import os
os.environ.setdefault("ANONYMIZED_TELEMETRY", "false")

import json
import chromadb
import tiktoken
from dataclasses import dataclass, field

ENC = tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str) -> int:
    return len(ENC.encode(text))


@dataclass
class RetrievalContext:
    characters: list[dict] = field(default_factory=list)
    plot_events: list[dict] = field(default_factory=list)
    style_dna: dict = field(default_factory=dict)
    world_settings: dict = field(default_factory=dict)

    def to_prompt_text(self) -> str:
        parts = []
        if self.characters:
            parts.append("【相关角色】")
            for c in self.characters:
                parts.append(f"- {c.get('name', '?')}: {c.get('description', '')[:200]}")
        if self.plot_events:
            parts.append("【相关剧情】")
            for p in self.plot_events:
                parts.append(f"- 第{p.get('chapter','?')}章: {p.get('description','')[:200]}")
        if self.style_dna:
            parts.append(f"【文风特征】{json.dumps(self.style_dna, ensure_ascii=False)}")
        if self.world_settings:
            parts.append(f"【世界观】{json.dumps(self.world_settings, ensure_ascii=False)}")
        return "\n".join(parts)

    def trim_to_tokens(self, max_tokens: int) -> "RetrievalContext":
        current = self.to_prompt_text()
        if count_tokens(current) <= max_tokens:
            return self
        trimmed = RetrievalContext(
            characters=self.characters.copy(),
            plot_events=self.plot_events.copy(),
            style_dna=self.style_dna,
            world_settings=self.world_settings,
        )
        while count_tokens(trimmed.to_prompt_text()) > max_tokens:
            if len(trimmed.plot_events) > 1:
                trimmed.plot_events = trimmed.plot_events[:-1]
            elif len(trimmed.characters) > 1:
                trimmed.characters = trimmed.characters[:-1]
            elif trimmed.world_settings:
                trimmed.world_settings = {}
            elif trimmed.style_dna:
                trimmed.style_dna = {}
            else:
                break
        return trimmed


class NovelRAG:
    def __init__(self, persist_dir: str = "./chroma_store"):
        self.client = chromadb.PersistentClient(path=persist_dir)
        self._characters = self.client.get_or_create_collection("characters")
        self._plot_events = self.client.get_or_create_collection("plot_events")
        self._writing_samples = self.client.get_or_create_collection("writing_samples")

    def add_characters(self, characters: list[dict]):
        if not characters:
            return
        ids = [c["id"] for c in characters]
        docs = [f"{c['name']}: {c.get('description', '')}" for c in characters]
        metadatas = [{"name": c["name"], "genre": c.get("genre", ""), "chapter": c.get("chapter", 0)} for c in characters]
        self._characters.upsert(ids=ids, documents=docs, metadatas=metadatas)

    def query_characters(self, query: str, genre: str = "", top_k: int = 10) -> list[dict]:
        where = {"genre": genre} if genre else None
        results = self._characters.query(query_texts=[query], n_results=top_k, where=where)
        if not results["ids"][0]:
            return []
        return [
            {"id": rid, "name": meta.get("name", ""), "description": doc,
             "genre": meta.get("genre", ""), "chapter": meta.get("chapter", 0),
             "score": 1.0 - dist}
            for rid, doc, meta, dist in zip(
                results["ids"][0], results["documents"][0],
                results["metadatas"][0], results["distances"][0])
        ]

    def add_plot_events(self, events: list[dict]):
        if not events:
            return
        ids = [e["id"] for e in events]
        docs = [e["description"] for e in events]
        metadatas = [{"chapter": e.get("chapter", 0), "genre": e.get("genre", "")} for e in events]
        self._plot_events.upsert(ids=ids, documents=docs, metadatas=metadatas)

    def query_plot_events(self, query: str, genre: str = "", top_k: int = 10) -> list[dict]:
        where = {"genre": genre} if genre else None
        results = self._plot_events.query(query_texts=[query], n_results=top_k, where=where)
        if not results["ids"][0]:
            return []
        return [
            {"id": rid, "description": doc, "chapter": meta.get("chapter", 0), "score": 1.0 - dist}
            for rid, doc, meta, dist in zip(
                results["ids"][0], results["documents"][0],
                results["metadatas"][0], results["distances"][0])
        ]

    def hybrid_search_characters(self, query: str, genre: str = "", top_k: int = 10,
                                  keyword_weight: float = 0.4, vector_weight: float = 0.6) -> list[dict]:
        vec_results = self.query_characters(query, genre, top_k * 2)
        for r in vec_results:
            kw_score = 0.0
            if query in r.get("name", ""):
                kw_score = 1.0
            elif any(q_char in r.get("name", "") for q_char in query):
                kw_score = 0.5
            r["final_score"] = kw_score * keyword_weight + r.get("score", 0) * vector_weight
        vec_results.sort(key=lambda x: x.get("final_score", 0), reverse=True)
        return vec_results[:top_k]
