# Importe le client depuis jobs.py (qui charge .env en premier)
from core.jobs import supabase

BUCKET = "stt-projects"


def upload_file(local_path: str, dest_path: str):
    with open(local_path, "rb") as f:
        res = supabase.storage.from_(BUCKET).upload(
            dest_path,
            f,
            {
                "content-type": guess_mime(dest_path),
                "x-upsert": "true"     # 🔥 CORRECTION ici
            }
        )
    return public_url(dest_path)


def public_url(dest_path: str) -> str:
    return supabase.storage.from_(BUCKET).get_public_url(dest_path)


def guess_mime(path: str):
    if path.endswith(".mp4"):
        return "video/mp4"
    if path.endswith(".wav") or path.endswith(".mp3"):
        return "audio/mpeg"
    if path.endswith(".srt"):
        return "text/plain"
    return "application/octet-stream"
