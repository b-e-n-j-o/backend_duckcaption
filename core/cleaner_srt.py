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
        "gemini-3.1-flash-lite-preview",
        generation_config={"response_mime_type": "application/json"}
    )

    numbered = {str(i): t for i, t in enumerate(texts)}

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

Format de sortie STRICT — un objet JSON avec des clés indexées :
{{"0": "segment 0 nettoyé", "1": "segment 1 nettoyé", ...}}

CRITICAL:
- You MUST return EXACTLY {len(texts)} keys in the JSON object.
- Keys MUST be strings from "0" to "{len(texts) - 1}".
- Even if two segments seem to belong together, keep them as separate items.
- Each key MUST correspond to the same input segment index.
- Incomplete segments are NORMAL in subtitles; keep them incomplete if needed.
- Example (3 segments):
  {{"0": "cleaned segment 0", "1": "cleaned segment 1", "2": "cleaned segment 2"}}

Segments à nettoyer :
{json.dumps(numbered, ensure_ascii=False)}
"""

    cleaned = None
    last_resp_preview = ""

    for attempt in range(2):
        print(f"🧹 Cleaner: {len(texts)} segments → Gemini... (attempt {attempt + 1}/2)")
        resp = model.generate_content([prompt])
        print("✅ Cleaner: réponse reçue")
        last_resp_preview = resp.text[:200]

        try:
            result_dict = json.loads(resp.text)
            if isinstance(result_dict, dict):
                expected_keys = [str(i) for i in range(len(texts))]
                if all(k in result_dict for k in expected_keys):
                    cleaned = [str(result_dict[str(i)]) for i in range(len(texts))]
                    break
                got = f"missing keys (got {len(result_dict)} keys)"
            else:
                got = "non-dict"

            if attempt == 0:
                print(
                    f"⚠️ Attempt {attempt + 1}: invalid structure ({got}), "
                    f"expected keys 0..{len(texts) - 1}, retrying..."
                )
            else:
                print(
                    f"⚠️ Attempt {attempt + 1}: invalid structure ({got}), "
                    f"expected keys 0..{len(texts) - 1}, fallback."
                )
        except Exception as e:
            if attempt == 0:
                print(f"⚠️ Attempt {attempt + 1}: parse error: {e}; retrying...")
            else:
                print(f"⚠️ Attempt {attempt + 1}: parse error: {e}; fallback.")

    if cleaned is None:
        print(f"Response: {last_resp_preview}")
        # Fallback : retourner l'original non modifié plutôt que planter
        return srt_content

    # Tracking coûts — identique à la traduction
    if job_id:
        try:
            from core.token_counter import calculate_model_text_costs, add_cost_component_to_job
            try:
                input_tokens = model.count_tokens([prompt]).total_tokens
            except:
                input_tokens = len(prompt.split()) * 1.3
            output_tokens = sum(len(t.split()) for t in cleaned) * 1.3
            costs = calculate_model_text_costs(
                "gemini-3.1-flash-lite-preview",
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )
            add_cost_component_to_job(job_id, "cleaning_gemini", costs["total"])
            print(
                f"💰 Coût cleaning: ${costs['total']} "
                f"(model={costs['model']}, in={costs['input_tokens']} @ ${costs['input_rate_per_1m']}/1M, "
                f"out={costs['output_tokens']} @ ${costs['output_rate_per_1m']}/1M)"
            )
        except Exception as e:
            print(f"⚠️ Cost tracking failed: {e}")

    # Reconstruire SRT — identique à la traduction
    output = []
    for i, seg in enumerate(segments):
        output.append(f"{seg['index']}\n{seg['timestamp']}\n{cleaned[i]}\n")

    return '\n'.join(output)