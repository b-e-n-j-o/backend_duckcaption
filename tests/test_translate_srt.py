"""
Test de traduction SRT via le router /api/transcription/translate.

Pipeline réel:
  srt local → job + Storage → POST /translate/{job_id}
  → srt_translator_v2 (method=strict) → URLs persistées dans duck.jobs.translations

Usage:
  cd backend
  python tests/test_translate_srt.py tests/audios/001.srt --langs en
  python tests/test_translate_srt.py tests/audios/001.srt --langs en,nl --method strict
  python tests/test_translate_srt.py --job-id <uuid> --langs en
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import requests

# Permet d'importer core.* quand on lance depuis backend/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.jobs import create_job, update_job, get_job
from core.supabase import upload_file

API = "http://127.0.0.1:8000/api/transcription"


def setup_job_from_srt(srt_path: Path) -> str:
    """Crée un job, upload le SRT sur Storage, marque srt_ready."""
    print("=" * 60)
    print("📤 [1/4] Création job + upload SRT...")
    t0 = time.time()

    job = create_job(srt_path.name)
    job_id = job["id"]
    print(f"   ✔ job_id: {job_id}")

    dest = f"{job_id}/{srt_path.stem}_source.srt"
    srt_url = upload_file(str(srt_path), dest)
    update_job(
        job_id,
        srt_url=srt_url,
        status="srt_ready",
        language="fra",
        engine="manual_srt_test",
    )
    print(f"   ✔ srt_url: {srt_url}")
    print(f"   ⏱ {time.time() - t0:.1f}s")
    return job_id


def preview_srt(content: str, max_lines: int = 8) -> None:
    lines = content.strip().splitlines()
    print(f"   ✔ lignes: {len(lines)}")
    print("   ── Aperçu ──")
    for line in lines[:max_lines]:
        print(f"      {line}")
    if len(lines) > max_lines:
        print("      ...")


def main() -> None:
    parser = argparse.ArgumentParser(description="Test traduction SRT (pipeline API)")
    parser.add_argument(
        "srt_file",
        nargs="?",
        default=None,
        help="Chemin vers un fichier SRT local",
    )
    parser.add_argument("--job-id", default=None, help="Réutiliser un job existant (avec srt_url)")
    parser.add_argument("--langs", default="en", help="Langues cibles séparées par virgule (ex: en,nl)")
    parser.add_argument(
        "--method",
        default="strict",
        choices=["strict", "classic"],
        help="strict = srt_translator_v2 | classic = ancien translator",
    )
    parser.add_argument("--max-words", type=int, default=None)
    parser.add_argument("--max-chars", type=int, default=None)
    args = parser.parse_args()

    languages = [lang.strip() for lang in args.langs.split(",") if lang.strip()]
    if not languages:
        print("❌ Aucune langue fournie")
        sys.exit(1)

    t_total = time.time()

    # ─── Setup job ───────────────────────────────────────────────
    if args.job_id:
        job_id = args.job_id
        print("=" * 60)
        print(f"♻️  [1/4] Réutilisation job {job_id}")
        job = get_job(job_id)
        if not job or not job.get("srt_url"):
            print("❌ Job introuvable ou sans srt_url")
            sys.exit(1)
        print(f"   ✔ srt_url: {job['srt_url']}")
    elif args.srt_file:
        srt_path = Path(args.srt_file).expanduser().resolve()
        if not srt_path.exists():
            print(f"❌ Fichier introuvable: {srt_path}")
            sys.exit(1)
        print("=" * 60)
        print(f"📄 SRT source: {srt_path}")
        preview_srt(srt_path.read_text(encoding="utf-8"))
        job_id = setup_job_from_srt(srt_path)
    else:
        print("Usage: python test_translate_srt.py <srt_path> [--langs en] ou --job-id <uuid>")
        sys.exit(1)

    # ─── Job avant traduction ────────────────────────────────────
    print("\n📋 [2/4] Job avant traduction...")
    job_before = get_job(job_id)
    print(f"   status:       {job_before.get('status')}")
    print(f"   language:     {job_before.get('language')}")
    print(f"   cost_usd:     ${job_before.get('cost_usd')}")
    print(f"   translations: {job_before.get('translations')}")

    # ─── Translate via API ───────────────────────────────────────
    print(f"\n🌍 [3/4] Traduction API (method={args.method}, langs={languages})...")
    t0 = time.time()
    payload = {
        "languages": languages,
        "method": args.method,
    }
    if args.max_words is not None:
        payload["max_words"] = args.max_words
    if args.max_chars is not None:
        payload["max_chars"] = args.max_chars

    resp = requests.post(f"{API}/translate/{job_id}", json=payload, timeout=300)
    elapsed = time.time() - t0

    if resp.status_code != 200:
        print(f"   ❌ ERREUR {resp.status_code}: {resp.text}")
        sys.exit(1)

    data = resp.json()
    translations = data.get("translations") or {}
    print(f"   ✔ langues traduites: {list(translations.keys())}")
    for lang, url in translations.items():
        print(f"   ✔ {lang}: {url}")
        try:
            srt_translated = requests.get(url, timeout=30).text
            print(f"   ── Aperçu {lang} ──")
            preview_srt(srt_translated)
        except Exception as e:
            print(f"   ⚠ Impossible de télécharger {lang}: {e}")
    print(f"   ⏱ {elapsed:.1f}s")

    # ─── Job final (persisté en base) ────────────────────────────
    print("\n📋 [4/4] Job final (base)...")
    job = get_job(job_id)
    raw_translations = job.get("translations")
    if isinstance(raw_translations, str) and raw_translations.strip():
        try:
            parsed = json.loads(raw_translations)
        except Exception:
            parsed = raw_translations
    else:
        parsed = raw_translations

    print(f"   status:           {job.get('status')}")
    print(f"   language:         {job.get('language')}")
    print(f"   engine:           {job.get('engine')}")
    print(f"   audio_duration:   {job.get('audio_duration_sec')}")
    print(f"   cost_usd:         ${job.get('cost_usd')}")
    print(f"   translations:     {json.dumps(parsed, ensure_ascii=False, indent=2) if isinstance(parsed, dict) else parsed}")
    if job.get("error"):
        print(f"   ⚠ error:         {job['error']}")

    print("\n" + "=" * 60)
    print(f"🎉 Test traduction terminé en {time.time() - t_total:.1f}s")
    print(f"   Job: {job_id}")
    print("=" * 60)


if __name__ == "__main__":
    main()
