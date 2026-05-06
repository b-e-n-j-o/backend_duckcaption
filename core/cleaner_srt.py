"""
Cleaner - Module de nettoyage SRT post-transcription

Nettoie intelligemment les disfluences et artefacts de transcription
via Gemini, sans toucher aux timestamps.

Cas traités :
- Faux départs : "a-aspect" → "aspect"
- Répétitions/hésitations : "le le le plus" → "le plus"
- Mots tronqués : "pro- production" → "production"
- Bruits transcrits : "euh", "um", "hm" isolés
- Autres artefacts imprévisibles laissés à l'appréciation du modèle
"""

from dotenv import load_dotenv
load_dotenv()

import json
import os
import google.generativeai as genai

genai.configure(api_key=os.getenv("GEMINI_API_KEY"))


def clean_srt_segments(srt_content: str, language: str = "fr", job_id: str = None) -> str:
    """
    Nettoie un SRT post-transcription en gardant les timestamps intacts.
    
    Args:
        srt_content: Contenu SRT brut sorti de l'engine
        language: Langue du contenu (pour adapter les consignes)
        job_id: Pour tracking des coûts
    
    Returns:
        SRT nettoyé, timestamps inchangés
    """

    # Parse SRT — identique à translate_srt_segments
    segments = []
    for block in srt_content.strip().split('\n\n'):
        lines = block.split('\n')
        if len(lines) >= 3:
            segments.append({
                "index": lines[0],
                "timestamp": lines[1],
                "text": '\n'.join(lines[2:])
            })

    if not segments:
        return srt_content

    texts = [seg["text"] for seg in segments]

    model = genai.GenerativeModel(
        "gemini-2.5-flash-lite",
        generation_config={"response_mime_type": "application/json"}
    )

    prompt = f"""
Tu corriges des sous-titres issus d'une transcription automatique de la parole ({language}).
Ton rôle est de nettoyer les artefacts oraux sans reformuler ni paraphraser le contenu.

RÈGLES ABSOLUES :
1. Tu dois retourner EXACTEMENT {len(texts)} segments — ni plus, ni moins
2. Chaque segment en sortie correspond EXACTEMENT au segment d'entrée (même position)
3. Tu ne dois PAS fusionner ni diviser des segments
4. Tu ne dois PAS reformuler, résumer ou paraphraser
5. Si un segment est déjà propre, retourne-le tel quel

CORRECTIONS AUTORISÉES :
- Faux départs : "a-aspect" → "aspect", "pro- production" → "production"
- Répétitions/hésitations : "le le le plus grand" → "le plus grand"
- Hésitations isolées : "euh", "um", "hm", "bah", "ben" seuls ou en début de segment
- Mots tronqués suivis de leur forme complète : "je vou- je voudrais" → "je voudrais"
- Bégaiements : "c'c'est" → "c'est"

NE PAS TOUCHER :
- Les mots composés avec tiret légitimes : "anti-inflammatoire", "Jean-Pierre", "vis-à-vis"
- Les chiffres, noms propres, marques
- La ponctuation existante
- Les retours à la ligne internes (\\n) dans un segment

Format de sortie STRICT — un tableau JSON de strings :
["segment nettoyé 1", "segment nettoyé 2", ...]

Segments à nettoyer :
{json.dumps(texts, ensure_ascii=False)}
"""

    print(f"🧹 Cleaner: {len(texts)} segments → Gemini...")
    resp = model.generate_content([prompt])
    print("✅ Cleaner: réponse reçue")

    try:
        cleaned = json.loads(resp.text)
        if not isinstance(cleaned, list) or len(cleaned) != len(texts):
            raise ValueError(
                f"Expected {len(texts)} segments, got "
                f"{len(cleaned) if isinstance(cleaned, list) else 'non-list'}"
            )
    except Exception as e:
        print(f"⚠️ Cleaning parsing failed: {e}")
        print(f"Response: {resp.text[:200]}")
        # Fallback : retourner l'original non modifié plutôt que planter
        return srt_content

    # Tracking coûts — identique à la traduction
    if job_id:
        try:
            from core.token_counter import calculate_costs, add_cost_to_job
            try:
                input_tokens = model.count_tokens([prompt]).total_tokens
            except:
                input_tokens = len(prompt.split()) * 1.3
            output_tokens = sum(len(t.split()) for t in cleaned) * 1.3
            costs = calculate_costs(0, input_tokens, output_tokens)
            add_cost_to_job(job_id, costs["total"])
            print(f"💰 Coût cleaning: ${costs['total']}")
        except Exception as e:
            print(f"⚠️ Cost tracking failed: {e}")

    # Reconstruire SRT — identique à la traduction
    output = []
    for i, seg in enumerate(segments):
        output.append(f"{seg['index']}\n{seg['timestamp']}\n{cleaned[i]}\n")

    return '\n'.join(output)