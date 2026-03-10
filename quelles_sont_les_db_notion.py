import os
import requests
from dotenv import load_dotenv

load_dotenv()

NOTION_API_KEY = os.getenv("NOTION_API_KEY")

HEADERS = {
    "Authorization": f"Bearer {NOTION_API_KEY}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
}

url = "https://api.notion.com/v1/search"

payload = {
    "filter": {
        "property": "object",
        "value": "database"
    }
}

resp = requests.post(url, headers=HEADERS, json=payload)
resp.raise_for_status()

databases = resp.json()["results"]

print(f"📚 {len(databases)} bases trouvées\n")

for db in databases:
    title = db.get("title", [])
    name = title[0]["plain_text"] if title else "(sans nom)"

    print("—" * 40)
    print("Nom :", name)
    print("ID  :", db["id"])
