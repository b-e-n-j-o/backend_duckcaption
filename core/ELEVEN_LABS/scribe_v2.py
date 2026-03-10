"""
POC: ElevenLabs Scribe v2 Speech-to-Text

Ce script teste le modèle Scribe v2 pour la transcription audio avec:
- Timestamps au niveau des mots (pas de segments comme Whisper)
- Scores de confiance (logprob) par mot
- Keyterm prompting pour améliorer la reconnaissance de termes spécifiques
- Génération SRT avec contrôle précis du nombre de mots/caractères par segment

Avantages par rapport à Whisper + Gemini:
- Timestamps exacts par mot → pas d'interpolation nécessaire
- Une seule API call au lieu de 2 (Whisper + Gemini)
- Keyterms intégrés (noms propres, marques, termes techniques)

Usage:
    python scribe_v2_poc.py <audio_file> [--max-words N] [--max-chars N] [--keyterms "term1,term2"]
    
Requires:
    pip install elevenlabs python-dotenv
    
Environment:
    ELEVENLABS_API_KEY=your_api_key
"""

import os
import sys
import json
import argparse
from pathlib import Path
from dataclasses import dataclass
from typing import List, Optional
from dotenv import load_dotenv

load_dotenv()


# ============================================================
# CONFIGURATION
# ============================================================

ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")


# ============================================================
# DATA STRUCTURES
# ============================================================

@dataclass
class Word:
    """Représente un mot transcrit avec ses métadonnées."""
    text: str
    start: float  # timestamp début en secondes
    end: float    # timestamp fin en secondes
    type: str     # "word", "spacing", "audio_event", "punctuation"
    speaker_id: Optional[str] = None
    logprob: Optional[float] = None  # score de confiance (plus proche de 0 = plus confiant)
    
    def __repr__(self):
        conf = f" (conf={self.logprob:.2f})" if self.logprob else ""
        return f"[{self.start:.2f}-{self.end:.2f}] {self.text}{conf}"


@dataclass 
class Segment:
    """Représente un segment SRT avec plusieurs mots."""
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
                # Pas d'espace avant la ponctuation
                if result:
                    result[-1] += word.text
                else:
                    result.append(word.text)
            elif word.type == "audio_event":
                result.append(word.text)  # Ex: "(laughter)"
        return " ".join(result)
    
    @property
    def word_count(self) -> int:
        return len([w for w in self.words if w.type == "word"])
    
    @property
    def char_count(self) -> int:
        return len(self.text)


# ============================================================
# SCRIBE V2 API CLIENT
# ============================================================

def transcribe_with_scribe_v2(
    audio_path: Path,
    keyterms: Optional[List[str]] = None,
    language_code: Optional[str] = None,
    diarize: bool = False,
    timeout: int = 300
) -> dict:
    """
    Transcrit un fichier audio avec ElevenLabs Scribe v2.
    
    Args:
        audio_path: Chemin vers le fichier audio
        keyterms: Liste de termes à privilégier (max 100, max 50 chars chacun)
        language_code: Code langue ISO (None = auto-detect)
        diarize: Activer la diarisation (identification des speakers)
        timeout: Timeout en secondes (défaut: 300s = 5min)
    
    Returns:
        Réponse brute de l'API
    """
    import time
    import requests
    
    if not ELEVENLABS_API_KEY:
        print("❌ ELEVENLABS_API_KEY non définie dans l'environnement")
        sys.exit(1)
    
    # Infos fichier
    file_size_kb = audio_path.stat().st_size / 1024
    print(f"📁 Taille: {file_size_kb:.1f} KB")
    print(f"📤 Envoi de {audio_path.name} à Scribe v2...")
    
    url = "https://api.elevenlabs.io/v1/speech-to-text"
    headers = {"xi-api-key": ELEVENLABS_API_KEY}
    
    start_time = time.time()
    
    with open(audio_path, "rb") as f:
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
        
        files = {"file": (audio_path.name, f, mime_type)}
        data = {
            "model_id": "scribe_v2",
            "timestamps_granularity": "word",
            "tag_audio_events": "true"
        }
        
        if keyterms:
            valid_keyterms = [k.strip()[:50] for k in keyterms[:100] if k.strip()]
            if valid_keyterms:
                # L'API attend un JSON array pour keyterms
                data["keyterms"] = json.dumps(valid_keyterms)
                print(f"🔑 Keyterms: {valid_keyterms}")
        
        if language_code:
            data["language_code"] = language_code
        
        if diarize:
            data["diarize"] = "true"
        
        print("⏳ Traitement en cours...", flush=True)
        
        try:
            response = requests.post(
                url,
                headers=headers,
                files=files,
                data=data,
                timeout=(60, timeout)  # 60s connect, timeout pour read
            )
            
            elapsed = time.time() - start_time
            
            if response.status_code == 200:
                print(f"✅ Réponse reçue en {elapsed:.1f}s")
                return response.json()
            else:
                error_detail = response.json() if response.headers.get("content-type", "").startswith("application/json") else response.text
                
                if "quota_exceeded" in str(error_detail):
                    print(f"\n❌ QUOTA INSUFFISANT")
                    print(f"   {error_detail}")
                elif response.status_code == 401:
                    print(f"\n❌ ERREUR D'AUTHENTIFICATION")
                    print(f"   Vérifiez votre ELEVENLABS_API_KEY")
                else:
                    print(f"\n❌ Erreur API ({response.status_code}): {error_detail}")
                sys.exit(1)
                
        except requests.exceptions.Timeout:
            elapsed = time.time() - start_time
            print(f"\n❌ TIMEOUT après {elapsed:.1f}s")
            print(f"   Essayez --timeout 600 pour 10 minutes")
            sys.exit(1)
            
        except Exception as e:
            elapsed = time.time() - start_time
            print(f"\n❌ Erreur après {elapsed:.1f}s: {e}")
            sys.exit(1)


# ============================================================
# WORD-LEVEL SRT BUILDER
# ============================================================

def build_segments_from_words(
    words_data: List[dict],
    max_words: Optional[int] = None,
    max_chars: Optional[int] = None,
    min_segment_duration: float = 0.5,  # Durée min d'un segment en secondes
    max_segment_duration: float = 7.0,   # Durée max d'un segment en secondes
) -> List[Segment]:
    """
    Construit des segments SRT à partir de mots individuels.
    
    AVANTAGE MAJEUR vs votre srt_splitter.py:
    Ici les timestamps sont EXACTS car chaque mot a son propre timestamp.
    Pas d'interpolation proportionnelle nécessaire !
    
    Args:
        words_data: Liste de mots depuis Scribe v2
        max_words: Nombre max de mots par segment
        max_chars: Nombre max de caractères par segment
        min_segment_duration: Durée minimum d'un segment
        max_segment_duration: Durée maximum d'un segment
    
    Returns:
        Liste de Segments avec timestamps précis
    """
    # Convertir en objets Word
    words = [
        Word(
            text=w["text"],
            start=w["start"],
            end=w["end"],
            type=w.get("type", "word"),
            speaker_id=w.get("speaker_id"),
            logprob=w.get("logprob")
        )
        for w in words_data
    ]
    
    if not words:
        return []
    
    segments = []
    current_words = []
    
    def should_break(word: Word) -> bool:
        """Détermine si on doit créer un nouveau segment."""
        if not current_words:
            return False
        
        # Compter uniquement les "word" types pour max_words
        word_count = len([w for w in current_words if w.type == "word"])
        
        # Calculer le texte actuel pour max_chars
        temp_segment = Segment(words=current_words)
        current_text = temp_segment.text
        
        # Durée actuelle
        duration = current_words[-1].end - current_words[0].start
        
        # Vérifier les limites
        if max_words and word_count >= max_words:
            return True
        
        if max_chars:
            # Simuler l'ajout du nouveau mot
            new_text_len = len(current_text) + len(word.text) + 1
            if new_text_len > max_chars:
                return True
        
        if duration >= max_segment_duration:
            return True
        
        return False
    
    for word in words:
        # Ignorer les "spacing" purs (espaces entre mots)
        if word.type == "spacing":
            continue
        
        if should_break(word):
            # Finaliser le segment actuel
            if current_words:
                segments.append(Segment(words=current_words))
            current_words = [word]
        else:
            current_words.append(word)
    
    # Dernier segment
    if current_words:
        segments.append(Segment(words=current_words))
    
    return segments


def segments_to_srt(segments: List[Segment]) -> str:
    """
    Convertit les segments en format SRT.
    
    Les timestamps sont EXACTS car ils viennent directement
    des mots individuels de Scribe v2.
    """
    def format_timestamp(seconds: float) -> str:
        """Formate un timestamp en HH:MM:SS,mmm"""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        millis = int((seconds - int(seconds)) * 1000)
        return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"
    
    lines = []
    for i, segment in enumerate(segments, 1):
        lines.append(str(i))
        lines.append(f"{format_timestamp(segment.start)} --> {format_timestamp(segment.end)}")
        lines.append(segment.text.strip())
        lines.append("")  # Ligne vide entre segments
    
    return "\n".join(lines)


# ============================================================
# ANALYSIS & DEBUG
# ============================================================

def analyze_transcription(result: dict) -> dict:
    """Analyse la qualité de la transcription."""
    words = result.get("words", [])
    
    if not words:
        return {"error": "No words in transcription"}
    
    # Statistiques
    word_types = {}
    logprobs = []
    
    for w in words:
        wtype = w.get("type", "unknown")
        word_types[wtype] = word_types.get(wtype, 0) + 1
        if w.get("logprob") is not None:
            logprobs.append(w["logprob"])
    
    # Mots avec faible confiance (logprob très négatif = moins confiant)
    low_confidence = [
        w for w in words 
        if w.get("logprob") is not None and w["logprob"] < -1.0
    ]
    
    analysis = {
        "total_words": len(words),
        "word_types": word_types,
        "language": result.get("language_code"),
        "language_confidence": result.get("language_probability"),
        "duration_seconds": words[-1]["end"] if words else 0,
    }
    
    if logprobs:
        analysis["avg_confidence"] = sum(logprobs) / len(logprobs)
        analysis["low_confidence_words"] = [
            {"text": w["text"], "logprob": w["logprob"]} 
            for w in low_confidence[:10]  # Top 10
        ]
    
    return analysis


def print_word_timeline(words: List[dict], limit: int = 20):
    """Affiche une timeline des mots pour debug."""
    print("\n📝 Timeline des mots (premiers {}):\n".format(limit))
    print(f"{'Start':>8} {'End':>8} {'Type':<12} {'Text':<20} {'Conf':>8}")
    print("-" * 60)
    
    for w in words[:limit]:
        logprob = f"{w.get('logprob', 0):.3f}" if w.get('logprob') is not None else "N/A"
        print(f"{w['start']:>8.2f} {w['end']:>8.2f} {w.get('type', 'word'):<12} {w['text']:<20} {logprob:>8}")
    
    if len(words) > limit:
        print(f"... et {len(words) - limit} autres mots")





# ============================================================
# MAIN
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="POC ElevenLabs Scribe v2 - Transcription avec timestamps mot-par-mot",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemples:
  python scribe_v2_poc.py audio.mp3
  python scribe_v2_poc.py audio.mp3 --max-words 5
  python scribe_v2_poc.py audio.mp3 --max-chars 42 --keyterms "Anthropic,Claude"
  python scribe_v2_poc.py audio.mp3 --output subtitles.srt --debug --json
        """
    )
    
    parser.add_argument("audio_file", type=Path, help="Fichier audio à transcrire")
    parser.add_argument("--max-words", type=int, default=None, help="Nombre max de mots par segment SRT")
    parser.add_argument("--max-chars", type=int, default=None, help="Nombre max de caractères par segment SRT")
    parser.add_argument("--keyterms", type=str, default=None, help="Termes à privilégier (séparés par virgule)")
    parser.add_argument("--language", type=str, default=None, help="Code langue ISO (ex: fr, en)")
    parser.add_argument("--diarize", action="store_true", help="Activer la diarisation")
    parser.add_argument("--timeout", type=int, default=300, help="Timeout en secondes (défaut: 300)")
    parser.add_argument("--output", "-o", type=Path, default=None, help="Fichier SRT de sortie")
    parser.add_argument("--json", action="store_true", help="Sauvegarder aussi le JSON brut")
    parser.add_argument("--debug", action="store_true", help="Afficher la timeline des mots")
    
    args = parser.parse_args()
    
    # Vérifier le fichier
    if not args.audio_file.exists():
        print(f"❌ Fichier non trouvé: {args.audio_file}")
        sys.exit(1)
    
    # Parser les keyterms
    keyterms = None
    if args.keyterms:
        keyterms = [k.strip() for k in args.keyterms.split(",") if k.strip()]
    
    # Transcrire
    print(f"\n🎙️  Transcription avec Scribe v2")
    print(f"   Fichier: {args.audio_file}")
    print(f"   Max words: {args.max_words or 'illimité'}")
    print(f"   Max chars: {args.max_chars or 'illimité'}")
    print()
    
    result = transcribe_with_scribe_v2(
        args.audio_file,
        keyterms=keyterms,
        language_code=args.language,
        diarize=args.diarize,
        timeout=args.timeout
    )
    
    # Analyse
    analysis = analyze_transcription(result)
    print(f"\n📊 Analyse:")
    print(f"   Langue: {analysis.get('language')} (confiance: {analysis.get('language_confidence', 0):.1%})")
    print(f"   Durée: {analysis.get('duration_seconds', 0):.1f}s")
    print(f"   Mots: {analysis.get('total_words', 0)}")
    print(f"   Types: {analysis.get('word_types', {})}")
    
    if analysis.get("low_confidence_words"):
        print(f"\n   ⚠️  Mots à faible confiance:")
        for w in analysis["low_confidence_words"][:5]:
            print(f"      - '{w['text']}' (logprob: {w['logprob']:.2f})")
    
    # Debug: timeline des mots
    if args.debug:
        print_word_timeline(result.get("words", []))
    
    # Construire les segments SRT
    print(f"\n🔧 Construction des segments SRT...")
    segments = build_segments_from_words(
        result.get("words", []),
        max_words=args.max_words,
        max_chars=args.max_chars
    )
    
    print(f"   {len(segments)} segments créés")
    
    # Statistiques des segments
    if segments:
        word_counts = [s.word_count for s in segments]
        char_counts = [s.char_count for s in segments]
        print(f"   Mots par segment: min={min(word_counts)}, max={max(word_counts)}, avg={sum(word_counts)/len(word_counts):.1f}")
        print(f"   Chars par segment: min={min(char_counts)}, max={max(char_counts)}, avg={sum(char_counts)/len(char_counts):.1f}")
    
    # Générer SRT
    srt_content = segments_to_srt(segments)
    
    # Afficher un aperçu
    print(f"\n📺 Aperçu SRT (premiers 5 segments):")
    print("-" * 50)
    preview_lines = srt_content.split("\n\n")[:5]
    print("\n\n".join(preview_lines))
    print("-" * 50)
    
    # Sauvegarder
    output_path = args.output or args.audio_file.with_suffix(".srt")
    output_path.write_text(srt_content, encoding="utf-8")
    print(f"\n✅ SRT sauvegardé: {output_path}")
    
    # Sauvegarder JSON si demandé
    if args.json:
        json_path = args.audio_file.with_suffix(".scribe.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"✅ JSON sauvegardé: {json_path}")
    
    print("\n🎉 Transcription terminée!")
    

if __name__ == "__main__":
    main()