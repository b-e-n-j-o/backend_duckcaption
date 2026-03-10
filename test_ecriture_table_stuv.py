import requests

API_BASE = "http://localhost:8000/api"

payload = {
    "filename": "stuv-03-fi-fr",
    "video_url": "https://vimeo.com/999999999"
}

resp = requests.post(
    f"{API_BASE}/notion/sync-video",
    json=payload
)

print("STATUS:", resp.status_code)
print("BODY:", resp.json())
