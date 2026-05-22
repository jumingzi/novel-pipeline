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
):
    """Editor assistant chat — discuss plot, not write chapters."""
    orch = get_orchestrator()
    # Load KB context for the chat
    proj = orch.state.result.get("project", "") if orch.state.result else ""
    kb_context = ""
    if proj:
        data = orch.kb.load_project_data(proj)
        chars = data.get("characters", [])[:10]
        if chars:
            kb_context = "当前作品已收录角色: " + ", ".join(c.get("name", "?") for c in chars)
    reply = await orch.run_chat(message, genre, kb_context)
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
