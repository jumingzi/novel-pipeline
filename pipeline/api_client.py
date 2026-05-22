import json
import re
import time
import asyncio
import httpx
from typing import Optional, Callable, Awaitable
from config import (
    AGENT_CONFIG, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL,
    MAX_RETRIES, RETRY_BACKOFF, JSON_FIX_MAX_RETRIES,
    HTTP_TIMEOUT, load_api_key,
)

API_ENDPOINT = f"{DEEPSEEK_BASE_URL}/v1/chat/completions"


def fix_json_output(raw: str) -> str:
    """Extract valid JSON from potentially noisy API response (thinking mode, etc)."""
    text = raw.strip()

    # Remove markdown code fences
    text = re.sub(r"^```(?:json)?\s*\n?", "", text)
    text = re.sub(r"\n?```\s*$", "", text)

    # Find ALL complete JSON objects in the text, return the largest valid one
    candidates = []
    for m in re.finditer(r"\{", text):
        start = m.start()
        candidate = text[start:]
        depth = 0
        end = -1
        for i, ch in enumerate(candidate):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        if end > 0:
            candidate = candidate[:end]
            try:
                json.loads(candidate)
                candidates.append((len(candidate), candidate))
            except json.JSONDecodeError:
                continue

    if candidates:
        # Return the largest valid JSON object (outermost)
        candidates.sort(key=lambda x: x[0], reverse=True)
        return candidates[0][1]

    return text.strip()


class DeepSeekClient:
    def __init__(self, api_key: Optional[str] = None, progress_callback: Optional[Callable[[dict], Awaitable[None]]] = None):
        self.api_key = api_key or load_api_key()
        self.progress_callback = progress_callback

    async def _emit(self, agent_id: str, status: str, message: str = ""):
        if self.progress_callback:
            await self.progress_callback({
                "agent_id": agent_id,
                "status": status,
                "message": message,
                "timestamp": time.time(),
            })

    async def call(
        self,
        agent_id: str,
        messages: list[dict],
        _client: Optional[httpx.AsyncClient] = None,
    ) -> str:
        cfg = AGENT_CONFIG[agent_id]
        await self._emit(agent_id, "running", f"Agent {agent_id} 开始调用 API")

        body = {
            "model": DEEPSEEK_MODEL,
            "messages": messages,
            "temperature": cfg["temperature"],
        }

        # thinking mode
        if cfg.get("thinking"):
            body["thinking"] = {"type": "enabled"}
            if "reasoning_effort" in cfg:
                body["thinking"]["reasoning_effort"] = cfg["reasoning_effort"]

        # response_format — skip when thinking is enabled (API doesn't support both)
        if cfg.get("response_format") == "json_object" and not cfg.get("thinking"):
            body["response_format"] = {"type": "json_object"}

        # optional params
        if "max_tokens" in cfg:
            body["max_tokens"] = cfg["max_tokens"]
        if "frequency_penalty" in cfg:
            body["frequency_penalty"] = cfg["frequency_penalty"]

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        # Debug: print what we're sending
        msg_sizes = [len(m.get("content","")) for m in messages]
        print(f"[API] {agent_id} thinking={cfg.get('thinking')} effort={cfg.get('reasoning_effort','')} msgs={msg_sizes} total={sum(msg_sizes)}chars", flush=True)

        last_error = None
        for attempt in range(MAX_RETRIES + 1):
            try:
                if _client:
                    resp = await _client.post(
                        API_ENDPOINT, json=body, headers=headers,
                        timeout=HTTP_TIMEOUT,
                    )
                else:
                    async with httpx.AsyncClient() as client:
                        resp = await client.post(
                            API_ENDPOINT, json=body, headers=headers,
                            timeout=HTTP_TIMEOUT,
                        )

                resp_len = len(resp.content) if hasattr(resp, 'content') else 0
                print(f"[API] {agent_id} response HTTP {resp.status_code} len={resp_len} attempt={attempt}", flush=True)

                if resp.status_code >= 500:
                    last_error = f"HTTP {resp.status_code}"
                    if attempt < MAX_RETRIES:
                        await self._emit(agent_id, "running",
                            f"HTTP {resp.status_code}, 重试 {attempt+1}/{MAX_RETRIES}")
                        await _async_sleep(RETRY_BACKOFF[min(attempt, len(RETRY_BACKOFF)-1)])
                        continue
                    raise RuntimeError(f"API error after {MAX_RETRIES} retries: HTTP {resp.status_code}")

                if resp.status_code != 200:
                    data = resp.json()
                    err = data.get("error", {}).get("message", resp.text)
                    print(f"[API] {agent_id} ERROR HTTP {resp.status_code}: {err}", flush=True)
                    raise RuntimeError(f"API returned HTTP {resp.status_code}: {err}")

                data = resp.json()
                if "choices" not in data or not data["choices"]:
                    raise RuntimeError(f"API returned unexpected response: {json.dumps(data)[:300]}")
                content = data["choices"][0]["message"]["content"]

                # JSON format validation for agents that return json_object
                if cfg.get("response_format") == "json_object":
                    content = fix_json_output(content)
                    # Verify parseable
                    for json_fix_attempt in range(JSON_FIX_MAX_RETRIES + 1):
                        try:
                            json.loads(content)
                            break
                        except json.JSONDecodeError:
                            if json_fix_attempt < JSON_FIX_MAX_RETRIES:
                                await self._emit(agent_id, "running",
                                    f"JSON 损坏, 修复重试 {json_fix_attempt+1}/{JSON_FIX_MAX_RETRIES}")
                                # Re-request with fix instruction
                                fix_msg = {
                                    "role": "user",
                                    "content": "Fix JSON structure based on previous incomplete output. Output ONLY valid JSON, no markdown fences."
                                }
                                body["messages"] = messages + [
                                    {"role": "assistant", "content": content},
                                    fix_msg,
                                ]
                                content = await self._single_post(body, headers, _client)
                                content = fix_json_output(content)
                            else:
                                raise RuntimeError(f"JSON fix failed after {JSON_FIX_MAX_RETRIES} attempts")

                await self._emit(agent_id, "done", "完成")
                return content

            except (httpx.TimeoutException, httpx.ConnectError) as e:
                last_error = str(e)
                print(f"[API] {agent_id} NETWORK ERROR (attempt {attempt+1}): {e}", flush=True)
                if attempt < MAX_RETRIES:
                    await self._emit(agent_id, "running",
                        f"网络错误: {e}, 重试 {attempt+1}/{MAX_RETRIES}")
                    await _async_sleep(RETRY_BACKOFF[min(attempt, len(RETRY_BACKOFF)-1)])
                    continue
                raise RuntimeError(f"Network error after {MAX_RETRIES} retries: {e}")

        raise RuntimeError(f"Unexpected: {last_error}")

    async def _single_post(self, body: dict, headers: dict, _client=None) -> str:
        try:
            if _client:
                resp = await _client.post(API_ENDPOINT, json=body, headers=headers, timeout=HTTP_TIMEOUT)
            else:
                async with httpx.AsyncClient() as client:
                    resp = await client.post(API_ENDPOINT, json=body, headers=headers, timeout=HTTP_TIMEOUT)
        except (httpx.TimeoutException, httpx.ConnectError) as e:
            raise RuntimeError(f"Single post failed: {e}")
        if resp.status_code >= 500:
            raise RuntimeError(f"Retry call failed: HTTP {resp.status_code}")
        data = resp.json()
        return data["choices"][0]["message"]["content"]


async def _async_sleep(seconds: float):
    await asyncio.sleep(seconds)
