import json
import re
import time
import asyncio
import httpx
from typing import Optional, Callable
from config import (
    AGENT_CONFIG, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL,
    MAX_RETRIES, RETRY_BACKOFF, JSON_FIX_MAX_RETRIES,
    HTTP_TIMEOUT, load_api_key,
)

API_ENDPOINT = f"{DEEPSEEK_BASE_URL}/v1/chat/completions"


def fix_json_output(raw: str) -> str:
    """Attempt to extract valid JSON from a potentially malformed response."""
    text = raw.strip()

    # Remove markdown code fences
    text = re.sub(r"^```(?:json)?\s*\n?", "", text)
    text = re.sub(r"\n?```\s*$", "", text)

    # If the text starts with non-JSON content, try to find the first { or [
    first_brace = text.find("{")
    first_bracket = text.find("[")
    start = 0
    if first_brace != -1 and first_bracket != -1:
        start = min(first_brace, first_bracket)
    elif first_brace != -1:
        start = first_brace
    elif first_bracket != -1:
        start = first_bracket

    if start > 0:
        text = text[start:]

    # Try to find matching closing bracket
    if text.startswith("{"):
        depth = 0
        end = -1
        for i, ch in enumerate(text):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        if end > 0:
            text = text[:end]

    return text.strip()


class DeepSeekClient:
    def __init__(self, api_key: Optional[str] = None, progress_callback: Optional[Callable] = None):
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

        # response_format for json agents
        if cfg.get("response_format") == "json_object":
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

                if resp.status_code >= 500:
                    last_error = f"HTTP {resp.status_code}"
                    if attempt < MAX_RETRIES:
                        await self._emit(agent_id, "running",
                            f"HTTP {resp.status_code}, 重试 {attempt+1}/{MAX_RETRIES}")
                        await _async_sleep(RETRY_BACKOFF[min(attempt, len(RETRY_BACKOFF)-1)])
                        continue
                    raise RuntimeError(f"API error after {MAX_RETRIES} retries: HTTP {resp.status_code}")

                data = resp.json()
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
                                content = await self._retry_call(body, headers, _client)
                                content = fix_json_output(content)
                            else:
                                raise RuntimeError(f"JSON fix failed after {JSON_FIX_MAX_RETRIES} attempts")

                await self._emit(agent_id, "done", "完成")
                return content

            except (httpx.TimeoutException, httpx.ConnectError) as e:
                last_error = str(e)
                if attempt < MAX_RETRIES:
                    await self._emit(agent_id, "running",
                        f"网络错误: {e}, 重试 {attempt+1}/{MAX_RETRIES}")
                    await _async_sleep(RETRY_BACKOFF[min(attempt, len(RETRY_BACKOFF)-1)])
                    continue
                raise RuntimeError(f"Network error after {MAX_RETRIES} retries: {e}")

        raise RuntimeError(f"Unexpected: {last_error}")

    async def _retry_call(self, body: dict, headers: dict, _client=None) -> str:
        if _client:
            resp = await _client.post(API_ENDPOINT, json=body, headers=headers, timeout=HTTP_TIMEOUT)
        else:
            async with httpx.AsyncClient() as client:
                resp = await client.post(API_ENDPOINT, json=body, headers=headers, timeout=HTTP_TIMEOUT)
        if resp.status_code >= 500:
            raise RuntimeError(f"Retry call failed: HTTP {resp.status_code}")
        data = resp.json()
        return data["choices"][0]["message"]["content"]


async def _async_sleep(seconds: float):
    await asyncio.sleep(seconds)
