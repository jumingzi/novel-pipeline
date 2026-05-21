import json
import uuid
from pathlib import Path

import logging

from fastapi import FastAPI, Request, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from pipeline.orchestrator import PipelineOrchestrator
from config import load_api_key

# Silence /api/state and /api/events polling noise
class PollFilter(logging.Filter):
    def filter(self, record):
        msg = record.getMessage()
        skip = ("/api/state" in msg or "/api/events" in msg)
        return not skip

logging.getLogger("uvicorn.access").addFilter(PollFilter())

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
):
    orch = get_orchestrator()
    refs = json.loads(reference_paths) if reference_paths else None
    orch.start_analysis_background(file_path, genre, refs, start_chapter, end_chapter)
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


@app.post("/api/inspiration")
async def get_inspiration_endpoint(stuck_point: str = Form(...)):
    orch = get_orchestrator()
    suggestion = await orch.run_inspiration(stuck_point)
    return JSONResponse({"suggestion": suggestion})


@app.get("/api/state")
async def get_state():
    orch = get_orchestrator()
    state = orch.state
    genre = state.result.get("genre", "玄幻") if state.result else "玄幻"
    genre_data = orch.kb.load_genre_data(genre)
    return JSONResponse({
        "progress": state.progress,
        "current_step": state.current_step,
        "error": state.error,
        "is_error": state.is_error,
        "result": state.result if state.result else {},
        "knowledge_base": {
            "character_count": len(genre_data.get("characters", [])),
            "foreshadowing_count": len(genre_data.get("plot_timeline", [])),
        },
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
