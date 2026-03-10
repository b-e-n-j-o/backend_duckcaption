#!/usr/bin/env python3
"""
Test minimal Scribe v2 avec requests (pas le SDK)
Pour debugger les problèmes de connexion
"""

import os
import sys
import time
import requests
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("ELEVENLABS_API_KEY")

def test_scribe(audio_path: str):
    path = Path(audio_path)
    if not path.exists():
        print(f"❌ Fichier non trouvé: {audio_path}")
        return
    
    file_size = path.stat().st_size / 1024  # KB
    print(f"📁 Fichier: {path.name}")
    print(f"📊 Taille: {file_size:.1f} KB")
    print(f"🔑 API Key: {API_KEY[:15]}...")
    print()
    
    # Test 1: Vérifier que l'API répond
    print("1️⃣  Test connexion API...")
    try:
        r = requests.get(
            "https://api.elevenlabs.io/v1/models",
            headers={"xi-api-key": API_KEY},
            timeout=10
        )
        print(f"   Status: {r.status_code}")
        if r.status_code == 200:
            models = r.json()
            print(f"   ✅ API accessible ({len(models)} modèles)")
        else:
            print(f"   ❌ Erreur: {r.text[:200]}")
            return
    except Exception as e:
        print(f"   ❌ Erreur connexion: {e}")
        return
    
    # Test 2: Envoyer le fichier audio
    print()
    print("2️⃣  Envoi du fichier à Scribe v2...")
    
    url = "https://api.elevenlabs.io/v1/speech-to-text"
    headers = {"xi-api-key": API_KEY}
    
    start = time.time()
    
    with open(path, "rb") as f:
        files = {"file": (path.name, f, "audio/mpeg")}
        data = {
            "model_id": "scribe_v2",
            "timestamps_granularity": "word",
            "tag_audio_events": "true"
        }
        
        print(f"   ⏳ Upload en cours...", flush=True)
        
        try:
            # Timeout long: 60s connect, 300s read
            r = requests.post(
                url, 
                headers=headers, 
                files=files, 
                data=data,
                timeout=(60, 300)
            )
            elapsed = time.time() - start
            
            print(f"   ⏱️  Temps: {elapsed:.1f}s")
            print(f"   📡 Status: {r.status_code}")
            
            if r.status_code == 200:
                result = r.json()
                print(f"\n✅ SUCCÈS!")
                print(f"   Langue: {result.get('language_code')}")
                print(f"   Texte: {result.get('text', '')[:100]}...")
                
                words = result.get("words", [])
                print(f"   Mots: {len(words)}")
                
                if words:
                    print(f"\n   Premiers mots:")
                    for w in words[:5]:
                        print(f"      [{w['start']:.2f}-{w['end']:.2f}] {w['text']}")
                
                # Sauvegarder le JSON
                import json
                out_path = path.with_suffix(".scribe.json")
                with open(out_path, "w") as f:
                    json.dump(result, f, indent=2, ensure_ascii=False)
                print(f"\n   📄 JSON sauvé: {out_path}")
                
            else:
                print(f"\n❌ ERREUR API:")
                try:
                    error = r.json()
                    print(f"   {error}")
                except:
                    print(f"   {r.text[:500]}")
                    
        except requests.exceptions.Timeout:
            elapsed = time.time() - start
            print(f"\n❌ TIMEOUT après {elapsed:.1f}s")
            
        except Exception as e:
            elapsed = time.time() - start
            print(f"\n❌ Erreur après {elapsed:.1f}s: {e}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python test_scribe_minimal.py <audio.mp3>")
        sys.exit(1)
    
    test_scribe(sys.argv[1])