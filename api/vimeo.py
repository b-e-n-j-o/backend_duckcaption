from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import os
import requests
from dotenv import load_dotenv
load_dotenv()

router = APIRouter(prefix="/vimeo", tags=["vimeo"])

VIMEO_TOKEN = os.getenv("VIMEO_TOKEN")
if not VIMEO_TOKEN:
    raise ValueError("VIMEO_TOKEN is not set")

USER_ID = "251643410"
FOLDER_ID = "27976400"

HEADERS = {
    "Authorization": f"Bearer {VIMEO_TOKEN}",
    "Accept": "application/vnd.vimeo.*+json;version=3.4",
    "Content-Type": "application/json",
}

class CreateUploadRequest(BaseModel):
    filename: str
    size: int

@router.post("/create-upload")
def create_vimeo_upload(payload: CreateUploadRequest):
    """
    Crée une ressource vidéo Vimeo avec upload TUS
    """
    payload_data = {
        "upload": {
            "approach": "tus",
            "size": payload.size,
        },
        "name": payload.filename,
    }

    resp = requests.post(
        "https://api.vimeo.com/me/videos",
        headers=HEADERS,
        json=payload_data,
    )

    if not resp.ok:
        print("❌ VIMEO ERROR STATUS:", resp.status_code)
        print("❌ VIMEO ERROR BODY:", resp.text)
        raise HTTPException(
            status_code=500,
            detail=f"Vimeo error {resp.status_code}: {resp.text}",
        )

    data = resp.json()

    return {
        "video_id": data["uri"].split("/")[-1],
        "upload_link": data["upload"]["upload_link"],
    }
