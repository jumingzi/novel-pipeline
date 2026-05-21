import asyncio
import json
from dataclasses import dataclass
from typing import Optional, Callable, Awaitable
from pipeline.api_client import DeepSeekClient


@dataclass
class DeconstructionResult:
    characters: list[dict]
    relationships: list[dict]
    dopamine_curve: dict
    hooks: list[dict]
    style_dna: dict
    foreshadowing: dict

    def to_dict(self) -> dict:
        return {
            "characters": self.characters,
            "relationships": self.relationships,
            "dopamine_curve": self.dopamine_curve,
            "hooks": self.hooks,
            "style_dna": self.style_dna,
            "foreshadowing": self.foreshadowing,
        }


SYSTEM_PROMPT = """你是一位资深网文编辑，擅长深度拆解网络小说文本。

请对给定的文本块进行以下维度的分析，并以 JSON 格式返回：

1. **characters (人设拆解)**:
   - 列表中每个角色包含: name, explicit_traits (显性特征: 外貌/功法/职业/境界), hidden_motivation (隐性动机: 核心欲望), core_conflict (核心矛盾)
   - 仅提取本段文本中出现的角色

2. **relationships (人物关系网)**:
   - 列表中每对关系包含: pair (角色名列表), type (关系类型: 师徒/道侣/仇敌/盟友/亲属/竞争/陌生人), intimacy (亲密度 -10到10), power_gap (权力差: 上位/对等/下位), trend (关系演进: 升温/恶化/稳定)

3. **dopamine_curve (爽点与情绪曲线)**:
   - type: 爽点类型 (扮猪吃虎/念头通达/打脸/升级/夺宝/收后宫/复仇/逆袭/知识碾压/其他)
   - intensity: 情绪强度 (-5 到 5)
   - note: 简要点评

4. **hooks (黄金钩子)**:
   - 列表中每个钩子包含: type (悬念钩/利益期待钩/情感钩/冲突钩), score (1-10), description

5. **style_dna (语言微观特征)**:
   - idiom_density: 成语密度 (0-1)
   - dialogue_ratio: 对白占比 (0-1)
   - avg_sentence_length: 平均句长 (字数)
   - sentence_patterns: 独有句式指纹 (列表, 如 ["倒吸一口凉气", "恐怖如斯"])
   - camera_sequence: 镜头切换模式简述 (如 "先环境后人物再动作")

6. **foreshadowing (伏笔追踪)**:
   - planted: 本段埋伏笔列表 [{description, confidence: 0-1}]
   - resolved: 本段回收伏笔列表 [{description, reference}]

要求: 严格输出 JSON，不包含任何 markdown 围栏或其他文字。"""


def build_deconstruct_prompt(chunk_text: str, context_note: str = "") -> list[dict]:
    user_text = f"请分析以下小说文本：\n\n{chunk_text}"
    if context_note:
        user_text = f"{context_note}\n\n{user_text}"
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_text},
    ]


def parse_deconstruct_response(raw_json: str) -> DeconstructionResult:
    data = json.loads(raw_json)
    return DeconstructionResult(
        characters=data.get("characters", []),
        relationships=data.get("relationships", []),
        dopamine_curve=data.get("dopamine_curve", {}),
        hooks=data.get("hooks", []),
        style_dna=data.get("style_dna", {}),
        foreshadowing=data.get("foreshadowing", {"planted": [], "resolved": []}),
    )


async def deconstruct_chunk(
    client: DeepSeekClient, chunk_text: str, context_note: str = ""
) -> DeconstructionResult:
    messages = build_deconstruct_prompt(chunk_text, context_note)
    raw = await client.call("agent2", messages)
    return parse_deconstruct_response(raw)


async def deconstruct_all_chunks(
    client: DeepSeekClient, chunks: list, prev_context: str = "",
    on_progress: Optional[Callable[[dict], Awaitable[None]]] = None,
    parallel: int = 3,
) -> list[DeconstructionResult]:
    total = len(chunks)
    results = [None] * total

    async def _send(msg: str):
        if on_progress:
            await on_progress({"agent_id": "agent2", "status": "running", "message": msg, "timestamp": __import__("time").time()})

    await _send(f"开始拆解 {total} 个文本块 (并行{parallel})")

    # Process in parallel batches
    for batch_start in range(0, total, parallel):
        batch_end = min(batch_start + parallel, total)
        tasks = []
        for i in range(batch_start, batch_end):
            chunk = chunks[i]
            # For first batch and first item, use prev_context; otherwise summarize prev batch
            ctx = ""
            if i == 0 and prev_context:
                ctx = prev_context
            elif i > 0 and results[i-1]:
                ctx = _summarize_prev(results[i-1])
            tasks.append(_deconstruct_one(client, chunk, ctx, i))

        batch_results = await asyncio.gather(*tasks, return_exceptions=True)
        for i, r in zip(range(batch_start, batch_end), batch_results):
            if isinstance(r, Exception):
                await _send(f"Chunk {i+1}/{total} 失败: {r}")
                results[i] = DeconstructionResult([], [], {}, [], {}, {"planted": [], "resolved": []})
            else:
                results[i] = r

        done = min(batch_end, total)
        await _send(f"进度: {done}/{total} chunks")

    await _send(f"拆解完成: {total} 个文本块")
    return results


async def _deconstruct_one(client, chunk, ctx: str, idx: int):
    return await deconstruct_chunk(client, chunk.content, ctx)


def _summarize_prev(prev: DeconstructionResult) -> str:
    chars = ", ".join(c.get("name", "?") for c in prev.characters[:5])
    hooks = ", ".join(h.get("description", "")[:30] for h in prev.hooks[:3])
    return f"角色: {chars}; 钩子: {hooks}"
