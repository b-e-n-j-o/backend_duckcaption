# test_notion.py
import os
import requests
from dotenv import load_dotenv

load_dotenv()

NOTION_API_KEY = os.getenv("NOTION_API_KEY")
DATABASE_ID = os.getenv("NOTION_DATABASE_ID")

HEADERS = {
    "Authorization": f"Bearer {NOTION_API_KEY}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json"
}

# 1. Lister toutes les lignes
print("📋 Lignes existantes :")
r = requests.post(
    f"https://api.notion.com/v1/databases/{DATABASE_ID}/query",
    headers=HEADERS
)
r.raise_for_status()

for page in r.json()["results"]:
    nom = page["properties"]["Nom"]["title"][0]["text"]["content"]
    url_prop = page["properties"]["URL"].get("url", "")
    print(f"  - {nom}: {url_prop or '(vide)'}")

# 2. Tester updates
tests = [
    ("Marc", "https://vimeo.com/fake111"),
    ("Yann", "https://vimeo.com/fake222")
]

for nom, url in tests:
    print(f"\n🔄 Sync '{nom}' → {url}")
    
    r = requests.post(
        "http://localhost:8000/api/notion/sync-video",
        json={"page_name": nom, "video_url": url}
    )
    
    if r.ok:
        print(f"  ✅ {r.json()}")
    else:
        print(f"  ❌ {r.status_code}: {r.text}")

# 3. Vérifier résultats
print("\n📋 Après updates :")
r = requests.post(
    f"https://api.notion.com/v1/databases/{DATABASE_ID}/query",
    headers=HEADERS
)

for page in r.json()["results"]:
    nom = page["properties"]["Nom"]["title"][0]["text"]["content"]
    url_prop = page["properties"]["URL"].get("url", "")
    print(f"  - {nom}: {url_prop}")