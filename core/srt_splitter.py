"""
Module pour diviser les segments SRT selon une limite de mots ou caractères.

Gestion des timestamps :
- Les timestamps sont calculés proportionnellement à la longueur de chaque partie
- Si limite par mots : la durée est répartie selon le nombre de mots de chaque partie
- Si limite par caractères : la durée est répartie selon le nombre de caractères de chaque partie
- Le dernier segment utilise toujours le timestamp 'end' original pour éviter les décalages

Exemple :
  Segment original : "Bonjour comment allez-vous aujourd'hui" (5 mots, 0-5s)
  Division max_words=2 :
    - Partie 1: "Bonjour comment" (2 mots) → 0-2s (40% de 5s)
    - Partie 2: "allez-vous aujourd'hui" (3 mots) → 2-5s (60% de 5s)
"""

import math
from typing import List, Optional


def split_segments_by_limit(
    segments: List[dict],
    max_words: Optional[int] = None,
    max_chars: Optional[int] = None
) -> List[dict]:
    """
    Divise les segments SRT qui dépassent la limite spécifiée.
    
    Args:
        segments: Liste de segments avec 'start', 'end', 'text'
        max_words: Nombre maximum de mots par segment (None = pas de limite)
        max_chars: Nombre maximum de caractères par segment (None = pas de limite)
    
    Returns:
        Liste de segments divisés avec timestamps interpolés
    """
    if max_words is None and max_chars is None:
        return segments
    
    result = []
    
    for seg in segments:
        text = seg['text'].strip()
        start = seg['start']
        end = seg['end']
        duration = end - start
        
        # Compter les mots et caractères
        words = text.split()
        char_count = len(text)
        
        # Vérifier si le segment doit être divisé
        should_split = False
        if max_words and len(words) > max_words:
            should_split = True
        elif max_chars and char_count > max_chars:
            should_split = True
        
        if not should_split:
            result.append(seg)
            continue
        
        # Diviser le texte en sous-segments
        sub_texts = _split_text(text, max_words, max_chars)
        
        if len(sub_texts) == 1:
            # Pas de division possible (un seul mot trop long)
            result.append(seg)
            continue
        
        # Calculer les timestamps proportionnellement à la longueur de chaque partie
        # On utilise soit le nombre de mots, soit le nombre de caractères selon la limite utilisée
        sub_lengths = []
        total_length = 0
        
        for sub_text in sub_texts:
            if max_words:
                # Utiliser le nombre de mots comme mesure
                length = len(sub_text.split())
            else:
                # Utiliser le nombre de caractères
                length = len(sub_text)
            
            sub_lengths.append(length)
            total_length += length
        
        # Si total_length est 0 (cas improbable), fallback sur division égale
        if total_length == 0:
            num_sub_segments = len(sub_texts)
            time_per_segment = duration / num_sub_segments
            for i, sub_text in enumerate(sub_texts):
                sub_start = start + (i * time_per_segment)
                sub_end = start + ((i + 1) * time_per_segment)
                if i == len(sub_texts) - 1:
                    sub_end = end
                result.append({
                    'start': sub_start,
                    'end': sub_end,
                    'text': sub_text.strip()
                })
        else:
            # Calculer les timestamps proportionnellement
            cumulative_time = 0.0
            for i, (sub_text, length) in enumerate(zip(sub_texts, sub_lengths)):
                # Proportion de la durée totale pour ce segment
                segment_duration = (length / total_length) * duration
                
                sub_start = start + cumulative_time
                sub_end = start + cumulative_time + segment_duration
                
                # Pour le dernier segment, utiliser exactement le timestamp original
                if i == len(sub_texts) - 1:
                    sub_end = end
                
                result.append({
                    'start': sub_start,
                    'end': sub_end,
                    'text': sub_text.strip()
                })
                
                cumulative_time += segment_duration
    
    return result


def _split_text(text: str, max_words: Optional[int], max_chars: Optional[int]) -> List[str]:
    """
    Divise un texte en plusieurs parties selon les limites.
    
    Args:
        text: Texte à diviser
        max_words: Nombre maximum de mots par partie
        max_chars: Nombre maximum de caractères par partie
    
    Returns:
        Liste de parties du texte
    """
    words = text.split()
    
    if not words:
        return [text]
    
    parts = []
    current_part = []
    current_chars = 0
    
    for word in words:
        word_chars = len(word) + 1  # +1 pour l'espace
        
        # Vérifier les limites AVANT d'ajouter le mot
        would_exceed_words = max_words and (len(current_part) + 1) > max_words
        would_exceed_chars = max_chars and (current_chars + word_chars) > max_chars
        
        # Si l'ajout du mot dépasserait une limite et qu'on a déjà des mots, créer une nouvelle partie
        if (would_exceed_words or would_exceed_chars) and current_part:
            parts.append(' '.join(current_part))
            current_part = [word]
            current_chars = len(word)
        else:
            current_part.append(word)
            current_chars += word_chars
    
    # Ajouter la dernière partie
    if current_part:
        parts.append(' '.join(current_part))
    
    return parts if parts else [text]


def validate_segments(segments: List[dict]) -> bool:
    """
    Valide que les segments ont les champs requis et des timestamps valides.
    
    Args:
        segments: Liste de segments à valider
    
    Returns:
        True si valide, False sinon
    """
    for seg in segments:
        if 'start' not in seg or 'end' not in seg or 'text' not in seg:
            return False
        
        start = seg['start']
        end = seg['end']
        
        # Vérifier que les timestamps ne sont pas NaN ou infini
        if math.isnan(start) or math.isinf(start):
            return False
        if math.isnan(end) or math.isinf(end):
            return False
        
        # Vérifier que start < end
        if start >= end:
            return False
    
    return True
