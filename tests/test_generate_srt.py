import requests
import sys

API = "http://127.0.0.1:8000"

if len(sys.argv) < 2:
    print("Usage: python test_generate_srt.py <job_id> [context]")
    exit()

job_id = sys.argv[1]
context = sys.argv[2] if len(sys.argv) > 2 else ""

print("📄 Generating SRT for job", job_id)

resp = requests.post(
    f"{API}/generate_srt/{job_id}",
    params={"context": context}
)

print("➡️ Result:", resp.status_code, resp.json())
