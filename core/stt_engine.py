from pathlib import Path
from typing import Optional
import math
from core.whisper_gemini_pipeline import generate_srt
from core.audio_chunker import (
    MAX_CHUNK_SIZE, split_audio, merge_srt, get_audio_duration
)
from core.token_counter import estimate_tokens, calculate_costs, add_cost_to_job, get_audio_duration as get_duration
import asyncio


def process_stt(audio_path: Path, out_path: Path, context: Optional[str] = None,
                start_time: float = None, end_time: float = None, job_id: str = None,
                max_words: Optional[int] = None, max_chars: Optional[int] = None):
    """
    Wrapper synchrone pour la pipeline async avec support des gros fichiers
    
    Args:
        max_words: Nombre maximum de mots par segment SRT (None = pas de limite)
        max_chars: Nombre maximum de caractères par segment SRT (None = pas de limite)
    """
    
    # Valider et nettoyer les paramètres de temps
    if start_time is not None and (math.isnan(start_time) or start_time < 0):
        start_time = None
    if end_time is not None and (math.isnan(end_time) or end_time < 0):
        end_time = None
    
    # Estimation AVANT traitement
    tokens = estimate_tokens(audio_path, start_time or 0, end_time)
    print(f"💰 Estimation: {tokens['duration_min']}min, "
          f"${tokens['whisper_cost_usd']}, {tokens['gemini_tokens']} tokens Gemini")
    
    size = audio_path.stat().st_size
    
    if size > MAX_CHUNK_SIZE:
        print(f"📦 Audio trop grand ({size/1e6:.1f}MB), découpage...")
        chunks = split_audio(audio_path)
        
        srt_chunks = []
        offsets = []
        cumul = 0
        total_duration = 0
        total_gemini_input = 0
        total_gemini_output = 0
        
        for chunk in chunks:
            chunk_srt = chunk.with_suffix('.srt')
            # Ne pas passer start_time/end_time aux chunks : ils sont déjà découpés
            # Les timestamps seront ajustés par merge_srt() avec les offsets
            srt_text, chunk_tokens = asyncio.run(generate_srt(chunk, context, None, None, max_words, max_chars))
            chunk_srt.write_text(srt_text, encoding="utf-8")
            srt_chunks.append(chunk_srt)
            offsets.append(cumul)
            chunk_duration = get_audio_duration(chunk)
            total_duration += chunk_duration
            total_gemini_input += chunk_tokens["gemini_input"]
            total_gemini_output += chunk_tokens["gemini_output"]
            cumul += chunk_duration
        
        merged = merge_srt(srt_chunks, offsets)
        out_path.write_text(merged, encoding="utf-8")
        
        # Calculer coûts précis
        if job_id:
            duration_min = total_duration / 60
            costs = calculate_costs(duration_min, total_gemini_input, total_gemini_output)
            add_cost_to_job(job_id, costs["total"])
            print(f"💰 Coût réel: ${costs['total']} (Whisper: ${costs['whisper']}, Gemini: ${costs['gemini_input'] + costs['gemini_output']})")
        
        # Cleanup
        for chunk in chunks:
            chunk.unlink(missing_ok=True)
        for srt_chunk in srt_chunks:
            srt_chunk.unlink(missing_ok=True)
    else:
        srt_text, tokens_info = asyncio.run(generate_srt(audio_path, context, start_time, end_time, max_words, max_chars))
        out_path.write_text(srt_text, encoding="utf-8")
        
        # Calculer coûts précis
        if job_id:
            duration_min = get_duration(audio_path) / 60
            if start_time or end_time:
                duration = get_duration(audio_path)
                if end_time:
                    duration = min(end_time - (start_time or 0), duration)
                elif start_time:
                    duration = duration - start_time
                duration_min = duration / 60
            
            costs = calculate_costs(duration_min, tokens_info["gemini_input"], tokens_info["gemini_output"])
            add_cost_to_job(job_id, costs["total"])
            print(f"💰 Coût réel: ${costs['total']} (Whisper: ${costs['whisper']}, Gemini: ${costs['gemini_input'] + costs['gemini_output']})")
    
    return out_path
