import json
import os
import uuid
import warnings
from pathlib import Path

import logging

# Suppress noisy library warnings
warnings.filterwarnings("ignore", category=UserWarning, module="ebooklib")
warnings.filterwarnings("ignore", category=FutureWarning, module="ebooklib")
warnings.filterwarnings("ignore", message=".*Skipping data.*")

# Suppress ChromaDB telemetry noise (library bug with posthog)
logging.getLogger("chromadb").setLevel(logging.ERROR)

from fastapi import FastAPI, Request, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from pipeline.orchestrator import PipelineOrchestrator
from config import load_api_key

# Suppress "Skipping data after last boundary" multipart warning
logging.getLogger("multipart").setLevel(logging.ERROR)

# Silence /api/state and /api/events polling noise
class PollFilter(logging.Filter):
    def filter(self, record):
        msg = record.getMessage()
        skip = ("/api/state" in msg or "/api/events" in msg)
        return not skip

logging.getLogger("uvicorn.access").addFilter(PollFilter())

# Also suppress root-level "Failed to send telemetry" prints
import sys
_original_stderr_write = sys.stderr.write
def _filtered_stderr_write(s):
    if "Failed to send telemetry" in s:
        return len(s)
    return _original_stderr_write(s)
sys.stderr.write = _filtered_stderr_write

app = FastAPI(title="小说矩阵工坊")

BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "webui" / "templates"))
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "webui" / "static")), name="static")

UPLOAD_DIR = BASE_DIR / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

orchestrator: PipelineOrchestrator = None


def get_orchestrator() -> PipelineOrchestrator:
    global orchestrator
    if orchestrator is None:
        key = load_api_key()
        orchestrator = PipelineOrchestrator(
            api_key=key,
            kb_dir=str(BASE_DIR / "knowledge_base"),
            chroma_dir=str(BASE_DIR / "chroma_store"),
        )
    return orchestrator


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/api/upload")
async def upload_file(file: UploadFile = File(...)):
    ext = Path(file.filename).suffix.lower()
    if ext not in (".txt", ".epub", ".mobi"):
        raise HTTPException(400, f"不支持的文件格式: {ext}")
    file_id = str(uuid.uuid4())[:8]
    save_path = UPLOAD_DIR / f"{file_id}{ext}"
    content = await file.read()
    save_path.write_bytes(content)
    return JSONResponse({"file_id": file_id, "filename": file.filename, "path": str(save_path), "size": len(content)})


@app.post("/api/upload-reference")
async def upload_reference(file: UploadFile = File(...)):
    ext = Path(file.filename).suffix.lower()
    if ext not in (".txt", ".epub", ".mobi"):
        raise HTTPException(400, f"不支持的文件格式: {ext}")
    file_id = str(uuid.uuid4())[:8]
    save_path = UPLOAD_DIR / f"ref_{file_id}{ext}"
    content = await file.read()
    save_path.write_bytes(content)
    return JSONResponse({"file_id": file_id, "filename": file.filename, "path": str(save_path)})


@app.post("/api/analyze")
async def start_analysis(
    file_path: str = Form(...),
    genre: str = Form(""),
    reference_paths: str = Form(""),
    start_chapter: int = Form(0),
    end_chapter: int = Form(0),
    fast_mode: bool = Form(True),
    project: str = Form(""),
):
    orch = get_orchestrator()
    refs = json.loads(reference_paths) if reference_paths else None
    orch.start_analysis_background(file_path, genre, refs, start_chapter, end_chapter, fast_mode, project)
    return JSONResponse({"status": "started"})


@app.post("/api/generate-chapter")
async def generate_chapter_endpoint(
    outline: str = Form(...),
    genre: str = Form("玄幻"),
    word_count: int = Form(3000),
    reference_style: str = Form(""),
):
    orch = get_orchestrator()
    orch.start_chapter_background(outline, genre, word_count, reference_style)
    return JSONResponse({"status": "started"})


@app.post("/api/titles")
async def generate_titles_endpoint(
    synopsis: str = Form(...),
    genre: str = Form("玄幻"),
):
    orch = get_orchestrator()
    titles = await orch.run_titles(synopsis, genre)
    return JSONResponse({"titles": titles})


@app.post("/api/chat")
async def chat_with_editor(
    message: str = Form(...),
    genre: str = Form("玄幻"),
    history: str = Form("[]"),
):
    """Editor assistant chat — discuss plot, not write chapters."""
    orch = get_orchestrator()
    proj = orch.state.result.get("project", "") if orch.state.result else ""
    kb_context = ""
    if proj:
        data = orch.kb.load_project_data(proj)
        chars = data.get("characters", [])[:10]
        if chars:
            kb_context = "当前作品已收录角色: " + ", ".join(c.get("name", "?") for c in chars)
    try:
        hist = json.loads(history) if history else []
    except Exception:
        hist = []
    reply = await orch.run_chat(message, genre, kb_context, history=hist)
    return JSONResponse({"reply": reply})


@app.post("/api/inspiration")
async def get_inspiration_endpoint(stuck_point: str = Form(...)):
    orch = get_orchestrator()
    suggestion = await orch.run_inspiration(stuck_point)
    return JSONResponse({"suggestion": suggestion})


@app.post("/api/stop")
async def stop_pipeline():
    orch = get_orchestrator()
    orch.cancel()
    return JSONResponse({"status": "cancelled"})


@app.post("/api/save-chapter")
async def save_chapter(
    content: str = Form(...),
    chapter_num: int = Form(0),
    project: str = Form(""),
):
    """Save an adopted chapter to the project directory."""
    orch = get_orchestrator()
    proj = project or (orch.state.result.get("project", "") if orch.state.result else "")
    if not proj:
        raise HTTPException(400, "No project selected")
    chapters_dir = os.path.join(orch.kb._project_path(proj), "chapters")
    os.makedirs(chapters_dir, exist_ok=True)
    num = chapter_num or len(os.listdir(chapters_dir)) + 1
    fname = f"chapter_{num:03d}.txt"
    with open(os.path.join(chapters_dir, fname), "w", encoding="utf-8") as f:
        f.write(content)
    return JSONResponse({"chapter": num, "filename": fname})


@app.get("/api/export/{project}")
async def export_project(project: str):
    """Export all project data as JSON."""
    orch = get_orchestrator()
    data = orch.kb.load_project_data(project)
    chapters_dir = os.path.join(orch.kb._project_path(project), "chapters")
    if os.path.exists(chapters_dir):
        chapters = {}
        for f in sorted(os.listdir(chapters_dir)):
            with open(os.path.join(chapters_dir, f), "r", encoding="utf-8") as cf:
                chapters[f] = cf.read()
        data["chapters"] = chapters
    return JSONResponse(data)


@app.get("/api/compare")
async def compare_projects(a: str = "", b: str = ""):
    """Compare two projects' style profiles."""
    orch = get_orchestrator()
    result = {}
    for proj in [a, b]:
        if proj:
            d = orch.kb.load_project_data(proj)
            result[proj] = {
                "style": d.get("style_profile", {}),
                "character_count": len(d.get("characters", [])),
                "genre": d.get("world_settings", {}).get("genre", ""),
            }
    return JSONResponse(result)


@app.post("/api/create-project")
async def create_project(
    title: str = Form(...),
    genre: str = Form("玄幻"),
    synopsis: str = Form(""),
    characters: str = Form(""),
    golden_finger: str = Form(""),
):
    """Create a new original project from scratch."""
    orch = get_orchestrator()
    project = title or "未命名项目"
    data = {
        "characters": [],
        "plot_timeline": [],
        "world_settings": {"genre": genre, "synopsis": synopsis, "golden_finger": golden_finger, "title": project},
        "style_profile": {},
    }
    if characters:
        for c_name in [x.strip() for x in characters.split(",") if x.strip()]:
            data["characters"].append({"name": c_name, "explicit_traits": "", "hidden_motivation": "", "core_conflict": ""})
    orch.kb.save_project_data(project, data)
    return JSONResponse({"status": "created", "project": project})


@app.post("/api/plan-outline")
async def plan_outline(
    idea: str = Form(...),
    genre: str = Form("玄幻"),
    project: str = Form(""),
):
    """Generate a beat sheet from a story idea, using KB context."""
    orch = get_orchestrator()
    # Get KB summary for context
    kb_text = ""
    if project:
        data = orch.kb.load_project_data(project)
        chars = data.get("characters", [])[:10]
        style = data.get("style_profile", {})
        if chars:
            kb_text = "角色: " + ", ".join(c.get("name","?") for c in chars)
        if style:
            kb_text += f"\n文风: 对白{style.get('dialogue_ratio','?')}, 句长{style.get('avg_sentence_length','?')}"
    msgs = [
        {"role": "system", "content": "你是资深网文大纲规划师。把用户的想法展开为6-8个节拍的章节细纲（起承转合结构）。每个节拍包含：节拍标题、一句话剧情、预期爽点类型、字数建议。输出为JSON数组 [{beat:1, title:'', plot:'', dopamine:'', words:1500},...]。"},
        {"role": "user", "content": f"题材: {genre}\n{kb_text}\n\n想法: {idea}\n\n请生成节拍表，只输出JSON数组。"},
    ]
    reply = await orch.client.call("agent3", msgs)
    return JSONResponse({"outline": reply})


@app.post("/api/refine-beat")
async def refine_beat(
    beat: str = Form(...),
    feedback: str = Form(""),
    genre: str = Form("玄幻"),
):
    """Refine a single beat based on feedback."""
    orch = get_orchestrator()
    msgs = [
        {"role": "system", "content": "你是专业网文编辑。根据反馈优化这一节拍的内容，只输出优化后的JSON：{beat:N, title:'', plot:'', dopamine:'', words:1500}"},
        {"role": "user", "content": f"原始节拍: {beat}\n反馈: {feedback}\n题材: {genre}"},
    ]
    reply = await orch.client.call("agent3", msgs)
    return JSONResponse({"beat": reply})


@app.post("/api/batch-generate")
async def batch_generate(
    beats: str = Form(...),
    genre: str = Form("玄幻"),
    project: str = Form(""),
):
    """Generate multiple chapters from a beat sheet."""
    orch = get_orchestrator()
    try:
        beats_list = json.loads(beats)
    except Exception:
        raise HTTPException(400, "Invalid beat sheet JSON")
    orch._batch_beats = beats_list
    orch._batch_genre = genre
    orch._batch_project = project or genre
    orch._batch_index = 0
    orch._batch_chapters = []
    orch.start_batch_background()
    return JSONResponse({"status": "started", "total": len(beats_list)})


@app.get("/api/batch-state")
async def batch_state():
    orch = get_orchestrator()
    return JSONResponse({
        "current": getattr(orch, '_batch_index', 0),
        "total": len(getattr(orch, '_batch_beats', [])),
        "chapters": getattr(orch, '_batch_chapters', []),
    })


@app.get("/api/relationships/{project}")
async def get_relationships(project: str):
    """Get character relationships for visualization."""
    orch = get_orchestrator()
    data = orch.kb.load_project_data(project)
    chars = data.get("characters", [])
    # Extract relationships from plot_timeline hooks
    relationships = []
    timeline = data.get("plot_timeline", [])
    for t in timeline:
        if isinstance(t, dict) and t.get("hooks"):
            for h in t.get("hooks", []):
                rel = h.get("description", "")
                if any(kw in rel for kw in ["敌", "仇", "杀", "恩", "爱", "师徒", "兄弟", "姐妹", "父子", "母女"]):
                    relationships.append({"type": "hook", "description": rel[:100], "score": h.get("score", 5)})
    return JSONResponse({
        "characters": [{"name": c.get("name", "?"), "traits": c.get("explicit_traits", "")[:80]} for c in chars[:20]],
        "relationships": relationships[:30],
    })


@app.post("/api/regenerate")
async def regenerate_chapter(
    outline: str = Form(...),
    genre: str = Form("玄幻"),
    word_count: int = Form(1500),
    reference_style: str = Form(""),
    project: str = Form(""),
):
    """Regenerate chapter with same prompt, different seed."""
    orch = get_orchestrator()
    orch.start_chapter_background(outline, genre, word_count, reference_style, project)
    return JSONResponse({"status": "started"})


@app.post("/api/save-version")
async def save_version(
    content: str = Form(...),
    chapter_num: int = Form(0),
    project: str = Form(""),
):
    """Save a chapter version for version history."""
    orch = get_orchestrator()
    proj = project or (orch.state.result.get("project", "") if orch.state.result else "")
    if not proj: raise HTTPException(400, "No project")
    versions_dir = os.path.join(orch.kb._project_path(proj), "versions")
    os.makedirs(versions_dir, exist_ok=True)
    num = chapter_num or 1
    ts = str(int(__import__("time").time()))
    fname = f"ch{num:03d}_v{ts}.txt"
    with open(os.path.join(versions_dir, fname), "w", encoding="utf-8") as f:
        f.write(content)
    return JSONResponse({"filename": fname})


@app.get("/api/versions/{project}")
async def list_versions(project: str):
    """List saved chapter versions."""
    orch = get_orchestrator()
    versions_dir = os.path.join(orch.kb._project_path(project), "versions")
    result = []
    if os.path.exists(versions_dir):
        for f in sorted(os.listdir(versions_dir), reverse=True):
            with open(os.path.join(versions_dir, f), "r", encoding="utf-8") as cf:
                result.append({"filename": f, "content": cf.read()[:500]})
    return JSONResponse({"versions": result})


@app.get("/api/stats/{project}")
async def project_stats(project: str):
    """Get project statistics for dashboard."""
    orch = get_orchestrator()
    data = orch.kb.load_project_data(project)
    chars = data.get("characters", [])
    timeline = data.get("plot_timeline", [])
    style = data.get("style_profile", {})
    # Count hooks and dopamine by chapter
    hook_types = {}
    for t in timeline:
        if isinstance(t, dict) and t.get("hooks"):
            for h in t.get("hooks", []):
                tp = h.get("type", "其他")
                hook_types[tp] = hook_types.get(tp, 0) + 1
    chapters_dir = os.path.join(orch.kb._project_path(project), "chapters")
    chapter_count = len(os.listdir(chapters_dir)) if os.path.exists(chapters_dir) else 0
    return JSONResponse({
        "character_count": len(chars),
        "chapter_count": chapter_count,
        "style": style,
        "hook_distribution": hook_types,
    })


@app.post("/api/consistency-check")
async def consistency_check(
    chapter: str = Form(...),
    project: str = Form(""),
):
    """Check character consistency in generated chapter."""
    orch = get_orchestrator()
    data = {}
    if project:
        data = orch.kb.load_project_data(project)
    chars = data.get("characters", [])[:10]
    char_names = [c.get("name", "") for c in chars if c.get("name")]
    issues = []
    for name in char_names:
        if name and name not in chapter:
            issues.append(f"角色「{name}」未在本章出现")
    # Check word repetition
    words = chapter.replace("\n", "").replace(" ", "")
    from collections import Counter
    word_counts = Counter(words)
    for w, c in word_counts.most_common(20):
        if len(w) == 1 and c > 100:
            issues.append(f"「{w}」出现{c}次，可能过于频繁")
    return JSONResponse({"issues": issues, "verdict": "通过" if not issues else "发现问题"})


@app.get("/api/checkpoints")
async def get_checkpoints():
    """Scan knowledge_base for incomplete analyses (_checkpoint.json)."""
    orch = get_orchestrator()
    kb_dir = orch.kb.base_dir
    checkpoints = []
    if os.path.exists(kb_dir):
        for proj in os.listdir(kb_dir):
            ckpt_path = os.path.join(kb_dir, proj, "_checkpoint.json")
            if os.path.isfile(ckpt_path):
                try:
                    with open(ckpt_path, "r", encoding="utf-8") as f:
                        ckpt = json.load(f)
                    checkpoints.append({
                        "project": proj,
                        "chunks": ckpt.get("chunk_count", 0),
                        "file_path": ckpt.get("file_path", ""),
                        "genre": ckpt.get("genre", ""),
                    })
                except Exception:
                    checkpoints.append({"project": proj, "chunks": 0, "file_path": "", "genre": ""})
    return JSONResponse({"checkpoints": checkpoints})


@app.get("/api/state")
async def get_state(project: str = ""):
    orch = get_orchestrator()
    state = orch.state
    proj = project or state.result.get("project", "") if state.result else ""
    genre = state.result.get("genre", "玄幻") if state.result else "玄幻"
    # Load per-project data if project is set, otherwise from state
    if proj:
        data = orch.kb.load_project_data(proj)
    else:
        data = orch.kb.load_project_data(genre)
    return JSONResponse({
        "progress": state.progress,
        "current_step": state.current_step,
        "error": state.error,
        "is_error": state.is_error,
        "result": state.result if state.result else {},
        "knowledge_base": {
            "characters": data.get("characters", []),
            "character_count": len(data.get("characters", [])),
            "plot_timeline": data.get("plot_timeline", []),
            "foreshadowing_count": len(data.get("plot_timeline", [])),
            "style_profile": data.get("style_profile", {}),
            "world_settings": data.get("world_settings", {}),
            "genre": genre,
            "project": proj,
        },
        "projects": orch.kb.list_projects(),
    })


@app.get("/api/events")
async def sse_events(request: Request):
    orch = get_orchestrator()
    async def event_generator():
        async for event in orch.bus.subscribe():
            if await request.is_disconnected():
                break
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
    return StreamingResponse(event_generator(), media_type="text/event-stream")
