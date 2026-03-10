from dotenv import load_dotenv
load_dotenv()  # ← EN PREMIER

import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import math
import subprocess
from pathlib import Path
from typing import List, Optional

from openai import OpenAI
import google.generativeai as genai
import os

OPENAI_KEY = os.getenv("OPENAI_API_KEY")
GEMINI_KEY = os.getenv("GEMINI_API_KEY")

client_openai = OpenAI(api_key=OPENAI_KEY)
genai.configure(api_key=GEMINI_KEY)


def whisper_segments(audio: Path) -> List[dict]:
    with open(audio, "rb") as f:
        resp = client_openai.audio.transcriptions.create(
            model="whisper-1",
            file=f,
            response_format="verbose_json",
            timestamp_granularities=["segment"]
        )

    return [{
        "start": s.start,
        "end": s.end,
        "text": s.text
    } for s in resp.segments]


def gemini_transcript(audio: Path) -> str:
    model = genai.GenerativeModel("gemini-2.5-flash")
    uploaded = genai.upload_file(path=str(audio))

    resp = model.generate_content([
        "Transcris parfaitement l'audio sans traduire.",
        uploaded
    ])
    return resp.text.strip()


def gemini_align(whisper_segments: List[dict], transcript: str, context: Optional[str] = None):
    model = genai.GenerativeModel(
        "gemini-2.5-flash",
        generation_config={"response_mime_type": "application/json"}
    )

    # Extraire uniquement les textes (sans timestamps)
    texts_only = [seg["text"] for seg in whisper_segments]
    
    prompt = f"""
Tu corriges des textes de sous-titres générés par IA.

RÈGLES STRICTES :
1. Tu reçois EXACTEMENT {len(texts_only)} textes
2. Tu DOIS retourner EXACTEMENT {len(texts_only)} textes corrigés
3. Retourne UNIQUEMENT une liste JSON de strings (pas d'objets, pas de timestamps)
4. Corriger uniquement le texte pour :
   - Noms propres (personnes, entreprises, marques)
   - Fautes d'orthographe françaises évidentes
   - Attention à la grammaire et aux pluriels/féminins
   - Ponctuation manquante
   - Homonymes mal transcrits

Format de sortie STRICT (liste JSON de strings uniquement) :
["texte corrigé 1", "texte corrigé 2", ...]

Textes à corriger (dans l'ordre) :
{json.dumps(texts_only, ensure_ascii=False)}

Transcription de référence (contexte uniquement) :
{transcript}
"""

    resp = model.generate_content([prompt])
    
    try:
        corrected_texts = json.loads(resp.text)
        
        # Validation stricte du nombre
        if not isinstance(corrected_texts, list):
            raise ValueError(f"Expected list, got {type(corrected_texts)}")
        if len(corrected_texts) != len(whisper_segments):
            raise ValueError(f"Expected {len(whisper_segments)} texts, got {len(corrected_texts)}")
        
        # Réassigner les textes corrigés aux segments originaux avec leurs timestamps
        corrected_segments = []
        for i, original_seg in enumerate(whisper_segments):
            corrected_segments.append({
                "start": original_seg["start"],
                "end": original_seg["end"],
                "text": corrected_texts[i] if i < len(corrected_texts) else original_seg["text"]
            })
        
        return corrected_segments
        
    except Exception as e:
        print(f"⚠️ Gemini alignment failed: {e}")
        return whisper_segments  # Fallback


def to_srt(segs: List[dict]) -> str:
    def fmt(t):
        # Vérifier que t n'est pas NaN ou infini
        if math.isnan(t) or math.isinf(t):
            t = 0.0
        h = int(t // 3600)
        m = int((t % 3600) // 60)
        s = int(t % 60)
        ms = int((t - int(t)) * 1000)
        return f"{h:02}:{m:02}:{s:02},{ms:03}"

    out = []
    for i, seg in enumerate(segs, 1):
        out.append(f"{i}\n{fmt(seg['start'])} --> {fmt(seg['end'])}\n{seg['text'].strip()}\n")
    return "\n".join(out)


async def generate_srt(audio_path: Path, context: Optional[str] = None, 
                       start_time: float = None, end_time: float = None):
    """Pipeline avec support timestamp range - Retourne (srt, tokens_dict)"""
    
    # Valider et nettoyer les paramètres de temps
    if start_time is not None and (math.isnan(start_time) or start_time < 0):
        start_time = None
    if end_time is not None and (math.isnan(end_time) or end_time < 0):
        end_time = None
    
    # Trim audio si range spécifié
    working_audio = audio_path
    if start_time is not None or end_time is not None:
        working_audio = audio_path.parent / f"{audio_path.stem}_trimmed.wav"
        trim_cmd = ["ffmpeg", "-y", "-i", str(audio_path)]
        if start_time:
            trim_cmd.extend(["-ss", str(start_time)])
        if end_time:
            trim_cmd.extend(["-to", str(end_time)])
        trim_cmd.extend(["-ar", "16000", "-ac", "1", str(working_audio)])
        subprocess.run(trim_cmd, capture_output=True)
    
    # Upload audio pour Gemini (avant traitement pour compter tokens)
    model = genai.GenerativeModel("gemini-2.5-flash")
    uploaded = genai.upload_file(path=str(working_audio))
    
    # Compter tokens input (audio)
    try:
        input_tokens = model.count_tokens([uploaded]).total_tokens
    except:
        # Fallback si count_tokens ne fonctionne pas
        from core.token_counter import get_audio_duration
        duration = get_audio_duration(working_audio)
        input_tokens = int(duration * 32)  # Estimation
    
    loop = asyncio.get_event_loop()
    
    with ThreadPoolExecutor(max_workers=2) as executor:
        print("📍 Whisper + Gemini en parallèle...")
        whisper_task = loop.run_in_executor(executor, whisper_segments, working_audio)
        
        # Utiliser l'upload existant pour la transcription
        def gemini_transcript_with_upload(uploaded_file):
            model_local = genai.GenerativeModel("gemini-2.5-flash")
            resp = model_local.generate_content([
                "Transcris parfaitement l'audio sans traduire.",
                uploaded_file
            ])
            return resp.text.strip()
        
        gemini_task = loop.run_in_executor(executor, gemini_transcript_with_upload, uploaded)
        
        ws, gfull = await asyncio.gather(whisper_task, gemini_task)
    
    # Ajuster timestamps si start_time
    if start_time and not math.isnan(start_time):
        for seg in ws:
            # Vérifier que les timestamps ne sont pas NaN avant d'ajouter
            if not math.isnan(seg.get("start", 0)):
                seg["start"] += start_time
            if not math.isnan(seg.get("end", 0)):
                seg["end"] += start_time
    
    print("📍 Gemini alignment...")
    try:
        aligned = gemini_align(ws, gfull, context)
    except Exception as e:
        print(f"⚠️ Gemini alignment failed ({e}) — using Whisper output")
        aligned = ws
    
    # Estimation tokens output (alignement)
    output_tokens = len(aligned) * 10  # Estimation moyenne par segment
    
    # Cleanup trimmed
    if working_audio != audio_path:
        working_audio.unlink(missing_ok=True)
    
    tokens_info = {
        "gemini_input": input_tokens,
        "gemini_output": output_tokens
    }
    
    return to_srt(aligned), tokens_info
