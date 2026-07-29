"""
Test local : transcription puis traduction (2 jobs séparés).

Flux:
  upload MP3 → generate_srt (job A transcription)
  → translate/{job_id} crée job B (translation_only, parent_job_id=A)

Usage:
  cd backend
  # serveur local requis sur :8000
  python tests/test_transcription_puis_traduction.py
  python tests/test_transcription_puis_traduction.py --keyterms "lasseno,bruxelles" --langs en
  python tests/test_transcription_puis_traduction.py --base-url https://backend-duckcaption.onrender.com
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import requests

DEFAULT_MP3 = Path(__file__).resolve().parent / "audios" / "001.mp3"
DEFAULT_API = "http://127.0.0.1:8000/api/transcription"


def preview_srt(content: str, max_lines: int = 8) -> None:
    lines = content.strip().splitlines()
    print(f"   ✔ lignes: {len(lines)}")
    print("   ── Aperçu ──")
    for line in lines[:max_lines]:
        print(f"      {line}")
    if len(lines) > max_lines:
        print("      ...")


def main() -> None:
    parser = argparse.ArgumentParser(description="Transcription puis traduction")
    parser.add_argument("--mp3", type=Path, default=DEFAULT_MP3)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--engine", default="scribe_v2")
    parser.add_argument("--keyterms", default=None)
    parser.add_argument("--langs", default="en")
    parser.add_argument("--method", default="strict", choices=["strict", "classic"])
    args = parser.parse_args()

    api = f"{args.base_url.rstrip('/')}/api/transcription"
    languages = [x.strip() for x in args.langs.split(",") if x.strip()]
    mp3 = args.mp3.expanduser().resolve()
    if not mp3.exists():
        print(f"❌ MP3 introuvable: {mp3}")
        sys.exit(1)

    t_total = time.time()
    print("=" * 60)
    print(f"🌐 API: {api}")
    print(f"📁 MP3: {mp3}")
    print(f"🌍 Langues: {languages} | method={args.method} | engine={args.engine}")
    print("=" * 60)

    # ─── 1. Upload ───────────────────────────────────────────────
    print("\n📤 [1/5] Upload...")
    t0 = time.time()
    with open(mp3, "rb") as f:
        resp = requests.post(f"{api}/upload", files={"file": (mp3.name, f)}, timeout=120)
    if resp.status_code != 200:
        print(f"   ❌ {resp.status_code} {resp.text}")
        sys.exit(1)
    job_id = resp.json()["job_id"]
    print(f"   ✔ job_id: {job_id}")
    print(f"   ⏱ {time.time() - t0:.1f}s")

    # ─── 2. Audio info ───────────────────────────────────────────
    print("\n📊 [2/5] Audio info...")
    t0 = time.time()
    resp = requests.get(f"{api}/audio_info/{job_id}", timeout=120)
    if resp.status_code == 200:
        info = resp.json()
        print(f"   durée: {info.get('duration_sec')}s | coût estimé: ${info.get('estimated_cost')}")
    else:
        print(f"   ⚠ {resp.status_code}")
    print(f"   ⏱ {time.time() - t0:.1f}s")

    # ─── 3. Transcription ────────────────────────────────────────
    print(f"\n📝 [3/5] Transcription ({args.engine})...")
    t0 = time.time()
    params = {"engine": args.engine}
    if args.keyterms:
        params["keyterms"] = args.keyterms
    resp = requests.post(f"{api}/generate_srt/{job_id}", params=params, timeout=600)
    if resp.status_code != 200:
        print(f"   ❌ {resp.status_code} {resp.text}")
        sys.exit(1)
    srt = resp.json()
    print(f"   ✔ language: {srt.get('language')}")
    print(f"   ✔ filename: {srt.get('filename')}")
    print(f"   ✔ srt_url:  {srt.get('srt_url')}")
    print(f"   ⏱ {time.time() - t0:.1f}s")

    print("\n📋 Job après transcription...")
    job = requests.get(f"{api}/job/{job_id}", timeout=60).json()
    print(f"   status={job.get('status')} engine={job.get('engine')} "
          f"duration={job.get('audio_duration_sec')}s "
          f"segments={job.get('segments_count')} words={job.get('words_count')} "
          f"cost=${job.get('cost_usd')} keyterms={job.get('keyterms')}")
    print(f"   translations (avant): {job.get('translations')}")

    # ─── 4. Traduction (NOUVEAU job dédié) ────────────────────────
    print(f"\n🌍 [4/5] Traduction → nouveau job dédié ({languages})...")
    t0 = time.time()
    payload = {"languages": languages, "method": args.method}
    resp = requests.post(f"{api}/translate/{job_id}", json=payload, timeout=600)
    if resp.status_code != 200:
        print(f"   ❌ {resp.status_code} {resp.text}")
        sys.exit(1)
    data = resp.json()
    translation_job_id = data.get("job_id")
    source_job_id = data.get("source_job_id", job_id)
    translations = data.get("translations") or {}
    print(f"   ✔ source_job_id (transcription): {source_job_id}")
    print(f"   ✔ job_id (traduction):           {translation_job_id}")
    print(f"   ✔ langues: {list(translations.keys())}")
    for lang, url in translations.items():
        print(f"   ✔ {lang}: {url}")
        try:
            preview_srt(requests.get(url, timeout=60).text)
        except Exception as e:
            print(f"   ⚠ download {lang}: {e}")
    print(f"   ⏱ {time.time() - t0:.1f}s")

    # ─── 5. Deux jobs en base ────────────────────────────────────
    print("\n📋 [5/5] Vérification séparation en base...")

    print("\n   ── Job TRANSCRIPTION ──")
    job_src = requests.get(f"{api}/job/{source_job_id}", timeout=60).json()
    print(f"   id:               {job_src.get('id')}")
    print(f"   status:           {job_src.get('status')}")
    print(f"   engine:           {job_src.get('engine')}")
    print(f"   language:         {job_src.get('language')}")
    print(f"   audio_duration:   {job_src.get('audio_duration_sec')}s")
    print(f"   cost_usd:         ${job_src.get('cost_usd')}")
    print(f"   srt_url:          {job_src.get('srt_url')}")
    print(f"   translations:     {job_src.get('translations')}  ← doit rester null")

    print("\n   ── Job TRADUCTION ──")
    job_tr = requests.get(f"{api}/job/{translation_job_id}", timeout=60).json()
    raw = job_tr.get("translations")
    if isinstance(raw, str) and raw.strip():
        try:
            raw = json.loads(raw)
        except Exception:
            pass
    print(f"   id:               {job_tr.get('id')}")
    print(f"   status:           {job_tr.get('status')}")
    print(f"   engine:           {job_tr.get('engine')}")
    print(f"   parent_job_id:    {job_tr.get('parent_job_id')}")
    print(f"   cost_usd:         ${job_tr.get('cost_usd')}")
    print(f"   srt_url (source): {job_tr.get('srt_url')}")
    print(f"   translations:     {json.dumps(raw, ensure_ascii=False, indent=2) if isinstance(raw, dict) else raw}")

    print("\n" + "=" * 60)
    print(f"🎉 Terminé en {time.time() - t_total:.1f}s")
    print(f"   Transcription: {source_job_id}")
    print(f"   Traduction:    {translation_job_id}")
    print("   ℹ 2 lignes séparées en base")
    print("=" * 60)


if __name__ == "__main__":
    main()
