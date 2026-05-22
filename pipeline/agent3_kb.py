import json
import os
from pipeline.agent2_deconstructor import DeconstructionResult
from rag import NovelRAG, RetrievalContext
from config import AGENT4_MAX_CONTEXT_TOKENS


class KnowledgeBase:
    def __init__(self, base_dir: str = "./knowledge_base"):
        self.base_dir = base_dir

    def _genre_path(self, genre: str) -> str:
        return os.path.join(self.base_dir, genre)

    def _ensure_dir(self, genre: str):
        os.makedirs(self._genre_path(genre), exist_ok=True)

    def save_genre_data(self, genre: str, data: dict):
        self._ensure_dir(genre)
        files = {
            "characters": "character_cards.json",
            "plot_timeline": "plot_timeline.json",
            "world_settings": "world_settings.json",
            "style_profile": "style_profile.json",
        }
        for key, filename in files.items():
            if key in data and data[key]:
                filepath = os.path.join(self._genre_path(genre), filename)
                with open(filepath, "w", encoding="utf-8") as f:
                    json.dump(data[key], f, ensure_ascii=False, indent=2)

    def load_genre_data(self, genre: str) -> dict:
        result = {}
        files = {
            "characters": "character_cards.json",
            "plot_timeline": "plot_timeline.json",
            "world_settings": "world_settings.json",
            "style_profile": "style_profile.json",
        }
        for key, filename in files.items():
            filepath = os.path.join(self._genre_path(genre), filename)
            if os.path.exists(filepath):
                with open(filepath, "r", encoding="utf-8") as f:
                    result[key] = json.load(f)
        return result

    def update_genre_data(self, genre: str, new_data: dict):
        existing = self.load_genre_data(genre)
        for key in ["characters", "plot_timeline", "world_settings", "style_profile"]:
            if key in new_data and new_data[key]:
                if key in existing:
                    if key in ("characters", "plot_timeline"):
                        existing[key] = merge_lists(existing[key], new_data[key], key="name")
                    else:
                        existing[key] = {**existing[key], **new_data[key]}
                else:
                    existing[key] = new_data[key]
        self.save_genre_data(genre, existing)


def merge_lists(existing: list, new: list, key: str = "name") -> list:
    result = {item.get(key): item for item in existing if isinstance(item, dict)}
    for item in new:
        if not isinstance(item, dict):
            continue
        k = item.get(key)
        if k and k in result:
            result[k] = {**result[k], **item}
        else:
            result[k or str(len(result))] = item
    return list(result.values())


GENRE_KEYWORDS = {
    "玄幻": ["斗者", "斗气", "异火", "魂殿", "炼药", "斗帝", "武动", "斗破"],
    "仙侠": ["筑基", "金丹", "元婴", "剑修", "灵根", "渡劫", "飞升", "仙门", "练气"],
    "武侠": ["内功", "轻功", "掌门", "侠客", "武林", "五岳", "江湖"],
    "都市": ["重生", "总裁", "商业", "财阀", "都市", "神医", "保镖", "系统"],
    "恋爱": ["霸道", "甜宠", "总裁", "婚约", "白月光", "修罗场"],
    "历史": ["穿越", "古代", "皇帝", "太子", "权谋", "科举", "宫中"],
    "科幻": ["机甲", "星际", "AI", "基因", "末世", "赛博", "飞船"],
    "奇幻": ["魔法", "精灵", "龙", "勇者", "魔王", "剑与魔法"],
    "游戏": ["全息", "网游", "副本", "BOSS", "竞技", "排位", "电竞"],
    "悬疑": ["案件", "凶手", "推理", "鬼", "诅咒", "恐怖", "灵异"],
}


def detect_genre(characters: list[dict], hooks: list[dict]) -> str:
    all_text = json.dumps(characters, ensure_ascii=False) + json.dumps(hooks, ensure_ascii=False)
    scores = {}
    for genre, keywords in GENRE_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in all_text)
        if score > 0:
            scores[genre] = score
    if not scores:
        return "玄幻"
    return max(scores, key=scores.get)


def merge_character_cards(existing: list[dict], new_chars: list[dict]) -> list[dict]:
    return merge_lists(existing, new_chars, key="name")


async def update_knowledge_base(
    kb: KnowledgeBase, rag: NovelRAG,
    decon_results: list[DeconstructionResult], genre: str = "",
) -> dict:
    all_chars = []
    all_hooks = []
    all_style = {}
    all_foreshadowing = {"planted": [], "resolved": []}

    for r in decon_results:
        all_chars.extend(r.characters)
        all_hooks.extend(r.hooks)
        if r.style_dna and isinstance(r.style_dna, dict):
            all_style = r.style_dna
        fw = r.foreshadowing
        if not isinstance(fw, dict):
            fw = {"planted": [], "resolved": []}
        for f in fw.get("planted", []):
            all_foreshadowing["planted"].append(f)
        for f in fw.get("resolved", []):
            all_foreshadowing["resolved"].append(f)

    if not genre:
        genre = detect_genre(all_chars, all_hooks)

    existing = kb.load_genre_data(genre)
    merged_chars = merge_character_cards(existing.get("characters", []), all_chars)

    kb.update_genre_data(genre, {
        "characters": merged_chars,
        "plot_timeline": merge_lists(
            existing.get("plot_timeline", []),
            [{"hooks": all_hooks, "foreshadowing": all_foreshadowing}],
            key="description",
        ),
        "style_profile": {**existing.get("style_profile", {}), **all_style},
    })

    for i, c in enumerate(merged_chars):
        cid = f"{genre}_{c.get('name', f'unknown_{i}')}"
        rag.add_characters([{
            "id": cid, "name": c.get("name", ""),
            "description": json.dumps(c, ensure_ascii=False),
            "genre": genre, "chapter": c.get("chapter", 0),
        }])

    return {"genre": genre, "character_count": len(merged_chars)}


async def build_retrieval_context(
    rag: NovelRAG, kb: KnowledgeBase, genre: str,
    current_context: str, character_names: list[str] = None,
) -> RetrievalContext:
    ctx = RetrievalContext()
    if character_names:
        for name in character_names:
            results = rag.hybrid_search_characters(name, genre, top_k=5)
            ctx.characters.extend(results)
    else:
        results = rag.query_characters(current_context[:200], genre, top_k=10)
        ctx.characters = results
    results = rag.query_plot_events(current_context[:200], genre, top_k=10)
    ctx.plot_events = results
    genre_data = kb.load_genre_data(genre)
    ctx.style_dna = genre_data.get("style_profile", {})
    ctx.world_settings = genre_data.get("world_settings", {})
    ctx = ctx.trim_to_tokens(AGENT4_MAX_CONTEXT_TOKENS)
    return ctx
