from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import os
import requests
from datetime import datetime
import re
from dotenv import load_dotenv

load_dotenv()

router = APIRouter(prefix="/notion", tags=["notion"])

NOTION_API_KEY = os.getenv("NOTION_API_KEY")
if not NOTION_API_KEY:
    raise RuntimeError("NOTION_API_KEY manquant")

HEADERS = {
    "Authorization": f"Bearer {NOTION_API_KEY}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
}

def normalize(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())

class SyncVideoRequest(BaseModel):
    filename: str
    video_url: str

@router.post("/sync-video")
def sync_video_to_notion(payload: SyncVideoRequest):
    filename = payload.filename.strip()
    client_key = filename.split("-")[0].lower()

    print("🚀 [SYNC]")
    print("  filename   =", filename)
    print("  client_key =", client_key)

    # 1️⃣ Découverte des bases
    search = requests.post(
        "https://api.notion.com/v1/search",
        headers=HEADERS,
        json={"filter": {"property": "object", "value": "database"}}
    )
    search.raise_for_status()

    databases = search.json()["results"]
    print(f"📚 [NOTION] {len(databases)} bases trouvées")

    matches = []
    for db in databases:
        title = db.get("title", [])
        if not title:
            continue
        name = title[0]["plain_text"]
        if normalize(client_key) in normalize(name):
            matches.append({"name": name, "id": db["id"]})

    if len(matches) == 0:
        raise HTTPException(404, f"Aucune base pour client '{client_key}'")

    if len(matches) > 1:
        raise HTTPException(409, {"error": "Ambiguïté", "matches": matches})

    database_id = matches[0]["id"]
    db_name = matches[0]["name"]
    print("🔎 [MATCHES] =", matches)
    print("📚 [DB CHOSEN] =", db_name, database_id)

    # 2️⃣ Query lignes
    query = requests.post(
        f"https://api.notion.com/v1/databases/{database_id}/query",
        headers=HEADERS,
        json={}
    )
    query.raise_for_status()

    rows = query.json()["results"]
    print(f"📄 [ROWS] {len(rows)} lignes")

    target_page = None
    for page in rows:
        title = page["properties"].get("Nom", {}).get("title", [])
        if not title:
            continue
        row_name = title[0]["text"]["content"]
        print("   • ligne:", row_name)
        if row_name.lower() == filename.lower():
            target_page = page
            break

    # 3️⃣ CREATE si absent
    if not target_page:
        print("➕ [CREATE] ligne inexistante")

        create_resp = requests.post(
            "https://api.notion.com/v1/pages",
            headers=HEADERS,
            json={
                "parent": {"database_id": database_id},
                "properties": {
                    "Nom": {
                        "title": [{"text": {"content": filename}}]
                    },
                    "URL": {"url": payload.video_url},
                    "Publiée": {"checkbox": False},
                    "Date": {
                        "date": {"start": datetime.utcnow().date().isoformat()}
                    }
                }
            }
        )

        print("✏️ [CREATE STATUS] =", create_resp.status_code)
        print("✏️ [CREATE BODY]   =", create_resp.text)
        create_resp.raise_for_status()

        return {
            "status": "created",
            "client": client_key,
            "database": db_name,
            "filename": filename
        }

    # 4️⃣ PATCH si existe
    page_id = target_page["id"]
    print("✏️ [PAGE ID] =", page_id)

    patch = requests.patch(
        f"https://api.notion.com/v1/pages/{page_id}",
        headers=HEADERS,
        json={
            "properties": {
                "URL": {"url": payload.video_url},
                "Publiée": {"checkbox": False},
                "Date": {
                    "date": {"start": datetime.utcnow().date().isoformat()}
                }
            }
        }
    )

    print("✏️ [PATCH STATUS] =", patch.status_code)
    print("✏️ [PATCH BODY]   =", patch.text)
    patch.raise_for_status()

    return {
        "status": "updated",
        "client": client_key,
        "database": db_name,
        "filename": filename
    }
