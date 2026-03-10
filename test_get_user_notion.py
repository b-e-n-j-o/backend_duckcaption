import os
import requests
from dotenv import load_dotenv

load_dotenv()

HEADERS = {
    "Authorization": f"Bearer {os.getenv('NOTION_API_KEY')}",
    "Notion-Version": "2022-06-28"
}

resp = requests.get(
    "https://api.notion.com/v1/users",
    headers=HEADERS
)
resp.raise_for_status()

users = resp.json()["results"]

for u in users:
    print("—" * 40)
    print("Nom :", u.get("name"))
    print("ID  :", u["id"])
    print("Type:", u["type"])
