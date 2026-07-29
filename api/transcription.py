from fastapi import APIRouter, File, UploadFile, Query
from fastapi.responses import JSONResponse, FileResponse
from pydantic import BaseModel

from pathlib import Path
from typing import List
import json
import requests
import subprocess
import math
import os
import re
import unicodedata

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


def slugify_filename(name: str) -> str:
    """
    Convertit un nom de fichier en forme ASCII safe pour Supabase Storage.
    """
    normalized = unicodedata.normalize("NFKD", name)
    ascii_name = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^\w\-.]", "_", ascii_name)
    return slug.strip("._") or "subtitles"


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
    filename: str | None = "uploaded.srt"  # nom du fichier source (job dédié traduction)
    persist: bool = True  # crée un job dédié + Storage (indépendant de la transcription)


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
    max_chars_per_line: int = Query(
        42,
        description="Nombre max de caractères par ligne de sous-titres (Scribe v2)",
    ),
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
        detected_lang = None
        srt_filename = "subtitles.srt"

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
                max_chars_per_line=max_chars_per_line,
                keyterms=keyterms_list,
                start_time=start_time,
                end_time=end_time,
                job_id=job_id,
            )
            log.info(f"📊 Scribe v2 stats: {stats}")

            # Nom du fichier: audio_original_langue.srt
            original_filename = job.get("filename", "subtitles")
            base_name = slugify_filename(os.path.splitext(original_filename)[0])
            detected_lang = stats.get("language", "unknown")
            srt_filename = f"{base_name}_{detected_lang}.srt"
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
                "language": detected_lang,
                "filename": srt_filename,
                "srt": srt_content,
            }
        
        dest = f"{job_id}/{srt_filename}"
        srt_url = upload_file(str(tmp_srt), dest)
        
        update_job(
            job_id,
            srt_url=srt_url,
            status="srt_ready",
            language=detected_lang,
            engine=engine,
        )
        
        log.info(f"✅ SRT ready for {job_id} (engine={engine})")
        
        return {
            "job_id": job_id,
            "engine": engine,
            "language": detected_lang,
            "filename": srt_filename,
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
    Traduit le SRT d'un job source (transcription) vers une ou plusieurs langues.

    Crée TOUJOURS un nouveau job dédié à la traduction (engine=translation_only),
    lié au job source via parent_job_id. Le job de transcription n'est pas modifié.
    """
    source_job = get_job(job_id)
    if not source_job or not source_job.get("srt_url"):
        return JSONResponse({"error": "SRT not ready"}, status_code=404)

    translation_job_id = None
    try:
        original_srt = requests.get(source_job["srt_url"]).text
        translations = {}

        source_name = source_job.get("filename") or "subtitles"
        base_name = slugify_filename(os.path.splitext(source_name)[0])
        translation_job = create_job(f"{base_name}_translation.srt")
        translation_job_id = translation_job["id"]

        # Copie du SRT source sur le job traduction + métadonnées
        tmp_source = TMP_DIR / f"{translation_job_id}_source.srt"
        tmp_source.write_text(original_srt, encoding="utf-8")
        source_url = upload_file(
            str(tmp_source),
            f"{translation_job_id}/{base_name}_source.srt",
        )
        tmp_source.unlink(missing_ok=True)

        translation_meta = {
            "srt_url": source_url,
            "status": "translating",
            "engine": "translation_only",
            "language": source_job.get("language"),
            "parent_job_id": job_id,
        }
        try:
            update_job(translation_job_id, **translation_meta)
        except Exception:
            # Compat si parent_job_id pas encore migré en base
            translation_meta.pop("parent_job_id", None)
            update_job(translation_job_id, **translation_meta)
            log.warning("⚠️ parent_job_id non persisté (colonne absente?)")

        log.info(
            f"🆕 Job traduction {translation_job_id} créé "
            f"(source transcription={job_id})"
        )

        for lang in request.languages:
            if lang not in SUPPORTED_LANGUAGES:
                continue

            log.info(
                f"🌍 Translating source={job_id} → job={translation_job_id} "
                f"lang={lang} (method={request.method})"
            )

            if request.method == "strict":
                translated = translate_srt_v2(
                    srt_content=original_srt,
                    target_lang=lang,
                    mode=TranslationMode.BATCH_STRICT,
                    max_words=request.max_words,
                    max_chars=request.max_chars,
                )
                try:
                    from core.token_counter import (
                        calculate_model_text_costs,
                        add_cost_component_to_job,
                    )
                    input_tokens = len(original_srt.split()) * 1.3
                    output_tokens = len(translated.split()) * 1.3
                    costs = calculate_model_text_costs(
                        "gemini-3.1-flash-lite",
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                    )
                    add_cost_component_to_job(
                        translation_job_id, "translation_gemini", costs["total"]
                    )
                    log.info(
                        f"💰 Translation cost ({lang}, strict): ${costs['total']:.12f} "
                        f"(estimated tokens in={int(input_tokens)}, out={int(output_tokens)})"
                    )
                except Exception as cost_err:
                    log.warning(
                        f"⚠️ Translation cost tracking failed ({lang}, strict): {cost_err}"
                    )
            else:
                translated = translate_srt_segments(
                    original_srt,
                    lang,
                    translation_job_id,
                )

            tmp_path = TMP_DIR / f"{translation_job_id}_{lang}.srt"
            tmp_path.write_text(translated, encoding="utf-8")
            dest = f"{translation_job_id}/{base_name}_{lang}.srt"
            url = upload_file(str(tmp_path), dest)
            translations[lang] = url
            tmp_path.unlink(missing_ok=True)

        update_job(
            translation_job_id,
            translations=json.dumps(translations),
            status="translated",
        )

        return {
            "job_id": translation_job_id,
            "source_job_id": job_id,
            "translations": translations,
        }

    except Exception as e:
        log.error(f"Translation failed: {e}")
        if translation_job_id:
            update_job(translation_job_id, status="error", error=str(e))
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/translate_srt_content")
def translate_srt_content(request: SRTDirectTranslateRequest):
    """
    Traduit un contenu SRT brut fourni par le client (sans transcription préalable).

    Par défaut (persist=True):
    - crée un NOUVEAU job dédié (indépendant d'une transcription)
    - upload le SRT source + les SRT traduits sur Storage
    - persiste translations / cost_usd / engine sur ce job

    Retourne toujours {lang: contenu_srt} pour compatibilité frontend/plugin.
    """
    job_id = None
    try:
        translations_content = {}
        translations_urls = {}
        source_url = None

        if request.persist:
            filename = request.filename or "uploaded.srt"
            job = create_job(filename)
            job_id = job["id"]

            tmp_source = TMP_DIR / f"{job_id}_source.srt"
            tmp_source.write_text(request.srt, encoding="utf-8")
            base_name = slugify_filename(os.path.splitext(filename)[0])
            source_url = upload_file(str(tmp_source), f"{job_id}/{base_name}_source.srt")
            tmp_source.unlink(missing_ok=True)

            update_job(
                job_id,
                srt_url=source_url,
                status="translating",
                engine="translation_only",
            )
            log.info(f"🆕 Job traduction dédié créé: {job_id}")

        for lang in request.languages:
            if lang not in SUPPORTED_LANGUAGES:
                continue

            log.info(
                f"🌍 Direct SRT translation to {lang} "
                f"(method={request.method}, job={job_id or 'no-persist'})"
            )

            if request.method == "strict":
                translated = translate_srt_v2(
                    srt_content=request.srt,
                    target_lang=lang,
                    mode=TranslationMode.BATCH_STRICT,
                    max_words=request.max_words,
                    max_chars=request.max_chars,
                )
                if job_id:
                    try:
                        from core.token_counter import (
                            calculate_model_text_costs,
                            add_cost_component_to_job,
                        )
                        input_tokens = len(request.srt.split()) * 1.3
                        output_tokens = len(translated.split()) * 1.3
                        costs = calculate_model_text_costs(
                            "gemini-3.1-flash-lite",
                            input_tokens=input_tokens,
                            output_tokens=output_tokens,
                        )
                        add_cost_component_to_job(
                            job_id, "translation_gemini", costs["total"]
                        )
                    except Exception as cost_err:
                        log.warning(f"⚠️ Translation cost tracking failed: {cost_err}")
            else:
                translated = translate_srt_segments(
                    request.srt,
                    lang,
                    job_id=job_id,
                )

            translations_content[lang] = translated

            if job_id:
                tmp_path = TMP_DIR / f"{job_id}_{lang}.srt"
                tmp_path.write_text(translated, encoding="utf-8")
                base_name = slugify_filename(
                    os.path.splitext(request.filename or "uploaded")[0]
                )
                url = upload_file(str(tmp_path), f"{job_id}/{base_name}_{lang}.srt")
                translations_urls[lang] = url
                tmp_path.unlink(missing_ok=True)

        if job_id:
            update_job(
                job_id,
                translations=json.dumps(translations_urls),
                status="translated",
            )

        return {
            "method": request.method,
            "job_id": job_id,
            "srt_url": source_url,
            "translation_urls": translations_urls,
            "translations": translations_content,  # contenu brut (compat UI)
        }

    except Exception as e:
        log.error(f"Direct SRT translation failed: {e}")
        if job_id:
            update_job(job_id, status="error", error=str(e))
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/cleanup_proxy")
def cleanup_proxy():
    """
    Nettoyage Supabase Storage
    """
    res = supabase.rpc("cleanup_old_objects").execute()
    return {"status": "ok", "detail": res.data}
