"""
Test end-to-end contre le backend déployé (prod).

1) Transcription Scribe v2 à partir d'un MP3
2) Traduction strict (EN) :
   - du job créé par la transcription
   - + du SRT local via /translate_srt_content

Usage:
  cd backend
  python tests/test_srt_et_trad_en_prod.py
  python tests/test_srt_et_trad_en_prod.py --mp3 tests/audios/001.mp3 --srt tests/audios/001.srt
  python tests/test_srt_et_trad_en_prod.py --keyterms "lasseno,bruxelles"
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import requests

PROD_BASE = "https://backend-duckcaption.onrender.com"
API = f"{PROD_BASE}/api/transcription"

DEFAULT_MP3 = Path(__file__).resolve().parent / "audios" / "001.mp3"
DEFAULT_SRT = Path(__file__).resolve().parent / "audios" / "001.srt"


def preview_srt(content: str, max_lines: int = 8) -> None:
    lines = content.strip().splitlines()
    print(f"   ✔ lignes: {len(lines)}")
    print("   ── Aperçu ──")
    for line in lines[:max_lines]:
        print(f"      {line}")
    if len(lines) > max_lines:
        print("      ...")


def main() -> None:
    parser = argparse.ArgumentParser(description="Test transcription + traduction en prod")
    parser.add_argument("--base-url", default=PROD_BASE, help="URL du backend déployé")
    parser.add_argument("--mp3", type=Path, default=DEFAULT_MP3, help="Fichier audio/vidéo")
    parser.add_argument("--srt", type=Path, default=DEFAULT_SRT, help="Fichier SRT local pour traduction directe")
    parser.add_argument("--engine", default="scribe_v2")
    parser.add_argument("--keyterms", default=None)
    parser.add_argument("--langs", default="en", help="Langues cibles (ex: en,nl)")
    parser.add_argument("--method", default="strict", choices=["strict", "classic"])
    parser.add_argument("--skip-transcription", action="store_true")
    parser.add_argument("--skip-translate-job", action="store_true")
    parser.add_argument("--skip-translate-srt", action="store_true")
    args = parser.parse_args()

    api = f"{args.base_url.rstrip('/')}/api/transcription"
    languages = [x.strip() for x in args.langs.split(",") if x.strip()]
    t_total = time.time()
    job_id = None

    print("=" * 60)
    print(f"🌐 Backend: {args.base_url}")
    print(f"📁 MP3: {args.mp3}")
    print(f"📄 SRT: {args.srt}")
    print("=" * 60)

    # Health check rapide
    try:
        ping = requests.get(args.base_url.rstrip("/") + "/", timeout=30)
        print(f"🏓 Ping: HTTP {ping.status_code}")
    except Exception as e:
        print(f"❌ Backend injoignable: {e}")
        sys.exit(1)

    # ─────────────────────────────────────────────────────────────
    # A) TRANSCRIPTION (MP3 → SRT)
    # ─────────────────────────────────────────────────────────────
    if not args.skip_transcription:
        mp3 = args.mp3.expanduser().resolve()
        if not mp3.exists():
            print(f"❌ MP3 introuvable: {mp3}")
            sys.exit(1)

        print("\n📤 [A1] Upload MP3 (prod)...")
        t0 = time.time()
        with open(mp3, "rb") as f:
            resp = requests.post(f"{api}/upload", files={"file": (mp3.name, f)}, timeout=120)
        if resp.status_code != 200:
            print(f"   ❌ Upload failed: {resp.status_code} {resp.text}")
            sys.exit(1)
        job_id = resp.json()["job_id"]
        print(f"   ✔ job_id: {job_id}")
        print(f"   ⏱ {time.time() - t0:.1f}s")

        print("\n📊 [A2] Audio info...")
        t0 = time.time()
        resp = requests.get(f"{api}/audio_info/{job_id}", timeout=120)
        if resp.status_code == 200:
            info = resp.json()
            print(f"   Durée: {info.get('duration_sec')}s | coût estimé: ${info.get('estimated_cost')}")
        else:
            print(f"   ⚠ audio_info: {resp.status_code} {resp.text[:200]}")
        print(f"   ⏱ {time.time() - t0:.1f}s")

        print(f"\n📝 [A3] Generate SRT (engine={args.engine})...")
        t0 = time.time()
        params = {"engine": args.engine}
        if args.keyterms:
            params["keyterms"] = args.keyterms
        resp = requests.post(f"{api}/generate_srt/{job_id}", params=params, timeout=600)
        if resp.status_code != 200:
            print(f"   ❌ generate_srt failed: {resp.status_code} {resp.text}")
            sys.exit(1)
        srt_data = resp.json()
        print(f"   ✔ engine: {srt_data.get('engine')}")
        print(f"   ✔ language: {srt_data.get('language')}")
        print(f"   ✔ filename: {srt_data.get('filename')}")
        print(f"   ✔ srt_url: {srt_data.get('srt_url')}")
        print(f"   ⏱ {time.time() - t0:.1f}s")

        print("\n📋 [A4] Job après transcription...")
        resp = requests.get(f"{api}/job/{job_id}", timeout=60)
        if resp.status_code == 200:
            job = resp.json()
            print(f"   status:         {job.get('status')}")
            print(f"   engine:         {job.get('engine')}")
            print(f"   language:       {job.get('language')}")
            print(f"   duration:       {job.get('audio_duration_sec')}")
            print(f"   segments:       {job.get('segments_count')}")
            print(f"   words:          {job.get('words_count')}")
            print(f"   keyterms:       {job.get('keyterms')}")
            print(f"   cost_usd:       ${job.get('cost_usd')}")
            if job.get("error"):
                print(f"   ⚠ error:       {job['error']}")
        else:
            print(f"   ⚠ job status: {resp.status_code} {resp.text[:200]}")

        # Traduire le job issu de la transcription
        if not args.skip_translate_job:
            print(f"\n🌍 [A5] Traduction du job (method={args.method}, langs={languages})...")
            t0 = time.time()
            payload = {"languages": languages, "method": args.method}
            resp = requests.post(f"{api}/translate/{job_id}", json=payload, timeout=600)
            if resp.status_code != 200:
                print(f"   ❌ translate failed: {resp.status_code} {resp.text}")
                sys.exit(1)
            translations = resp.json().get("translations") or {}
            print(f"   ✔ langues: {list(translations.keys())}")
            for lang, url in translations.items():
                print(f"   ✔ {lang}: {url}")
                try:
                    content = requests.get(url, timeout=60).text
                    preview_srt(content)
                except Exception as e:
                    print(f"   ⚠ download {lang}: {e}")
            print(f"   ⏱ {time.time() - t0:.1f}s")

            print("\n📋 [A6] Job final après traduction...")
            resp = requests.get(f"{api}/job/{job_id}", timeout=60)
            if resp.status_code == 200:
                job = resp.json()
                raw = job.get("translations")
                if isinstance(raw, str) and raw.strip():
                    try:
                        raw = json.loads(raw)
                    except Exception:
                        pass
                print(f"   status:     {job.get('status')}")
                print(f"   cost_usd:   ${job.get('cost_usd')}")
                print(f"   translations: {json.dumps(raw, ensure_ascii=False, indent=2) if isinstance(raw, dict) else raw}")
            else:
                print(f"   ⚠ job status: {resp.status_code}")

    # ─────────────────────────────────────────────────────────────
    # B) TRADUCTION DIRECTE D'UN SRT LOCAL
    # ─────────────────────────────────────────────────────────────
    if not args.skip_translate_srt:
        srt_path = args.srt.expanduser().resolve()
        if not srt_path.exists():
            print(f"❌ SRT introuvable: {srt_path}")
            sys.exit(1)

        print("\n📄 [B1] Traduction directe SRT local via /translate_srt_content...")
        print(f"   source: {srt_path}")
        srt_content = srt_path.read_text(encoding="utf-8")
        preview_srt(srt_content)

        t0 = time.time()
        payload = {
            "srt": srt_content,
            "languages": languages,
            "method": args.method,
            "filename": srt_path.name,
            "persist": True,
        }
        resp = requests.post(f"{api}/translate_srt_content", json=payload, timeout=600)
        if resp.status_code != 200:
            print(f"   ❌ translate_srt_content failed: {resp.status_code} {resp.text}")
            sys.exit(1)
        data = resp.json()
        print(f"   ✔ method: {data.get('method')}")
        print(f"   ✔ job_id (traduction seule): {data.get('job_id')}")
        print(f"   ✔ srt_url source: {data.get('srt_url')}")
        print(f"   ✔ translation_urls: {data.get('translation_urls')}")
        for lang, translated in (data.get("translations") or {}).items():
            print(f"   ✔ {lang} traduit (contenu)")
            preview_srt(translated)
        print(f"   ⏱ {time.time() - t0:.1f}s")

        if data.get("job_id"):
            print("\n📋 [B2] Job traduction seule (base)...")
            resp = requests.get(f"{api}/job/{data['job_id']}", timeout=60)
            if resp.status_code == 200:
                job = resp.json()
                print(f"   status:   {job.get('status')}")
                print(f"   engine:   {job.get('engine')}")
                print(f"   cost_usd: ${job.get('cost_usd')}")
                print(f"   translations: {job.get('translations')}")
            else:
                print(f"   ⚠ job status: {resp.status_code}")
                print("   (si 404 / colonnes manquantes: redéployer le backend avec la nouvelle logique)")

    print("\n" + "=" * 60)
    print(f"🎉 Test prod terminé en {time.time() - t_total:.1f}s")
    if job_id:
        print(f"   Job transcription/traduction: {job_id}")
        print(f"   Statut: {api}/job/{job_id}")
    print("=" * 60)


if __name__ == "__main__":
    main()
