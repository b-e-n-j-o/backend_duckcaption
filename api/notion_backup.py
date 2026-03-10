from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import os
import requests
from dotenv import load_dotenv

# Charger .env depuis le dossier backend (indépendant du cwd au lancement)
_env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_env_path)

router = APIRouter(prefix="/notion", tags=["notion"])

NOTION_API_KEY = os.getenv("NOTION_API_KEY")
DATABASE_ID = os.getenv("NOTION_DATABASE_ID")


def _get_headers():
    if not NOTION_API_KEY or not DATABASE_ID:
        raise HTTPException(
            503,
            "Notion non configuré : définir NOTION_API_KEY et NOTION_DATABASE_ID dans le fichier .env du backend.",
        )
    return {
        "Authorization": f"Bearer {NOTION_API_KEY}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }



class SyncVideoRequest(BaseModel):
    page_name: str
    video_url: str


@router.post("/sync-video")
def sync_video_to_notion(payload: SyncVideoRequest):
    headers = _get_headers()

    # Query toutes les pages
    r = requests.post(
        f"https://api.notion.com/v1/databases/{DATABASE_ID}/query",
        headers=headers
    )
    r.raise_for_status()

    # Filtrer manuellement (case-insensitive)
    results = r.json()["results"]
    page = None

    for p in results:
        title_array = p["properties"]["Nom"]["title"]
        if title_array:
            nom = title_array[0]["text"]["content"]
            if nom.lower() == payload.page_name.lower():
                page = p
                break

    if not page:
        raise HTTPException(404, f"Page '{payload.page_name}' introuvable")

    # Update URL
    requests.patch(
        f"https://api.notion.com/v1/pages/{page['id']}",
        headers=headers,
        json={"properties": {"URL": {"url": payload.video_url}}},
    ).raise_for_status()
    
    return {"status": "ok", "page_id": page["id"]}
