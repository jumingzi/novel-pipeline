import asyncio
import json
import os
import threading
from dataclasses import dataclass, field

from pipeline.api_client import DeepSeekClient
from pipeline.agent1_cleaner import process_file
from pipeline.agent2_deconstructor import deconstruct_all_chunks
from pipeline.agent3_kb import update_knowledge_base, build_retrieval_context, KnowledgeBase
from pipeline.agent4_writer import generate_chapter, generate_titles, get_inspiration, extract_reference_samples
from rag import NovelRAG, RetrievalContext
from config import DEFAULT_CHAPTER_WORDS


@dataclass
class PipelineState:
    current_step: str = "idle"
    progress: float = 0.0
    error: str = ""
    is_error: bool = False
    result: dict = field(default_factory=dict)

    def advance(self, step: str, status: str):
        self.current_step = step
        steps = ["agent1", "agent2", "agent3", "agent4"]
        if step in steps and status == "done":
            idx = steps.index(step) + 1
            self.progress = idx / len(steps)

    def set_error(self, msg: str):
        self.error = msg
        self.is_error = True


class ProgressBus:
    def __init__(self):
        self._queues: list[asyncio.Queue] = []

    def subscribe(self):
        q = asyncio.Queue()
        self._queues.append(q)
        return self._listen(q)

    async def _listen(self, q: asyncio.Queue):
        while True:
            event = await q.get()
            yield event

    async def emit(self, event: dict):
        for q in self._queues:
            await q.put(event)


class PipelineOrchestrator:
    def __init__(self, api_key: str = "", kb_dir: str = "./knowledge_base", chroma_dir: str = "./chroma_store"):
        self.bus = ProgressBus()
        self.state = PipelineState()
        api_key_final = api_key or None
        self.client = DeepSeekClient(api_key=api_key_final, progress_callback=self._on_progress)
        self.kb = KnowledgeBase(base_dir=kb_dir)
        self.rag = NovelRAG(persist_dir=chroma_dir)
        self._thread = None
        self._cancelled = False

    def cancel(self):
        self._cancelled = True
        self.client.cancel()
        self.state.current_step = "cancelled"

    def _check_cancel(self):
        if self._cancelled:
            raise RuntimeError("cancelled")

    async def _on_progress(self, event: dict):
        self.state.advance(event["agent_id"], event["status"])
        await self.bus.emit({**event, "progress": self.state.progress})

    async def run_analysis(self, filepath: str, genre: str = "", reference_files: list[str] = None,
                             start_chapter: int = 0, end_chapter: int = 0, fast_mode: bool = True,
                             project: str = "") -> dict:
        self._cancelled = False
        self.client.reset_cancel()
        # Fast mode: disable thinking for speed
        if fast_mode:
            import copy
            self.client._fast_mode = True
        try:
            self.state.advance("agent1", "running")
            chunks = process_file(filepath, start_chapter=start_chapter, end_chapter=end_chapter)
            raw_name = project or filepath.replace('\\', '/').split('/')[-1].rsplit('.', 1)[0]
            project = raw_name
            self.state.advance("agent1", "done")
            self._check_cancel()

            self.state.advance("agent2", "running")
            # Check for existing checkpoint
            ckpt_path = os.path.join(self.kb._project_path(project), "_checkpoint.json")
            if os.path.exists(ckpt_path):
                print(f"[Orchestrator] 发现断点, 跳过Agent2直接归档: {project}", flush=True)
                with open(ckpt_path, "r", encoding="utf-8") as f:
                    ckpt = json.load(f)
                decon_dicts = ckpt.get("decon_results", ckpt)
                from pipeline.agent2_deconstructor import DeconstructionResult
                decon_results = [DeconstructionResult(**d) for d in decon_dicts]
            else:
                decon_results = await deconstruct_all_chunks(self.client, chunks, on_progress=self._on_progress, cancel_check=lambda: self._check_cancel())
                # Save checkpoint
                decon_dicts = [r.to_dict() if hasattr(r, 'to_dict') else r for r in decon_results]
                os.makedirs(os.path.dirname(ckpt_path), exist_ok=True)
                with open(ckpt_path, "w", encoding="utf-8") as f:
                    json.dump({
                        "chunk_count": len(decon_dicts),
                        "file_path": filepath,
                        "genre": genre,
                        "decon_results": decon_dicts,
                    }, f, ensure_ascii=False)
            self.state.advance("agent2", "done")
            self._check_cancel()

            self.state.advance("agent3", "running")
            genre = genre or "玄幻"
            kb_result = await update_knowledge_base(self.kb, self.rag, decon_results, genre, project=project)
            # Remove checkpoint after successful Agent3
            if os.path.exists(ckpt_path):
                os.remove(ckpt_path)
            self.state.advance("agent3", "done")

            ref_style = ""
            if reference_files:
                ref_style = extract_reference_samples(reference_files)

            self.state.result = {
                "project": project,
                "chunks": [{"chunk_id": c.chunk_id, "token_count": c.token_count} for c in chunks],
                "genre": kb_result["genre"],
                "character_count": kb_result["character_count"],
                "reference_style": ref_style,
                "decon_results": [r.to_dict() for r in decon_results],
            }
            return self.state.result
        except RuntimeError as e:
            if str(e) == "cancelled":
                return self.state.result
            self.state.set_error(str(e))
            raise
        except Exception as e:
            self.state.set_error(str(e))
            raise

    async def run_chapter(self, outline: str, genre: str, word_count: int = DEFAULT_CHAPTER_WORDS,
                           reference_style: str = "", project: str = "") -> str:
        proj = project or genre
        try:
            self.state.advance("agent4", "running")
            ctx = await build_retrieval_context(self.rag, self.kb, genre, outline, project=proj)
            style = self.kb.load_project_data(proj).get("style_profile", {})
            chapter = await generate_chapter(self.client, outline, ctx.to_prompt_text(), style,
                                              reference_style, word_count)
            self.state.advance("agent4", "done")
            self.state.result["last_chapter"] = chapter
            return chapter
        except Exception as e:
            self.state.set_error(str(e))
            raise

    def _get_kb_summary(self) -> str:
        """Build a summary of current project's KB for context injection."""
        proj = self.state.result.get("project", "") if self.state.result else ""
        if not proj:
            return ""
        data = self.kb.load_project_data(proj)
        parts = []
        style = data.get("style_profile", {})
        if style:
            parts.append(f"文风: 对白占比{style.get('dialogue_ratio','?')}, 成语密度{style.get('idiom_density','?')}, 镜头模式{style.get('camera_sequence','')}")
        chars = data.get("characters", [])[:15]
        if chars:
            parts.append("角色: " + ", ".join(c.get("name", "?") for c in chars))
        world = data.get("world_settings", {})
        if world and world.get("genre"):
            parts.append(f"题材: {world['genre']}")
        timeline = data.get("plot_timeline", [])
        if timeline:
            hooks = []
            for t in timeline[-3:]:
                if isinstance(t, dict) and t.get("hooks"):
                    for h in t["hooks"][:3]:
                        hooks.append(h.get("description", "")[:50])
            if hooks:
                parts.append("近期剧情: " + "; ".join(hooks))
        return "\n".join(parts)

    async def run_titles(self, synopsis: str, genre: str) -> str:
        kb = self._get_kb_summary()
        if kb:
            synopsis = f"[知识库参考]\n{kb}\n\n[概要]\n{synopsis}"
        return await generate_titles(self.client, synopsis, genre)

    async def run_chat(self, message: str, genre: str, kb_context: str = "", history: list[dict] = None) -> str:
        """Editor assistant — discuss plot ideas, not write chapters. Supports conversation history and KB context."""
        orig = self.client._fast_mode
        self.client._fast_mode = True
        try:
            system = "你是一位经验丰富的网文编辑和创作顾问。你不是在写小说，而是在和作者讨论剧情、分析人物、提供建议。请用对话的语气回复，不要长篇大论。每次回复控制在300字以内。记住之前的对话内容。"
            kb_text = self._get_kb_summary()
            user = f"题材: {genre}\n"
            if kb_text:
                user += f"[知识库参考]\n{kb_text}\n\n"
            if kb_context:
                user += f"{kb_context}\n"
            user += f"作者提问: {message}"
            msgs = [{"role": "system", "content": system}]
            if history:
                for h in history[-50:]:
                    msgs.append(h)
            msgs.append({"role": "user", "content": user})
            reply = await self.client.call("agent4", msgs)
            return reply
        finally:
            self.client._fast_mode = orig

    async def run_inspiration(self, stuck_point: str) -> str:
        refs = self._get_related_references(stuck_point)
        kb = self._get_kb_summary()
        if kb:
            stuck_point = f"[知识库参考]\n{kb}\n\n[卡文处]\n{stuck_point}"
        return await get_inspiration(self.client, stuck_point, refs)

    def _get_related_references(self, query: str) -> list[str]:
        results = self.rag.query_plot_events(query, top_k=5)
        return [f"参考剧情: {r['description']}" for r in results]

    def start_analysis_background(self, filepath: str, genre: str = "", reference_files: list[str] = None,
                                    start_chapter: int = 0, end_chapter: int = 0, fast_mode: bool = True,
                                    project: str = ""):
        self._thread = threading.Thread(
            target=lambda: asyncio.run(self.run_analysis(filepath, genre, reference_files, start_chapter, end_chapter, fast_mode, project)),
            daemon=True)
        self._thread.start()

    async def run_batch(self):
        """Generate multiple chapters from beat sheet, chaining hooks."""
        beats = getattr(self, '_batch_beats', [])
        genre = getattr(self, '_batch_genre', '玄幻')
        project = getattr(self, '_batch_project', '')
        chapters = []
        prev_hook = ""
        for i, beat in enumerate(beats):
            self._check_cancel()
            outline = beat.get("plot", str(beat))
            if prev_hook:
                outline = f"[上一章结尾钩子: {prev_hook}]\n\n{outline}"
            await self._on_progress({"agent_id": "agent4", "status": "running", "message": f"生成第{i+1}/{len(beats)}章"})
            chapter = await self.run_chapter(outline, genre, word_count=beat.get("words", 1500), project=project)
            chapters.append({"chapter": i+1, "title": beat.get("title", f"第{i+1}章"), "content": chapter})
            self._batch_index = i + 1
            self._batch_chapters = chapters
            # Extract last 100 chars as hook for next chapter
            prev_hook = chapter[-200:] if len(chapter) > 200 else chapter[-50:]
        self.state.result["batch_chapters"] = chapters
        await self._on_progress({"agent_id": "agent4", "status": "done", "message": f"批量生成完成: {len(chapters)}章"})

    def start_batch_background(self):
        self._thread = threading.Thread(
            target=lambda: asyncio.run(self.run_batch()),
            daemon=True)
        self._thread.start()

    def start_chapter_background(self, outline: str, genre: str, word_count: int = 3000, reference_style: str = ""):
        proj = self.state.result.get("project", "") if self.state.result else ""
        self._thread = threading.Thread(
            target=lambda: asyncio.run(self.run_chapter(outline, genre, word_count, reference_style, project=proj)),
            daemon=True)
        self._thread.start()
