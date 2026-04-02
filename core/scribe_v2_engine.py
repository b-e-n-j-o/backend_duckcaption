"""
Scribe v2 Engine - Module de transcription ElevenLabs

Ce module fournit une alternative à Whisper+Gemini avec:
- Timestamps précis au niveau des mots
- Pas d'interpolation nécessaire pour le découpage
- Keyterms pour améliorer la reconnaissance
"""

import os
import json
import time
import re
import requests
from pathlib import Path
from typing import List, Optional
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()

ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")


def remove_repetitions(text: str) -> str:
    """
    Supprime les répétitions/hésitations.
    'le, le, le plus' → 'le plus'
    'je je veux' → 'je veux'
    """
    # Pattern: mot répété 2+ fois avec virgules/espaces entre
    # Gère: "le, le, le" / "je je je" / "euh, euh"
    pattern = r"\b(\w+)(?:[,\s]+\1)+\b"
    cleaned = re.sub(pattern, r"\1", text, flags=re.IGNORECASE)

    # Nettoyer les espaces multiples
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    # Nettoyer les virgules orphelines ", ," ou ", , ,"
    cleaned = re.sub(r"(?:,\s*)+,", ",", cleaned)
    cleaned = re.sub(r"\s+,", ",", cleaned)

    return cleaned


def split_to_two_lines(text: str, max_chars_per_line: int = 42) -> str:
    """
    Coupe le texte en 2 lignes équilibrées si trop long.
    Standard sous-titrage: ~42 caractères par ligne max.
    """
    text = text.strip()

    # Si assez court, pas besoin de couper
    if len(text) <= max_chars_per_line:
        return text

    words = text.split()
    if len(words) < 2:
        return text

    # Trouver le meilleur point de coupure (proche du milieu)
    total_len = len(text)
    target = total_len // 2

    current_len = 0
    best_split_idx = 0
    best_diff = total_len

    for i, word in enumerate(words[:-1]):  # Pas sur le dernier mot
        current_len += len(word) + 1  # +1 pour l'espace
        diff = abs(current_len - target)
        if diff < best_diff:
            best_diff = diff
            best_split_idx = i + 1

    line1 = " ".join(words[:best_split_idx])
    line2 = " ".join(words[best_split_idx:])

    return f"{line1}\n{line2}"


# ============================================================
# DATA STRUCTURES
# ============================================================

@dataclass
class Word:
    """Un mot avec son timestamp."""
    text: str
    start: float
    end: float
    type: str = "word"  # word, spacing, audio_event, punctuation


@dataclass
class Segment:
    """Un segment SRT avec plusieurs mots."""
    words: List[Word]
    
    @property
    def start(self) -> float:
        return self.words[0].start if self.words else 0
    
    @property
    def end(self) -> float:
        return self.words[-1].end if self.words else 0
    
    @property
    def text(self) -> str:
        result = []
        for word in self.words:
            if word.type == "word":
                result.append(word.text)
            elif word.type == "punctuation":
                if result:
                    result[-1] += word.text
                else:
                    result.append(word.text)
            # audio_event ignorés (ex: [laughter], [music])

        raw_text = " ".join(result)

        # Supprimer les hésitations/répétitions
        cleaned = remove_repetitions(raw_text)

        return cleaned
    
    @property
    def word_count(self) -> int:
        return len([w for w in self.words if w.type == "word"])
    
    @property
    def char_count(self) -> int:
        return len(self.text)


# ============================================================
# SCRIBE V2 API
# ============================================================

def transcribe_audio(
    audio_path: Path,
    keyterms: Optional[List[str]] = None,
    language_code: Optional[str] = None,
    timeout: int = 300
) -> dict:
    """
    Transcrit un fichier audio avec ElevenLabs Scribe v2.
    
    Returns:
        Dict avec: language_code, text, words[]
    """
    if not ELEVENLABS_API_KEY:
        raise ValueError("ELEVENLABS_API_KEY non définie")
    
    url = "https://api.elevenlabs.io/v1/speech-to-text"
    headers = {"xi-api-key": ELEVENLABS_API_KEY}
    
    # Détecter le mime type
    suffix = audio_path.suffix.lower()
    mime_types = {
        ".mp3": "audio/mpeg",
        ".wav": "audio/wav",
        ".m4a": "audio/mp4",
        ".mp4": "video/mp4",
        ".webm": "audio/webm",
        ".ogg": "audio/ogg",
    }
    mime_type = mime_types.get(suffix, "audio/mpeg")
    
    with open(audio_path, "rb") as f:
        files = {"file": (audio_path.name, f, mime_type)}
        data = {
            "model_id": "scribe_v2",
            "timestamps_granularity": "word",
            "tag_audio_events": "true"
        }
        
        if keyterms:
            valid_keyterms = [k.strip()[:50] for k in keyterms[:100] if k.strip()]
            if valid_keyterms:
                data["keyterms"] = json.dumps(valid_keyterms)
        
        if language_code:
            data["language_code"] = language_code
        
        response = requests.post(
            url,
            headers=headers,
            files=files,
            data=data,
            timeout=(60, timeout)
        )
        
        if response.status_code == 200:
            return response.json()
        else:
            error = response.json() if response.headers.get("content-type", "").startswith("application/json") else response.text
            raise Exception(f"Scribe v2 API error ({response.status_code}): {error}")


# ============================================================
# SRT BUILDER
# ============================================================

def build_segments(
    words_data: List[dict],
    max_words: Optional[int] = None,
    max_chars: Optional[int] = None,
    max_chars_per_line: int = 42,
    max_segment_duration: float = 7.0
) -> List[Segment]:
    """
    Construit des segments SRT à partir des mots Scribe v2.
    
    Timestamps EXACTS - pas d'interpolation !
    """
    words = [
        Word(
            text=w["text"],
            start=w["start"],
            end=w["end"],
            type=w.get("type", "word")
        )
        for w in words_data
    ]
    
    if not words:
        return []
    
    segments = []
    current_words = []
    
    def should_break(word: Word) -> bool:
        if not current_words:
            return False

        word_count = len([w for w in current_words if w.type == "word"])
        duration = current_words[-1].end - current_words[0].start

        # Couper après ponctuation finale
        last_text = current_words[-1].text.strip()
        if last_text.endswith((".", "!", "?")):
            return True

        if max_words and word_count >= max_words:
            return True

        if max_chars:
            temp_seg = Segment(words=current_words)
            new_len = len(temp_seg.text) + len(word.text) + 1
            if new_len > max_chars:
                return True

        if duration >= max_segment_duration:
            return True

        return False
    
    for word in words:
        # Ignorer spacing et audio_event (ex: [laughter], [music])
        if word.type in ("spacing", "audio_event"):
            continue
        
        if should_break(word):
            if current_words:
                segments.append(Segment(words=current_words))
            current_words = [word]
        else:
            current_words.append(word)
    
    if current_words:
        segments.append(Segment(words=current_words))
    
    return segments


def segments_to_srt(segments: List[Segment], max_chars_per_line: int = 42) -> str:
    """Convertit les segments en format SRT."""
    def fmt_time(seconds: float) -> str:
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        ms = int((seconds - int(seconds)) * 1000)
        return f"{h:02}:{m:02}:{s:02},{ms:03}"
    
    lines = []
    for i, seg in enumerate(segments, 1):
        text = seg.text.strip()

        # Appliquer le split 2 lignes si nécessaire
        text = split_to_two_lines(text, max_chars_per_line)

        lines.append(str(i))
        lines.append(f"{fmt_time(seg.start)} --> {fmt_time(seg.end)}")
        lines.append(text)
        lines.append("")

    return "\n".join(lines)


# ============================================================
# MAIN ENTRY POINT
# ============================================================

def process_scribe_v2(
    audio_path: Path,
    output_path: Path,
    max_words: Optional[int] = None,
    max_chars: Optional[int] = None,
    max_chars_per_line: int = 42,
    keyterms: Optional[List[str]] = None,
    language_code: Optional[str] = None,
    start_time: Optional[float] = None,
    end_time: Optional[float] = None
) -> dict:
    """
    Pipeline complet Scribe v2: audio → SRT
    
    Args:
        audio_path: Fichier audio source
        output_path: Fichier SRT de sortie
        max_words: Limite de mots par segment
        max_chars: Limite de caractères par segment
        keyterms: Termes à privilégier
        language_code: Code langue ISO
        start_time: Début en secondes (pour trim)
        end_time: Fin en secondes (pour trim)
    
    Returns:
        Dict avec stats: segments_count, duration, words_count
    """
    import subprocess
    
    working_audio = audio_path
    
    # Trim audio si nécessaire
    if start_time is not None or end_time is not None:
        working_audio = audio_path.parent / f"{audio_path.stem}_trimmed.wav"
        cmd = ["ffmpeg", "-y", "-i", str(audio_path)]
        if start_time:
            cmd.extend(["-ss", str(start_time)])
        if end_time:
            cmd.extend(["-to", str(end_time)])
        cmd.extend(["-ar", "16000", "-ac", "1", str(working_audio)])
        subprocess.run(cmd, capture_output=True)
    
    try:
        # Transcrire
        result = transcribe_audio(
            working_audio,
            keyterms=keyterms,
            language_code=language_code
        )
        
        words = result.get("words", [])
        
        # Ajuster timestamps si trimmed
        if start_time and start_time > 0:
            for w in words:
                w["start"] += start_time
                w["end"] += start_time
        
        # Construire segments
        segments = build_segments(
            words,
            max_words=max_words,
            max_chars=max_chars,
            max_chars_per_line=max_chars_per_line,
        )
        
        # Générer SRT avec split 2 lignes
        srt_content = segments_to_srt(segments, max_chars_per_line)
        output_path.write_text(srt_content, encoding="utf-8")
        
        detected_language = result.get("language_code", "unknown")

        return {
            "segments_count": len(segments),
            "words_count": len([w for w in words if w.get("type") == "word"]),
            "duration": words[-1]["end"] if words else 0,
            "language": detected_language,
            "engine": "scribe_v2"
        }
        
    finally:
        # Cleanup
        if working_audio != audio_path and working_audio.exists():
            working_audio.unlink(missing_ok=True)