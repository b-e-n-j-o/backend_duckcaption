"""
Test end-to-end du pipeline Scribe v2.

Usage:
  python test_full_flow.py <audio_or_video_path> [--keyterms "terme1,terme2"] [--engine scribe_v2]

Requiert un serveur local sur http://127.0.0.1:8000
"""

import requests
import sys
import time
import argparse

API = "http://127.0.0.1:8000/api/transcription"


def main():
    parser = argparse.ArgumentParser(description="Test full pipeline")
    parser.add_argument("file", help="Chemin vers le fichier audio/vidéo")
    parser.add_argument("--engine", default="scribe_v2", help="Engine: scribe_v2 ou whisper_gemini")
    parser.add_argument("--keyterms", default=None, help="Keyterms séparés par virgule")
    parser.add_argument("--max-chars", type=int, default=None)
    parser.add_argument("--max-words", type=int, default=None)
    parser.add_argument("--max-chars-per-line", type=int, default=42)
    parser.add_argument("--dry-run", action="store_true", help="Ne pas persister en base")
    args = parser.parse_args()

    t_total = time.time()

    # ─── 1. Upload ───────────────────────────────────────────────
    print("=" * 60)
    print("📤 [1/4] Upload...")
    t0 = time.time()
    with open(args.file, "rb") as f:
        resp = requests.post(f"{API}/upload", files={"file": f})
    assert resp.status_code == 200, f"Upload failed: {resp.status_code} {resp.text}"
    data = resp.json()
    job_id = data["job_id"]
    print(f"   ✔ job_id: {job_id}")
    print(f"   ⏱ {time.time() - t0:.1f}s")

    # ─── 2. Audio info ───────────────────────────────────────────
    print("\n📊 [2/4] Audio info...")
    t0 = time.time()
    resp = requests.get(f"{API}/audio_info/{job_id}")
    if resp.status_code == 200:
        info = resp.json()
        print(f"   Durée: {info.get('duration_sec', '?')}s")
        print(f"   Coût estimé: ${info.get('estimated_cost', '?')}")
    else:
        print(f"   ⚠ audio_info indisponible ({resp.status_code})")
    print(f"   ⏱ {time.time() - t0:.1f}s")

    # ─── 3. Generate SRT ─────────────────────────────────────────
    print(f"\n📝 [3/4] Generate SRT (engine={args.engine})...")
    t0 = time.time()
    params = {
        "engine": args.engine,
        "max_chars_per_line": args.max_chars_per_line,
        "dry_run": str(args.dry_run).lower(),
    }
    if args.keyterms:
        params["keyterms"] = args.keyterms
    if args.max_chars:
        params["max_chars"] = args.max_chars
    if args.max_words:
        params["max_words"] = args.max_words

    resp = requests.post(f"{API}/generate_srt/{job_id}", params=params)
    elapsed_srt = time.time() - t0

    if resp.status_code != 200:
        print(f"   ❌ ERREUR {resp.status_code}: {resp.text}")
        sys.exit(1)

    srt_data = resp.json()
    print(f"   ✔ Engine: {srt_data.get('engine')}")
    print(f"   ✔ Langue: {srt_data.get('language')}")
    print(f"   ✔ Filename: {srt_data.get('filename')}")
    if srt_data.get("srt_url"):
        print(f"   ✔ SRT URL: {srt_data['srt_url']}")
    if srt_data.get("srt"):
        lines = srt_data["srt"].strip().split("\n")
        print(f"   ✔ SRT lignes: {len(lines)}")
        print(f"   ── Aperçu (5 premières lignes) ──")
        for l in lines[:5]:
            print(f"      {l}")
    print(f"   ⏱ {elapsed_srt:.1f}s")

    # ─── 4. Job status final ─────────────────────────────────────
    print("\n📋 [4/4] Job status final...")
    resp = requests.get(f"{API}/job/{job_id}")
    if resp.status_code == 200:
        job = resp.json()
        print(f"   status:           {job.get('status')}")
        print(f"   engine:           {job.get('engine')}")
        print(f"   language:         {job.get('language')}")
        print(f"   audio_duration:   {job.get('audio_duration_sec')}s")
        print(f"   segments_count:   {job.get('segments_count')}")
        print(f"   words_count:      {job.get('words_count')}")
        print(f"   cost_usd:         ${job.get('cost_usd')}")
        print(f"   keyterms:         {job.get('keyterms')}")
        if job.get("error"):
            print(f"   ⚠ error:         {job['error']}")
    else:
        print(f"   ⚠ Impossible de récupérer le job ({resp.status_code})")

    # ─── Résumé ──────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print(f"🎉 Test terminé en {time.time() - t_total:.1f}s")
    print(f"   Job: {job_id}")
    print("=" * 60)


if __name__ == "__main__":
    main()
