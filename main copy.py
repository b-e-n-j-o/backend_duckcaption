from fastapi import FastAPI, File, UploadFile, Query
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from pathlib import Path
from typing import List
import json
import requests

from core.supabase import upload_file, public_url
from core.jobs import supabase
from core.jobs import create_job, update_job, get_job
from core.stt_engine import process_stt
from core.token_counter import estimate_tokens
from core.translator import translate_srt_segments, SUPPORTED_LANGUAGES

from core.logger import get_logger

import subprocess


app = FastAPI(title="Duck Caption API")

# CORS pour dev local
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Chemins relatifs au répertoire backend
BACKEND_DIR = Path(__file__).parent
TMP_DIR = BACKEND_DIR / "tmp"
STATIC_DIR = BACKEND_DIR / "static"
TMP_DIR.mkdir(exist_ok=True)
STATIC_DIR.mkdir(exist_ok=True)

MAX_UPLOAD_SIZE = 100 * 1024 * 1024  # 100 MB


class TranslateRequest(BaseModel):
    languages: List[str]


@app.post("/upload")
async def upload_video(file: UploadFile = File(...)):
    content = await file.read()
    
    if len(content) > MAX_UPLOAD_SIZE:
        return JSONResponse(
            {"error": "File too large (max 100MB)"},
            status_code=413
        )
    
    # Save uploaded file
    job = create_job(file.filename)
    job_id = job["id"]

    tmp_src = TMP_DIR / f"{job_id}.mp4"
    with open(tmp_src, "wb") as f:
        f.write(content)

    # à ce stade = only local copy
    
    return {"job_id": job_id, "status": "uploaded"}




log = get_logger("duck")


@app.get("/audio/{job_id}")
def serve_audio(job_id: str):
    """Sert l'audio WAV pour le lecteur"""
    audio_path = TMP_DIR / f"{job_id}.wav"
    if not audio_path.exists():
        return JSONResponse({"error": "audio not found"}, status_code=404)
    return FileResponse(audio_path, media_type="audio/wav")


@app.get("/audio_info/{job_id}")
def get_audio_info(job_id: str):
    """Retourne les infos audio (durée, coût estimé)"""
    tmp_audio = TMP_DIR / f"{job_id}.wav"
    
    # Extract audio si pas déjà fait
    if not tmp_audio.exists():
        tmp_src = TMP_DIR / f"{job_id}.mp4"
        if tmp_src.exists():
            subprocess.run(["ffmpeg", "-y", "-i", str(tmp_src),
                    "-vn", "-ac", "1", "-ar", "16000", str(tmp_audio)],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    
    if not tmp_audio.exists():
        return JSONResponse({"error": "Audio not found"}, status_code=404)
    
    tokens = estimate_tokens(tmp_audio)
    return {
        "job_id": job_id,
        "duration_min": tokens["duration_min"],
        "duration_sec": tokens["duration_sec"],
        "estimated_cost": tokens["total_estimated_cost"],
        "whisper_cost_usd": tokens["whisper_cost_usd"],
        "gemini_tokens": tokens["gemini_tokens"]
    }


@app.post("/generate_srt/{job_id}")
def generate_srt_endpoint(
    job_id: str, 
    context: str = Query("", description="Contexte pour la transcription"),
    start_time: float = Query(None, description="Début en secondes"),
    end_time: float = Query(None, description="Fin en secondes"),
    max_words: int = Query(None, description="Nombre maximum de mots par segment SRT"),
    max_chars: int = Query(None, description="Nombre maximum de caractères par segment SRT")
):
    import math
    
    job = get_job(job_id)
    if not job:
        log.error(f"❌ SRT: Job not found {job_id}")
        return JSONResponse({"error": "job not found"}, status_code=404)

    # Valider et nettoyer les paramètres de temps
    if start_time is not None and (math.isnan(start_time) or start_time < 0):
        start_time = None
    if end_time is not None and (math.isnan(end_time) or end_time < 0):
        end_time = None

    tmp_audio = TMP_DIR / f"{job_id}.wav"
    tmp_srt = TMP_DIR / f"{job_id}.srt"

    try:
        log.info(f"🔁 STT processing for {job_id}")

        log.info("🎧 Extracting audio...")
        subprocess.run(["ffmpeg", "-y", "-i", str(TMP_DIR / f"{job_id}.mp4"),
                "-vn", "-ac", "1", "-ar", "16000", str(tmp_audio)],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        log.info("🤖 Applying AI STT engine...")
        process_stt(tmp_audio, tmp_srt, context=context, start_time=start_time, end_time=end_time, 
                   job_id=job_id, max_words=max_words, max_chars=max_chars)

        log.info("📤 Upload SRT...")
        dest = f"{job_id}/subtitles.srt"
        srt_url = upload_file(str(tmp_srt), dest)

        job = update_job(job_id, srt_url=srt_url, status="srt_ready")

        log.info(f"✅ SRT ready for {job_id} → {srt_url}")
        return {"job_id": job_id, "srt_url": srt_url}

    except Exception as e:
        log.error(f"🔥 SRT generation failed for {job_id}: {e}")
        update_job(job_id, status="error", error=str(e))
        return JSONResponse({"error": str(e)}, status_code=500)
    finally:
        # tmp_audio gardé pour le lecteur audio
        tmp_srt.unlink(missing_ok=True)

@app.get("/job/{job_id}")
def get_status(job_id: str):
    job = get_job(job_id)
    if not job:
        return JSONResponse({"error": "job not found"}, status_code=404)
    return job



@app.post("/translate_srt/{job_id}")
def translate_srt(job_id: str, request: TranslateRequest):
    """
    Traduit le SRT final en plusieurs langues
    languages: ["en", "nl"]
    """
    languages = request.languages
    job = get_job(job_id)
    if not job or not job.get("srt_url"):
        return JSONResponse({"error": "SRT not ready"}, status_code=404)
    
    try:
        # Télécharger SRT original
        original_srt = requests.get(job["srt_url"]).text
        
        translations = {}
        for lang in languages:
            if lang not in SUPPORTED_LANGUAGES:
                continue
            
            log.info(f"🌍 Translating to {lang}...")
            translated = translate_srt_segments(original_srt, lang, job_id)
            
            # Upload traduction
            tmp_path = TMP_DIR / f"{job_id}_{lang}.srt"
            tmp_path.write_text(translated, encoding="utf-8")
            
            dest = f"{job_id}/subtitles_{lang}.srt"
            url = upload_file(str(tmp_path), dest)
            translations[lang] = url
            
            tmp_path.unlink()
        
        # Update job
        update_job(job_id, translations=json.dumps(translations))
        
        return {
            "job_id": job_id,
            "translations": translations
        }
        
    except Exception as e:
        log.error(f"Translation failed: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/cleanup_proxy")
def cleanup_proxy():
    res = supabase.rpc("cleanup_old_objects").execute()
    return {"status": "ok", "detail": res.data}


# Servir le frontend EN DERNIER (sinon capture toutes les routes API)
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
