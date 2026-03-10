from fastapi import APIRouter, File, UploadFile, Query
from fastapi.responses import JSONResponse, FileResponse
from pydantic import BaseModel

from pathlib import Path
from typing import List
import json
import requests
import subprocess
import math

from core.supabase import upload_file
from core.jobs import supabase
from core.jobs import create_job, update_job, get_job
from core.stt_engine import process_stt
from core.token_counter import estimate_tokens
from core.translator import translate_srt_segments
from core.srt_translator_v2 import translate_srt as translate_srt_v2, TranslationMode, SUPPORTED_LANGUAGES
from core.logger import get_logger
from core.scribe_v2_engine import process_scribe_v2


# ============================================================
# ROUTER
# ============================================================

router = APIRouter(
    prefix="/transcription",
    tags=["transcription"]
)

log = get_logger("transcription")

# ============================================================
# PATHS & CONFIG
# ============================================================

BASE_DIR = Path(__file__).parent.parent
TMP_DIR = BASE_DIR / "tmp"
TMP_DIR.mkdir(exist_ok=True)

MAX_UPLOAD_SIZE = 100 * 1024 * 1024  # 100 MB


# ============================================================
# MODELS
# ============================================================

class TranslateRequest(BaseModel):
    languages: List[str]
    method: str = "strict"  # "classic" (ancien) ou "strict" (v2 littéral)
    max_words: int | None = None
    max_chars: int | None = None


class SRTDirectTranslateRequest(BaseModel):
    srt: str
    languages: List[str]
    method: str = "strict"  # "classic" (ancien) ou "strict" (v2 littéral)
    max_words: int | None = None
    max_chars: int | None = None


# ============================================================
# ENDPOINTS
# ============================================================

@router.post("/upload")
async def upload_audio(file: UploadFile = File(...)):
    """
    Upload initial (audio ou vidéo).
    Stockage temporaire local + création job.
    """
    content = await file.read()

    if len(content) > MAX_UPLOAD_SIZE:
        return JSONResponse(
            {"error": "File too large (max 100MB)"},
            status_code=413
        )

    job = create_job(file.filename)
    job_id = job["id"]

    tmp_src = TMP_DIR / f"{job_id}.mp4"
    tmp_src.write_bytes(content)

    log.info(f"📥 Upload reçu pour job {job_id}")

    return {
        "job_id": job_id,
        "status": "uploaded"
    }


@router.get("/audio/{job_id}")
def serve_audio(job_id: str):
    """
    Sert l'audio WAV pour le lecteur frontend
    """
    audio_path = TMP_DIR / f"{job_id}.wav"

    if not audio_path.exists():
        return JSONResponse({"error": "audio not found"}, status_code=404)

    return FileResponse(audio_path, media_type="audio/wav")


@router.get("/audio_info/{job_id}")
def get_audio_info(job_id: str):
    """
    Retourne infos audio : durée, tokens, coût estimé
    """
    tmp_audio = TMP_DIR / f"{job_id}.wav"
    tmp_src = TMP_DIR / f"{job_id}.mp4"

    if not tmp_audio.exists() and tmp_src.exists():
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(tmp_src),
             "-vn", "-ac", "1", "-ar", "16000", str(tmp_audio)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )

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


@router.post("/generate_srt/{job_id}")
def generate_srt(
    job_id: str,
    context: str = Query("", description="Contexte pour la transcription"),
    start_time: float = Query(None, description="Début en secondes"),
    end_time: float = Query(None, description="Fin en secondes"),
    max_words: int = Query(None),
    max_chars: int = Query(None),
    engine: str = Query(
        "whisper_gemini",
        description="Moteur: 'whisper_gemini' ou 'scribe_v2'",
    ),
    keyterms: str = Query(
        None,
        description="Termes clés séparés par virgule (Scribe v2 uniquement)",
    ),
    dry_run: bool = Query(
        False,
        description="Si vrai, ne met pas à jour Supabase et renvoie le SRT brut (tests uniquement)",
    ),
):
    """
    Génère le SRT à partir de l'audio.
    
    Engines disponibles:
    - whisper_gemini: Pipeline classique Whisper + Gemini (défaut)
    - scribe_v2: ElevenLabs Scribe v2 avec timestamps mot-par-mot
    """
    job = get_job(job_id)
    if not job:
        log.error(f"❌ Job not found {job_id}")
        return JSONResponse({"error": "job not found"}, status_code=404)

    if start_time is not None and (math.isnan(start_time) or start_time < 0):
        start_time = None
    if end_time is not None and (math.isnan(end_time) or end_time < 0):
        end_time = None

    tmp_audio = TMP_DIR / f"{job_id}.wav"
    tmp_srt = TMP_DIR / f"{job_id}.srt"

    try:
        log.info(f"🔁 STT processing for {job_id} (engine={engine})")
        
        # Convertir en WAV si nécessaire
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(TMP_DIR / f"{job_id}.mp4"),
             "-vn", "-ac", "1", "-ar", "16000", str(tmp_audio)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        
        # Router vers le bon moteur
        if engine == "scribe_v2":
            # Parser keyterms
            keyterms_list = None
            if keyterms:
                keyterms_list = [k.strip() for k in keyterms.split(",") if k.strip()]
            
            # Utiliser Scribe v2
            stats = process_scribe_v2(
                audio_path=tmp_audio,
                output_path=tmp_srt,
                max_words=max_words,
                max_chars=max_chars,
                keyterms=keyterms_list,
                start_time=start_time,
                end_time=end_time
            )
            log.info(f"📊 Scribe v2 stats: {stats}")
        else:
            # Pipeline classique Whisper + Gemini
            process_stt(
                tmp_audio,
                tmp_srt,
                context=context,
                start_time=start_time,
                end_time=end_time,
                job_id=None if dry_run else job_id,
                max_words=max_words,
                max_chars=max_chars
            )

        if dry_run:
            srt_content = tmp_srt.read_text(encoding="utf-8")
            log.info(f"✅ SRT (dry-run) ready for {job_id}")
            return {
                "job_id": job_id,
                "dry_run": True,
                "engine": engine,
                "srt": srt_content
            }
        
        dest = f"{job_id}/subtitles.srt"
        srt_url = upload_file(str(tmp_srt), dest)
        
        update_job(job_id, srt_url=srt_url, status="srt_ready")
        
        log.info(f"✅ SRT ready for {job_id} (engine={engine})")
        
        return {
            "job_id": job_id,
            "engine": engine,
            "srt_url": srt_url
        }
        
    except Exception as e:
        log.error(f"🔥 SRT generation failed: {e}")
        if not dry_run:
            update_job(job_id, status="error", error=str(e))
        return JSONResponse({"error": str(e)}, status_code=500)

    finally:
        tmp_srt.unlink(missing_ok=True)


@router.get("/job/{job_id}")
def get_job_status(job_id: str):
    job = get_job(job_id)
    if not job:
        return JSONResponse({"error": "job not found"}, status_code=404)
    return job


@router.post("/translate/{job_id}")
def translate_srt_endpoint(job_id: str, request: TranslateRequest):
    """
    Traduit le SRT en plusieurs langues.
    
    Methods:
    - classic: Ancien traducteur (peut réarranger le contenu)
    - strict: Nouveau traducteur v2 (traduction littérale, même structure)
    """
    job = get_job(job_id)
    if not job or not job.get("srt_url"):
        return JSONResponse({"error": "SRT not ready"}, status_code=404)

    try:
        original_srt = requests.get(job["srt_url"]).text
        translations = {}

        for lang in request.languages:
            if lang not in SUPPORTED_LANGUAGES:
                continue

            log.info(f"🌍 Translating {job_id} to {lang} (method={request.method})")

            if request.method == "strict":
                translated = translate_srt_v2(
                    srt_content=original_srt,
                    target_lang=lang,
                    mode=TranslationMode.BATCH_STRICT,
                    max_words=request.max_words,
                    max_chars=request.max_chars,
                )
            else:
                translated = translate_srt_segments(
                    original_srt,
                    lang,
                    job_id,
                )

            tmp_path = TMP_DIR / f"{job_id}_{lang}.srt"
            tmp_path.write_text(translated, encoding="utf-8")

            dest = f"{job_id}/subtitles_{lang}.srt"
            url = upload_file(str(tmp_path), dest)
            translations[lang] = url

            tmp_path.unlink()

        update_job(job_id, translations=json.dumps(translations))

        return {
            "job_id": job_id,
            "translations": translations
        }

    except Exception as e:
        log.error(f"Translation failed: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/translate_srt_content")
def translate_srt_content(request: SRTDirectTranslateRequest):
    """
    Traduit un contenu SRT brut sans job ni stockage Supabase.
    Retourne un dictionnaire {lang: srt_traduit}.
    """
    try:
        translations = {}

        for lang in request.languages:
            if lang not in SUPPORTED_LANGUAGES:
                continue

            log.info(f"🌍 Direct SRT translation to {lang} (method={request.method})")

            if request.method == "strict":
                translated = translate_srt_v2(
                    srt_content=request.srt,
                    target_lang=lang,
                    mode=TranslationMode.BATCH_STRICT,
                    max_words=request.max_words,
                    max_chars=request.max_chars,
                )
            else:
                translated = translate_srt_segments(
                    request.srt,
                    lang,
                    job_id=None,
                )

            translations[lang] = translated

        return {
            "method": request.method,
            "translations": translations
        }

    except Exception as e:
        log.error(f"Direct SRT translation failed: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/cleanup_proxy")
def cleanup_proxy():
    """
    Nettoyage Supabase Storage
    """
    res = supabase.rpc("cleanup_old_objects").execute()
    return {"status": "ok", "detail": res.data}
