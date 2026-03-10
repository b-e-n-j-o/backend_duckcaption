from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from api.transcription import router as transcription_router
from api.vimeo import router as vimeo_router
from api.notion import router as notion_router

app = FastAPI(title="Duck Caption API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers API
app.include_router(transcription_router, prefix="/api")
app.include_router(vimeo_router, prefix="/api")
app.include_router(notion_router, prefix="/api")
# Static frontend
BASE_DIR = Path(__file__).parent
STATIC_DIR = BASE_DIR / "static"
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
