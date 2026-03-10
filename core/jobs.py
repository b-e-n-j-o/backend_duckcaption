from dotenv import load_dotenv
load_dotenv()  # ← EN PREMIER

from supabase import create_client
import os
import uuid
from datetime import datetime

supabase = create_client(
    os.getenv("SUPABASE_URL"), 
    os.getenv("SUPABASE_SERVICE_KEY")
)

def create_job(filename: str):
    job_id = str(uuid.uuid4())
    result = supabase.schema("duck").table("jobs").insert({
        "id": job_id,
        "filename": filename,
        "status": "uploaded",
        "created_at": datetime.utcnow().isoformat()
    }).execute()
    return result.data[0]

def update_job(job_id: str, **kwargs):
    kwargs["updated_at"] = datetime.utcnow().isoformat()
    result = supabase.schema("duck").table("jobs").update(kwargs).eq("id", job_id).execute()
    return result.data[0]

def get_job(job_id: str):
    result = supabase.schema("duck").table("jobs").select("*").eq("id", job_id).single().execute()
    return result.data