### Où est géré le “nombre max de mots par segment” ?

**Ce n’est pas un paramètre Whisper du tout.**  
C’est **100 % de l’engineering de notre côté**, en post‑traitement, via notre propre logique.

### Chaîne complète des paramètres

- **Frontend** (`frontend/lib/api/transcription.ts`)  
  - Le slider envoie `max_words` et `max_chars` en query params à l’endpoint backend `generate_srt` :

```24:37:/Volumes/T7/Travaux_Freelance/KERELIA/CUAs/DUCK_CAPTION/frontend/lib/api/transcription.ts
async generateSRT(..., maxWords?: number, maxChars?: number, ...) {
  const params = new URLSearchParams();
  ...
  if (maxWords !== undefined && !isNaN(maxWords)) params.append('max_words', maxWords.toString());
  if (maxChars !== undefined && !isNaN(maxChars)) params.append('max_chars', maxChars.toString());
}
```

- **API backend** (`backend/api/transcription.py`)  
  - L’endpoint `/generate_srt/{job_id}` reçoit `max_words` / `max_chars` et les passe à `process_stt`, qui les propage ensuite à `generate_srt` (pipeline Whisper+Gemini).

- **Pipeline Whisper+Gemini** (`backend/core/whisper_gemini_pipeline.py`)  
  - `generate_srt(...)` appelle d’abord Whisper + Gemini pour produire une liste de segments `{start, end, text}`.  
  - Ensuite, **la division par nombre de mots / caractères se fait ici** :

```214:218:/Volumes/T7/Travaux_Freelance/KERELIA/CUAs/DUCK_CAPTION/backend/core/whisper_gemini_pipeline.py
    # Diviser les segments selon les limites si spécifiées
    if max_words is not None or max_chars is not None:
        print(f"📍 Division des segments (max_words={max_words}, max_chars={max_chars})...")
        aligned = split_segments_by_limit(aligned, max_words=max_words, max_chars=max_chars)
```

- **Logique de découpe** (`backend/core/srt_splitter.py`)  
  - C’est la **vraie logique métier de segmentation** :  
    - `split_segments_by_limit` prend les segments Whisper/Gemini,  
    - les découpe selon `max_words` / `max_chars`,  
    - **recalcule les timestamps** proportionnellement pour que chaque sous‑segment ait un début/fin cohérent.

```21:36:/Volumes/T7/Travaux_Freelance/KERELIA/CUAs/DUCK_CAPTION/backend/core/srt_splitter.py
def split_segments_by_limit(
    segments: List[dict],
    max_words: Optional[int] = None,
    max_chars: Optional[int] = None
) -> List[dict]:
    """
    Divise les segments SRT qui dépassent la limite spécifiée.
    ...
    Returns:
        Liste de segments divisés avec timestamps interpolés
    """
```

### En résumé

- **Whisper** renvoie des segments “bruts” (pas de notion de `max_words` / `max_chars`).  
- **Gemini** corrige le texte, mais ne gère pas non plus la découpe en fonction de ces limites.  
- **Notre code** (`srt_splitter.py`) applique ensuite les contraintes de longueur et recalcule les timestamps.  
Donc, le paramétrage “mots max / caractères max par segment” est une **fonctionnalité maison**, pas une option native des APIs d’OpenAI ou Gemini.