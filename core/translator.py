from dotenv import load_dotenv
load_dotenv()  # ← EN PREMIER

from typing import List
import json
import os
import google.generativeai as genai

genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

SUPPORTED_LANGUAGES = {
    "en": "English",
    "fr": "French", 
    "nl": "Dutch",
    "es": "Spanish",
    "de": "German"
}

def translate_srt_segments(srt_content: str, target_lang: str, job_id: str = None) -> str:
    """Traduit un SRT en gardant timestamps"""
    
    # Parse SRT
    segments = []
    for block in srt_content.strip().split('\n\n'):
        lines = block.split('\n')
        if len(lines) >= 3:
            segments.append({
                "index": lines[0],
                "timestamp": lines[1],
                "text": '\n'.join(lines[2:])
            })
    
    # Extraire textes uniquement
    texts = [seg["text"] for seg in segments]
    
    # Traduire en batch
    model = genai.GenerativeModel(
        "gemini-2.5-flash",
        generation_config={"response_mime_type": "application/json"}
    )
    prompt = f"""
        Tu traduis des sous-titres.

        RÈGLES ABSOLUES :

        1. Tu dois conserver EXACTEMENT {len(texts)} segments
        2. Chaque segment correspond EXACTEMENT au segment d'origine
        3. Tu ne dois PAS fusionner ni diviser de segments
        4. La traduction doit être la plus LITTÉRALE possible
        5. Conserve l'ordre des mots autant que possible
        6. Ne reformule pas les phrases
        7. Les chiffres doivent rester au même endroit dans la phrase
        8. Les marques et noms propres doivent être conservés

        Chaque segment correspond EXACTEMENT au même segment de la vidéo.

        La traduction doit être LITTÉRALE.
        Ne reformule pas les phrases.

        Les chiffres doivent rester au même endroit.
        Les marques et noms propres doivent être conservés.

        Format de sortie STRICT :

        ["translation segment 1", "translation segment 2", ...]

        Segments originaux :
        {json.dumps(texts, ensure_ascii=False)}
        """
    
    resp = model.generate_content([prompt])
    
    try:
        translated = json.loads(resp.text)
        if not isinstance(translated, list) or len(translated) != len(texts):
            raise ValueError(f"Expected {len(texts)} translations, got {len(translated) if isinstance(translated, list) else 'non-list'}")
    except Exception as e:
        print(f"⚠️ Translation parsing failed: {e}")
        print(f"Response: {resp.text[:200]}")
        raise
    
    # Compter tokens précis
    if job_id:
        from core.token_counter import calculate_costs, add_cost_to_job
        
        # Compter tokens input (prompt)
        try:
            input_tokens = model.count_tokens([prompt]).total_tokens
        except:
            # Fallback estimation
            input_tokens = len(prompt.split()) * 1.3
        
        # Compter tokens output (traductions)
        output_tokens = sum(len(t.split()) for t in translated) * 1.3  # Estimation
        
        # Calculer coût
        costs = calculate_costs(0, input_tokens, output_tokens)
        add_cost_to_job(job_id, costs["total"])
        print(f"💰 Coût traduction {target_lang}: ${costs['total']}")
    
    # Reconstruire SRT
    output = []
    for i, seg in enumerate(segments):
        output.append(f"{seg['index']}\n{seg['timestamp']}\n{translated[i]}\n")
    
    return '\n'.join(output)

