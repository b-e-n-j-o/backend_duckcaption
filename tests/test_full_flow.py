import requests
import sys
import time

API = "http://127.0.0.1:8000"

if len(sys.argv) < 2:
    print("Usage: python test_full_flow.py <video_path> [context]")
    exit()

file_path = sys.argv[1]
context = sys.argv[2] if len(sys.argv) > 2 else ""

# 1. Upload
print("📤 Uploading...")
resp = requests.post(f"{API}/upload", files={"file": open(file_path, "rb")})
data = resp.json()
job_id = data["job_id"]
print("✔ Uploaded job:", job_id)

# 2. Generate proxy
print("🎬 Generating proxy...")
resp = requests.post(f"{API}/generate_proxy/{job_id}")
print("✔ Proxy done:", resp.json())

# 3. Generate SRT
print("📝 Generating SRT...")
resp = requests.post(f"{API}/generate_srt/{job_id}", params={"context": context})
print("✔ SRT:", resp.json())

# 4. Fetch status
print("📊 Final job status:")
resp = requests.get(f"{API}/job/{job_id}")
print(resp.json())

print("🎉 End-to-end test complete")
