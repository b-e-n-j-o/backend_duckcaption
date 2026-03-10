import requests
import sys

API = "http://127.0.0.1:8000"

if len(sys.argv) < 2:
    print("Usage: python test_upload.py <video_path>")
    exit()

file_path = sys.argv[1]

print("📤 Uploading file:", file_path)

resp = requests.post(
    f"{API}/upload",
    files={"file": open(file_path, "rb")}
)

print("📥 Response:", resp.status_code, resp.json())
