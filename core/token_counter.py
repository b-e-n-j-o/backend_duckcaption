from pathlib import Path
import subprocess

PRICING = {
    "whisper_per_min": 0.006,
    "gemini_audio_input_per_1m": 1.00,
    "gemini_text_output_per_1m": 2.50,
}

def get_audio_duration(path: Path) -> float:
    cmd = ["ffprobe", "-v", "error", "-show_entries", 
           "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(path)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return float(result.stdout.strip())

def estimate_tokens(audio_path: Path, start_time: float = 0, end_time: float = None) -> dict:
    duration = get_audio_duration(audio_path)
    
    if end_time:
        duration = min(end_time - start_time, duration)
    elif start_time:
        duration = duration - start_time
    
    duration_min = duration / 60
    whisper_cost = duration_min * PRICING["whisper_per_min"]
    gemini_tokens = int(duration * 32)
    
    return {
        "duration_sec": duration,
        "duration_min": round(duration_min, 2),
        "whisper_cost_usd": round(whisper_cost, 4),
        "gemini_tokens": gemini_tokens,
        "total_estimated_cost": round(whisper_cost, 4)  # Estimation seulement
    }

def calculate_costs(whisper_min: float, gemini_input_tokens: int, gemini_output_tokens: int) -> dict:
    """Calcule les coûts précis basés sur les tokens réels"""
    whisper_cost = whisper_min * PRICING["whisper_per_min"]
    gemini_input_cost = (gemini_input_tokens / 1_000_000) * PRICING["gemini_audio_input_per_1m"]
    gemini_output_cost = (gemini_output_tokens / 1_000_000) * PRICING["gemini_text_output_per_1m"]
    
    return {
        "whisper": round(whisper_cost, 6),
        "gemini_input": round(gemini_input_cost, 6),
        "gemini_output": round(gemini_output_cost, 6),
        "total": round(whisper_cost + gemini_input_cost + gemini_output_cost, 6)
    }

def add_cost_to_job(job_id: str, new_cost: float):
    """Ajoute un coût au job existant"""
    from core.jobs import get_job, update_job
    job = get_job(job_id)
    current = job.get("cost_usd", 0) or 0
    update_job(job_id, cost_usd=round(current + new_cost, 6))

def log_tokens(job_id: str, whisper_min: float = 0, gemini_tokens: int = 0, translation_tokens: int = 0):
    """Enregistre les tokens utilisés dans la DB (déprécié, utiliser calculate_costs + add_cost_to_job)"""
    from core.jobs import update_job, get_job
    
    job = get_job(job_id)
    current_whisper = job.get("tokens_whisper", 0) or 0
    current_gemini = job.get("tokens_gemini", 0) or 0
    current_translation = job.get("tokens_translation", 0) or 0
    
    new_whisper = current_whisper + int(whisper_min * 60)
    new_gemini = current_gemini + gemini_tokens
    new_translation = current_translation + translation_tokens
    
    update_job(job_id, 
        tokens_whisper=new_whisper,
        tokens_gemini=new_gemini, 
        tokens_translation=new_translation
    )

