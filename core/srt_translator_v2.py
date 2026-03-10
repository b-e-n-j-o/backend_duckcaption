"""
Module de traduction SRT avec contraintes de fidélité.

Objectifs:
- Traduction littérale (pas de réarrangement entre segments)
- Respect des timings (chaque segment traduit correspond au même moment)
- Support des contraintes max_words / max_chars

Trois modes disponibles:
1. SEGMENT_BY_SEGMENT: Traduit chaque segment individuellement (plus lent, plus fidèle)
2. BATCH_STRICT: Traduit en batch avec contraintes strictes (équilibré)
3. WORD_LEVEL: Exploite les timestamps mot-par-mot de Scribe v2 (le plus précis)
"""

from dotenv import load_dotenv
load_dotenv()

import json
import os
import re
from dataclasses import dataclass
from typing import List, Optional, Literal
from enum import Enum

import google.generativeai as genai

genai.configure(api_key=os.getenv("GEMINI_API_KEY"))


# ============================================================
# CONFIGURATION
# ============================================================

SUPPORTED_LANGUAGES = {
    "en": "English",
    "fr": "French (France)", 
    "nl": "Dutch",
    "es": "Spanish (Spain)",
    "de": "German",
    "it": "Italian",
    "pt": "Portuguese (Brazil)",
    "ja": "Japanese",
    "ko": "Korean",
    "zh": "Chinese (Simplified)"
}

class TranslationMode(Enum):
    SEGMENT_BY_SEGMENT = "segment_by_segment"
    BATCH_STRICT = "batch_strict"
    WORD_LEVEL = "word_level"


# ============================================================
# DATA STRUCTURES
# ============================================================

@dataclass
class SRTSegment:
    """Un segment SRT avec index, timestamps et texte."""
    index: int
    start_time: str  # Format: "00:00:01,234"
    end_time: str
    text: str
    
    @property
    def timestamp_line(self) -> str:
        return f"{self.start_time} --> {self.end_time}"
    
    @property
    def word_count(self) -> int:
        return len(self.text.split())
    
    def to_srt_block(self) -> str:
        return f"{self.index}\n{self.timestamp_line}\n{self.text}\n"


@dataclass
class WordWithTimestamp:
    """Un mot avec son timestamp (pour mode WORD_LEVEL)."""
    text: str
    start: float
    end: float
    type: str = "word"  # word, punctuation, audio_event


# ============================================================
# SRT PARSING
# ============================================================

def parse_srt(srt_content: str) -> List[SRTSegment]:
    """Parse un fichier SRT en liste de segments."""
    segments = []
    blocks = re.split(r'\n\n+', srt_content.strip())
    
    for block in blocks:
        lines = block.strip().split('\n')
        if len(lines) >= 3:
            # Parse timestamp line
            timestamp_match = re.match(
                r'(\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2},\d{3})',
                lines[1]
            )
            if timestamp_match:
                segments.append(SRTSegment(
                    index=int(lines[0]),
                    start_time=timestamp_match.group(1),
                    end_time=timestamp_match.group(2),
                    text='\n'.join(lines[2:])
                ))
    
    return segments


def segments_to_srt(segments: List[SRTSegment]) -> str:
    """Convertit une liste de segments en contenu SRT."""
    return '\n'.join(seg.to_srt_block() for seg in segments)


# ============================================================
# MODE 1: BATCH STRICT (recommandé pour la plupart des cas)
# ============================================================

def translate_batch_strict(
    segments: List[SRTSegment],
    target_lang: str,
    max_words: Optional[int] = None,
    max_chars: Optional[int] = None
) -> List[SRTSegment]:
    """
    Traduit tous les segments en batch avec contraintes strictes.
    
    Le prompt force Gemini à:
    - Garder exactement le même nombre de segments
    - Ne pas déplacer de contenu entre segments
    - Respecter les contraintes de longueur
    """
    
    model = genai.GenerativeModel(
        "gemini-2.5-flash",
        generation_config={"response_mime_type": "application/json"}
    )
    
    # Préparer les données d'entrée avec métadonnées
    input_data = []
    for seg in segments:
        input_data.append({
            "id": seg.index,
            "text": seg.text,
            "word_count": seg.word_count
        })
    
    # Contraintes de longueur
    length_constraint = ""
    if max_words:
        length_constraint += f"\n- Maximum {max_words} mots par segment"
    if max_chars:
        length_constraint += f"\n- Maximum {max_chars} caractères par segment"
    
    prompt = f"""Tu es un traducteur professionnel de sous-titres vidéo.

RÈGLES STRICTES - À RESPECTER ABSOLUMENT:

1. NOMBRE DE SEGMENTS: Tu reçois {len(segments)} segments, tu DOIS retourner exactement {len(segments)} segments traduits.

2. CORRESPONDANCE 1:1: Chaque segment traduit doit correspondre EXACTEMENT au même moment de la vidéo.
   - Le segment 1 traduit = contenu du segment 1 original
   - Le segment 2 traduit = contenu du segment 2 original
   - etc.
   
3. PAS DE RÉARRANGEMENT: Ne déplace JAMAIS du contenu d'un segment à un autre.
   - Si l'original dit "20% des enfants" dans le segment 3, la traduction de "20%" doit être dans le segment 3.
   - Les chiffres, noms propres, données spécifiques doivent rester dans leur segment d'origine.

4. TRADUCTION LITTÉRALE: Privilégie une traduction proche de la structure originale.
   - Garde l'ordre des idées
   - Évite les reformulations qui changent l'ordre des mots-clés
{length_constraint}

5. FORMAT DE SORTIE: Retourne UNIQUEMENT un tableau JSON avec les traductions dans l'ordre:
   ["traduction segment 1", "traduction segment 2", ...]

Langue cible: {SUPPORTED_LANGUAGES.get(target_lang, target_lang)}

Segments à traduire:
{json.dumps(input_data, ensure_ascii=False, indent=2)}
"""
    
    response = model.generate_content([prompt])
    
    try:
        translated_texts = json.loads(response.text)
        
        if not isinstance(translated_texts, list):
            raise ValueError(f"Expected list, got {type(translated_texts)}")
        if len(translated_texts) != len(segments):
            raise ValueError(f"Expected {len(segments)} translations, got {len(translated_texts)}")
        
        # Reconstruire les segments avec les traductions
        result = []
        for i, seg in enumerate(segments):
            result.append(SRTSegment(
                index=seg.index,
                start_time=seg.start_time,
                end_time=seg.end_time,
                text=translated_texts[i].strip()
            ))
        
        return result
        
    except json.JSONDecodeError as e:
        print(f"❌ Erreur parsing JSON: {e}")
        print(f"   Réponse: {response.text[:500]}")
        raise
    except Exception as e:
        print(f"❌ Erreur traduction: {e}")
        raise


# ============================================================
# MODE 2: SEGMENT PAR SEGMENT (plus lent, plus fidèle)
# ============================================================

def translate_segment_by_segment(
    segments: List[SRTSegment],
    target_lang: str,
    max_words: Optional[int] = None,
    max_chars: Optional[int] = None
) -> List[SRTSegment]:
    """
    Traduit chaque segment individuellement avec contexte.
    Plus lent mais garantit la correspondance 1:1.
    """
    
    model = genai.GenerativeModel(
        "gemini-2.5-flash",
        generation_config={"response_mime_type": "application/json"}
    )
    
    result = []
    
    for i, seg in enumerate(segments):
        # Contexte: segments précédent et suivant
        context_before = segments[i-1].text if i > 0 else ""
        context_after = segments[i+1].text if i < len(segments)-1 else ""
        
        # Contraintes
        constraints = []
        if max_words:
            constraints.append(f"maximum {max_words} mots")
        if max_chars:
            constraints.append(f"maximum {max_chars} caractères")
        constraint_str = " et ".join(constraints) if constraints else "longueur similaire à l'original"
        
        prompt = f"""Traduis ce sous-titre en {SUPPORTED_LANGUAGES.get(target_lang, target_lang)}.

Contexte (ne pas traduire, juste pour comprendre):
- Avant: "{context_before}"
- Après: "{context_after}"

Texte à traduire: "{seg.text}"

Contraintes: {constraint_str}

Retourne UNIQUEMENT un objet JSON: {{"translation": "ta traduction ici"}}
"""
        
        response = model.generate_content([prompt])
        
        try:
            data = json.loads(response.text)
            translated_text = data.get("translation", seg.text)
        except:
            # Fallback: utiliser le texte brut
            translated_text = response.text.strip().strip('"')
        
        result.append(SRTSegment(
            index=seg.index,
            start_time=seg.start_time,
            end_time=seg.end_time,
            text=translated_text
        ))
        
        # Progress
        if (i + 1) % 10 == 0:
            print(f"   Traduit {i+1}/{len(segments)} segments...")
    
    return result


# ============================================================
# MODE 3: WORD LEVEL (exploite Scribe v2)
# ============================================================

def translate_word_level(
    words: List[dict],  # Format Scribe v2: [{"text": "...", "start": 0.0, "end": 0.5}, ...]
    target_lang: str,
    max_words: Optional[int] = None,
    max_chars: Optional[int] = None
) -> List[SRTSegment]:
    """
    Traduit en exploitant les timestamps mot-par-mot de Scribe v2.
    
    Processus:
    1. Gemini identifie des "groupes logiques" de mots à traduire ensemble
    2. Chaque groupe garde ses timestamps précis
    3. On assemble selon max_words/max_chars
    """
    
    model = genai.GenerativeModel(
        "gemini-2.5-flash",
        generation_config={"response_mime_type": "application/json"}
    )
    
    # Filtrer les mots (exclure les espaces purs)
    actual_words = [w for w in words if w.get("type") != "spacing" and w.get("text", "").strip()]
    
    # Préparer l'input avec indices pour tracking
    words_input = []
    for i, w in enumerate(actual_words):
        words_input.append({
            "idx": i,
            "text": w["text"],
            "start": w["start"],
            "end": w["end"]
        })
    
    prompt = f"""Tu es un traducteur de sous-titres. Tu reçois des mots avec leurs timestamps.

TÂCHE:
1. Identifie des groupes de mots qui doivent être traduits ENSEMBLE (expressions, groupes nominaux, etc.)
2. Traduis chaque groupe en {SUPPORTED_LANGUAGES.get(target_lang, target_lang)}
3. Garde les timestamps du premier et dernier mot de chaque groupe

RÈGLES:
- Ne change PAS l'ordre des groupes
- Les nombres et noms propres gardent leur position
- Chaque groupe doit avoir entre 1 et 5 mots sources max

FORMAT DE SORTIE (JSON array):
[
  {{
    "source_indices": [0, 1, 2],  // indices des mots sources dans ce groupe
    "start": 0.0,                  // timestamp début (du premier mot)
    "end": 1.5,                    // timestamp fin (du dernier mot)
    "source_text": "hello world",  // texte source (pour vérification)
    "translation": "bonjour monde" // traduction
  }},
  ...
]

Mots sources avec timestamps:
{json.dumps(words_input, ensure_ascii=False)}
"""
    
    response = model.generate_content([prompt])
    
    try:
        groups = json.loads(response.text)
    except:
        print(f"❌ Erreur parsing groupes: {response.text[:300]}")
        raise
    
    # Assembler en segments SRT selon max_words/max_chars
    segments = []
    current_words = []
    current_start = None
    current_end = None
    segment_index = 1
    
    for group in groups:
        translation = group.get("translation", "")
        start = group.get("start", 0)
        end = group.get("end", 0)
        
        # Initialiser le premier segment
        if current_start is None:
            current_start = start
        
        # Vérifier si on dépasse les limites
        test_text = " ".join(current_words + [translation])
        test_word_count = len(test_text.split())
        test_char_count = len(test_text)
        
        should_break = False
        if max_words and test_word_count > max_words:
            should_break = True
        if max_chars and test_char_count > max_chars:
            should_break = True
        
        if should_break and current_words:
            # Créer le segment
            segments.append(SRTSegment(
                index=segment_index,
                start_time=_seconds_to_srt_time(current_start),
                end_time=_seconds_to_srt_time(current_end),
                text=" ".join(current_words)
            ))
            segment_index += 1
            current_words = [translation]
            current_start = start
            current_end = end
        else:
            current_words.append(translation)
            current_end = end
    
    # Dernier segment
    if current_words:
        segments.append(SRTSegment(
            index=segment_index,
            start_time=_seconds_to_srt_time(current_start),
            end_time=_seconds_to_srt_time(current_end),
            text=" ".join(current_words)
        ))
    
    return segments


def _seconds_to_srt_time(seconds: float) -> str:
    """Convertit des secondes en format SRT (00:00:00,000)."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds - int(seconds)) * 1000)
    return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"


# ============================================================
# API PRINCIPALE
# ============================================================

def translate_srt(
    srt_content: str,
    target_lang: str,
    mode: TranslationMode = TranslationMode.BATCH_STRICT,
    max_words: Optional[int] = None,
    max_chars: Optional[int] = None,
    words_data: Optional[List[dict]] = None  # Pour mode WORD_LEVEL
) -> str:
    """
    Traduit un fichier SRT.
    
    Args:
        srt_content: Contenu SRT à traduire
        target_lang: Code langue cible (en, fr, es, etc.)
        mode: Mode de traduction
        max_words: Nombre max de mots par segment
        max_chars: Nombre max de caractères par segment
        words_data: Données mot-par-mot de Scribe v2 (requis pour mode WORD_LEVEL)
    
    Returns:
        Contenu SRT traduit
    """
    
    if target_lang not in SUPPORTED_LANGUAGES:
        raise ValueError(f"Langue non supportée: {target_lang}. Supportées: {list(SUPPORTED_LANGUAGES.keys())}")
    
    print(f"🌍 Traduction vers {SUPPORTED_LANGUAGES[target_lang]} (mode: {mode.value})")
    
    if mode == TranslationMode.WORD_LEVEL:
        if not words_data:
            raise ValueError("words_data requis pour mode WORD_LEVEL")
        segments = translate_word_level(words_data, target_lang, max_words, max_chars)
    else:
        # Parser le SRT
        segments = parse_srt(srt_content)
        print(f"   {len(segments)} segments à traduire")
        
        if mode == TranslationMode.BATCH_STRICT:
            segments = translate_batch_strict(segments, target_lang, max_words, max_chars)
        elif mode == TranslationMode.SEGMENT_BY_SEGMENT:
            segments = translate_segment_by_segment(segments, target_lang, max_words, max_chars)
    
    print(f"✅ Traduction terminée: {len(segments)} segments")
    
    return segments_to_srt(segments)


# ============================================================
# CLI POUR TESTS
# ============================================================

if __name__ == "__main__":
    import argparse
    from pathlib import Path
    
    parser = argparse.ArgumentParser(description="Traduire un fichier SRT")
    parser.add_argument("srt_file", type=Path, help="Fichier SRT à traduire")
    parser.add_argument("--lang", "-l", required=True, help="Langue cible (en, fr, es, etc.)")
    parser.add_argument("--mode", "-m", choices=["batch", "segment", "word"], default="batch",
                        help="Mode de traduction")
    parser.add_argument("--max-words", type=int, help="Max mots par segment")
    parser.add_argument("--max-chars", type=int, help="Max caractères par segment")
    parser.add_argument("--words-json", type=Path, help="Fichier JSON Scribe v2 (pour mode word)")
    parser.add_argument("--output", "-o", type=Path, help="Fichier de sortie")
    
    args = parser.parse_args()
    
    # Lire le SRT
    srt_content = args.srt_file.read_text(encoding="utf-8")
    
    # Mode
    mode_map = {
        "batch": TranslationMode.BATCH_STRICT,
        "segment": TranslationMode.SEGMENT_BY_SEGMENT,
        "word": TranslationMode.WORD_LEVEL
    }
    mode = mode_map[args.mode]
    
    # Données mots (si mode word)
    words_data = None
    if args.words_json:
        words_data = json.loads(args.words_json.read_text())
        if "words" in words_data:
            words_data = words_data["words"]
    
    # Traduire
    translated = translate_srt(
        srt_content,
        args.lang,
        mode=mode,
        max_words=args.max_words,
        max_chars=args.max_chars,
        words_data=words_data
    )
    
    # Sauvegarder
    output_path = args.output or args.srt_file.with_stem(f"{args.srt_file.stem}_{args.lang}")
    output_path.write_text(translated, encoding="utf-8")
    print(f"📄 Sauvegardé: {output_path}")