from pathlib import Path
import subprocess
import json

PRICING = {
    "whisper_per_min": 0.006,
    "gemini_audio_input_per_1m": 1.00,
    "gemini_text_output_per_1m": 2.50,
}

# Politique de calcul: prendre le tarif le plus haut pour chaque run.
# Starter (Scribe v1/v2):
# - additional hour (max): $0.40 / h
# - keyterm prompting add-on: $0.080 / h
ELEVENLABS_SCRIBE_PER_HOUR_USD = 0.40
ELEVENLABS_KEYTERM_ADDON_PER_HOUR_USD = 0.080

# Tarifs text in/out par modèle Gemini (USD / 1M tokens).
# Valeurs en dur selon la grille tarifaire publique.
MODEL_TEXT_PRICING_PER_1M = {
    "gemini-3.1-flash-lite": {
        # Input texte/image/video : $0.25 / 1M tokens
        "input": 0.25,
        # Output (thinking tokens inclus) : $1.50 / 1M tokens
        "output": 1.50,
    }
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


def calculate_model_text_costs(model_id: str, input_tokens: int, output_tokens: int) -> dict:
    """
    Calcule le coût text input/output pour un modèle Gemini donné.

    Si le modèle n'a pas de tarif dédié configuré, fallback sur PRICING historique.
    """
    model_pricing = MODEL_TEXT_PRICING_PER_1M.get(model_id, {})
    input_rate = model_pricing.get("input", PRICING["gemini_audio_input_per_1m"])
    output_rate = model_pricing.get("output", PRICING["gemini_text_output_per_1m"])

    input_cost = (input_tokens / 1_000_000) * input_rate
    output_cost = (output_tokens / 1_000_000) * output_rate

    return {
        "model": model_id,
        "input_tokens": int(input_tokens),
        "output_tokens": int(output_tokens),
        "input_rate_per_1m": float(input_rate),
        "output_rate_per_1m": float(output_rate),
        "input_cost": input_cost,
        "output_cost": output_cost,
        "total": input_cost + output_cost,
    }


def calculate_elevenlabs_transcription_cost(
    duration_sec: float,
    keyterms_enabled: bool = False,
) -> dict:
    """Calcule le coût de transcription ElevenLabs Scribe v2 (tarif max)."""
    duration_min = max(float(duration_sec), 0.0) / 60.0
    duration_hour = duration_min / 60.0
    base_cost = duration_hour * ELEVENLABS_SCRIBE_PER_HOUR_USD
    keyterm_cost = duration_hour * ELEVENLABS_KEYTERM_ADDON_PER_HOUR_USD if keyterms_enabled else 0.0
    total = base_cost + keyterm_cost
    return {
        "duration_sec": max(float(duration_sec), 0.0),
        "duration_min": duration_min,
        "base_rate_per_hour_usd": ELEVENLABS_SCRIBE_PER_HOUR_USD,
        "keyterm_rate_per_hour_usd": ELEVENLABS_KEYTERM_ADDON_PER_HOUR_USD if keyterms_enabled else 0.0,
        "base_cost": base_cost,
        "keyterm_cost": keyterm_cost,
        "keyterms_enabled": bool(keyterms_enabled),
        "total": total,
    }


def add_cost_component_to_job(job_id: str, component: str, new_cost: float):
    """
    Ajoute un coût au total job + composant (si champs disponibles).

    components:
    - transcription_elevenlabs
    - cleaning_gemini
    - translation_gemini
    """
    from core.jobs import get_job, update_job
    job = get_job(job_id)
    amount = float(new_cost or 0.0)

    payload = {}
    current_total = float(job.get("cost_usd", 0) or 0.0)
    payload["cost_usd"] = round(current_total + amount, 12)

    component_to_column = {
        "transcription_elevenlabs": "cost_transcription_usd",
        "cleaning_gemini": "cost_cleaning_usd",
        "translation_gemini": "cost_translation_usd",
    }
    maybe_col = component_to_column.get(component)
    if maybe_col and maybe_col in job:
        current_component = float(job.get(maybe_col, 0) or 0.0)
        payload[maybe_col] = round(current_component + amount, 12)

    if "cost_breakdown" in job:
        raw = job.get("cost_breakdown")
        if isinstance(raw, dict):
            breakdown = raw
        elif isinstance(raw, str) and raw.strip():
            try:
                breakdown = json.loads(raw)
            except Exception:
                breakdown = {}
        else:
            breakdown = {}
        current_component = float(breakdown.get(component, 0) or 0.0)
        breakdown[component] = round(current_component + amount, 12)
        payload["cost_breakdown"] = json.dumps(breakdown)

    update_job(job_id, **payload)


def add_cost_to_job(job_id: str, new_cost: float):
    """Compat historique: ajoute un coût au total."""
    add_cost_component_to_job(job_id, "misc", new_cost)

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

