import time
import shutil
from pathlib import Path
from datetime import datetime
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import requests
import logging

# Config
WATCH_DIR = Path.home() / "Desktop" / "DROP"
WATCH_DIR.mkdir(exist_ok=True)  # ← Ajouter AVANT logging
API_BASE = "http://localhost:8000/api"

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)

def upload_tus(filepath: Path, upload_link: str):
    """Upload TUS direct vers Vimeo"""
    with open(filepath, 'rb') as f:
        data = f.read()
    
    requests.patch(
        upload_link,
        data=data,
        headers={
            'Tus-Resumable': '1.0.0',
            'Upload-Offset': '0',
            'Content-Type': 'application/offset+octet-stream',
        },
        timeout=600
    ).raise_for_status()

class VideoHandler(FileSystemEventHandler):
    def on_created(self, event):
        if event.is_directory:
            return
        
        filepath = Path(event.src_path)
        if filepath.suffix.lower() not in ['.mp4', '.mov', '.avi', '.mkv']:
            return
        
        time.sleep(2)  # Attendre fin de copie
        self.process(filepath)
    
    def process(self, filepath: Path):
        # client_key = premier segment du nom (ex: stuv-01-fi-fr.mp4 → stuv)
        client_key = filepath.stem.split("-")[0].lower()

        logging.info(f"📹 {filepath.name} → client_key '{client_key}'")

        try:
            # 1. Créer ressource Vimeo
            with open(filepath, 'rb') as f:
                f.seek(0, 2)
                size = f.tell()
            
            r1 = requests.post(
                f"{API_BASE}/vimeo/create-upload",
                json={'filename': filepath.name, 'size': size}
            )
            r1.raise_for_status()
            data = r1.json()
            
            # 2. Upload TUS
            logging.info("📤 Upload vers Vimeo...")
            upload_tus(filepath, data['upload_link'])
            
            # 3. Sync Notion
            vimeo_url = f"https://vimeo.com/{data['video_id']}"
            requests.post(
                f"{API_BASE}/notion/sync-video",
                json={
                    "client_key": client_key,
                    "filename": filepath.stem,
                    "video_url": vimeo_url
                }
            ).raise_for_status()
            
            logging.info(f"✅ {vimeo_url}")
            
            # Fichier succès
            success = WATCH_DIR / f"✅_{filepath.stem}.txt"
            success.write_text(
                f"✅ Succès\n"
                f"Vimeo: {vimeo_url}\n"
                f"client_key: {client_key}\n"
                f"{datetime.now()}"
            )
            
            # Supprimer vidéo
            filepath.unlink()
        
        except Exception as e:
            logging.error(f"❌ {filepath.name}: {e}")
            error = WATCH_DIR / f"❌_{filepath.stem}.txt"
            error.write_text(
                f"❌ ERREUR\n{str(e)}\n{datetime.now()}"
                )

def main():
    WATCH_DIR.mkdir(exist_ok=True)
    logging.info(f"👁️ Surveillance: {WATCH_DIR}")
    
    handler = VideoHandler()
    observer = Observer()
    observer.schedule(handler, str(WATCH_DIR), recursive=False)
    observer.start()
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()

if __name__ == "__main__":
    main()