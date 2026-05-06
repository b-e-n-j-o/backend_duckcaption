#!/usr/bin/env python3
import os
import json
import requests
from pathlib import Path
from dotenv import load_dotenv

# Charge la clé depuis backend/.env
load_dotenv("/Volumes/T7/Travaux_Freelance/KERELIA/CUAs/DUCK_CAPTION/backend/.env")

API_KEY = os.getenv("ELEVENLABS_API_KEY")
AUDIO_PATH = Path(
    "/Volumes/T7/Travaux_Freelance/KERELIA/CUAs/DUCK_CAPTION/backend/tests/audios/001.mp3"
)

if not API_KEY:
    raise RuntimeError("ELEVENLABS_API_KEY manquante")
if not AUDIO_PATH.exists():
    raise FileNotFoundError(f"Fichier introuvable: {AUDIO_PATH}")

url = "https://api.elevenlabs.io/v1/speech-to-text"
headers = {"xi-api-key": API_KEY}

with open(AUDIO_PATH, "rb") as f:
    files = {"file": (AUDIO_PATH.name, f, "audio/mpeg")}
    data = {
        "model_id": "scribe_v2",
        "timestamps_granularity": "word",
        "tag_audio_events": "true",
    }

    resp = requests.post(url, headers=headers, files=files, data=data, timeout=(60, 600))

print("status_code:", resp.status_code)
print("content_type:", resp.headers.get("content-type", ""))

# Affiche la réponse brute
try:
    payload = resp.json()
    print(json.dumps(payload, ensure_ascii=False, indent=2))
except Exception:
    print(resp.text)