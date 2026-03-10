import requests
import sys

API = "http://127.0.0.1:8000"

if len(sys.argv) < 2:
    print("Usage: python test_generate_proxy.py <job_id>")
    exit()

job_id = sys.argv[1]

print("🎬 Generating proxy for job", job_id)

resp = requests.post(f"{API}/generate_proxy/{job_id}")

print("➡️ Result:", resp.status_code, resp.json())
