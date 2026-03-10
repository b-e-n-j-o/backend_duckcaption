import requests
import sys

API = "http://127.0.0.1:8000"

if len(sys.argv) < 2:
    print("Usage: python test_get_job_status.py <job_id>")
    exit()

job_id = sys.argv[1]

resp = requests.get(f"{API}/job/{job_id}")

print("📊 Status:", resp.status_code, resp.json())
