"""
Test de connexion Supabase
- Vérification des variables .env
- Connexion PostgreSQL (pooler, port 6543)
- Optionnel : test API REST si supabase est installé
"""

#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from dotenv import load_dotenv
load_dotenv()  # DOIT être exécuté avant tout

import os
import sys
import uuid
from datetime import datetime
from supabase import create_client

# -------------------------------------------------------------------
# ENV CHECK
# -------------------------------------------------------------------

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")

print("🔎 ENV CHECK")
print("SUPABASE_URL         =", SUPABASE_URL)
print("SERVICE_ROLE KEY     =", "OK" if SUPABASE_SERVICE_KEY else "❌ MISSING")

if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
    print("❌ Variables d'environnement manquantes")
    sys.exit(1)

# -------------------------------------------------------------------
# CONNECTION
# -------------------------------------------------------------------

print("\n🔌 Connecting to Supabase...")
supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

# -------------------------------------------------------------------
# TEST INSERT
# -------------------------------------------------------------------

job_id = str(uuid.uuid4())

print("\n🧪 TEST INSERT (duck.jobs)")
try:
    res = supabase.schema("duck").table("jobs").insert({
        "id": job_id,
        "filename": "test.mp4",
        "status": "test",
        "created_at": datetime.utcnow().isoformat()
    }).execute()

    print("✅ INSERT OK")
    print(res.data)

except Exception as e:
    print("❌ INSERT FAILED")
    print(e)
    sys.exit(2)

# -------------------------------------------------------------------
# TEST SELECT
# -------------------------------------------------------------------

print("\n🧪 TEST SELECT")
try:
    res = (
        supabase.schema("duck")
        .table("jobs")
        .select("*")
        .eq("id", job_id)
        .single()
        .execute()
    )

    print("✅ SELECT OK")
    print(res.data)

except Exception as e:
    print("❌ SELECT FAILED")
    print(e)
    sys.exit(3)

# -------------------------------------------------------------------
# TEST DELETE (cleanup)
# -------------------------------------------------------------------

print("\n🧪 TEST DELETE")
try:
    supabase.schema("duck").table("jobs").delete().eq("id", job_id).execute()
    print("✅ DELETE OK")

except Exception as e:
    print("❌ DELETE FAILED")
    print(e)
    sys.exit(4)

# -------------------------------------------------------------------

print("\n🎉 SUPABASE CONNECTION TEST OK")
