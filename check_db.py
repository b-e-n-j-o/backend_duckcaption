import os, requests
from dotenv import load_dotenv
load_dotenv()

HEADERS = {
    "Authorization": f"Bearer {os.getenv('NOTION_API_KEY')}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
}

DATABASE_ID = "3042401f579f80d0873fd98d62fedc76"

r = requests.post(
    f"https://api.notion.com/v1/databases/{DATABASE_ID}/query",
    headers=HEADERS,
    json={}
)

print("STATUS:", r.status_code)
print("BODY:", r.text)
