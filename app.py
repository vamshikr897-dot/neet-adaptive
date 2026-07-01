import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from starlette.requests import Request

import config
import db
from orchestrator.state_machine import SessionNotFoundError
from orchestrator import state_machine
from orchestrator.states import SessionStatus
from repositories import taxonomy_repo, report_repo
from agents import gap_analyser

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("neet_adaptive")

_STARTED_AT = datetime.now(timezone.utc).isoformat()

BASE_DIR = Path(__file__).resolve().parent


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    logger.info("DB ready at %s", config.DB_PATH)
    yield


app = FastAPI(lifespan=lifespan)
templates = Jinja2Templates(directory=BASE_DIR / "templates")


@app.get("/")
def index(request: Request):
    return templates.TemplateResponse(request, "index.html", {})


@app.get("/api/health")
def health():
    return {"status": "ok", "started_at": _STARTED_AT}


@app.get("/api/taxonomy/grades")
def get_grades():
    return {"grades": config.GRADE_LEVELS}


@app.get("/api/taxonomy/chapters")
def get_chapters(grade_level: str, subject: str | None = None):
    if grade_level not in config.GRADE_LEVELS:
        return JSONResponse(status_code=400, content={"error": f"grade_level must be one of {config.GRADE_LEVELS}"})
    if subject and subject not in config.SUBJECTS:
        return JSONResponse(status_code=400, content={"error": f"subject must be one of {config.SUBJECTS}"})
    chapters = taxonomy_repo.get_chapters(grade_level, subject)
    return {"chapters": chapters}


class StartSessionRequest(BaseModel):
    grade_level: str
    subject: str
    chapter: str
    selected_concepts: list[str] = Field(default_factory=list)


class AnswerRequest(BaseModel):
    selected_option: str | None = None
    time_taken_seconds: float = Field(..., ge=0)


@app.post("/api/sessions")
def start_session(payload: StartSessionRequest):
    if payload.grade_level not in config.GRADE_LEVELS:
        return JSONResponse(status_code=400, content={"error": f"grade_level must be one of {config.GRADE_LEVELS}"})
    if payload.subject not in config.SUBJECTS:
        return JSONResponse(status_code=400, content={"error": f"subject must be one of {config.SUBJECTS}"})
    try:
        result = state_machine.start_new(
            payload.grade_level, payload.subject, payload.chapter, payload.selected_concepts
        )
    except ValueError as e:
        return JSONResponse(status_code=400, content={"error": str(e)})
    return result


@app.get("/api/sessions/{session_id}/current")
def get_current_question(session_id: str):
    try:
        return state_machine.get_current(session_id)
    except SessionNotFoundError:
        return JSONResponse(status_code=404, content={"error": "Session not found."})


@app.post("/api/sessions/{session_id}/answer")
def submit_answer(session_id: str, payload: AnswerRequest):
    try:
        return state_machine.submit_answer(session_id, payload.selected_option, payload.time_taken_seconds)
    except SessionNotFoundError:
        return JSONResponse(status_code=404, content={"error": "Session not found."})


@app.post("/api/sessions/{session_id}/report")
def generate_report(session_id: str):
    state = state_machine.get_state(session_id)
    if state is None:
        return JSONResponse(status_code=404, content={"error": "Session not found."})
    if state.status not in (SessionStatus.COMPLETE, SessionStatus.DONE):
        return JSONResponse(status_code=409, content={"error": "Session is not yet complete."})
    existing = report_repo.get(session_id)
    if existing:
        return existing.model_dump()
    concepts = state_machine.available_concepts(state)
    report = gap_analyser.analyse_session(state, concepts)
    report_repo.insert(report)
    state.status = SessionStatus.DONE
    from repositories import session_repo
    session_repo.save(state)
    return report.model_dump()


@app.get("/api/sessions/{session_id}/report")
def get_report(session_id: str):
    report = report_repo.get(session_id)
    if report is None:
        return JSONResponse(status_code=404, content={"error": "Report not found."})
    return report.model_dump()


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled exception on %s", request.url.path)
    return JSONResponse(status_code=500, content={"error": "Something went wrong. Please try again."})


app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


if __name__ == "__main__":
    import socket
    import sys

    import uvicorn

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        if probe.connect_ex(("127.0.0.1", 8010)) == 0:
            sys.exit(
                "Port 8010 is already in use by another process (possibly serving stale "
                "code from before your last edit). Stop it first, then restart."
            )

    uvicorn.run("app:app", host="127.0.0.1", port=8010, reload=True)
