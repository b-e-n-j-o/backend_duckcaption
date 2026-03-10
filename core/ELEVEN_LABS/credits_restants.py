#!/usr/bin/env python3
"""
Audit des crédits ElevenLabs

Usage:
    python elevenlabs_credits.py
    
Affiche:
    - Crédits utilisés / max
    - Tier du plan
    - Date de renouvellement
    - Estimation du coût pour Speech-to-Text

Pour Speech-to-Text (Scribe v2):
    - Facturé à la MINUTE d'audio, pas en crédits "caractères"
    - ~$0.33-0.40 par heure selon le plan
    - Les "crédits" affichés dans l'erreur représentent des SECONDES d'audio
    - 45 crédits requis = ~45 secondes d'audio à transcrire
"""

import os
import sys
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
print("ELEVENLABS_API_KEY:", ELEVENLABS_API_KEY)


def get_subscription_info() -> dict:
    """Récupère les infos de subscription via l'API."""
    try:
        from elevenlabs import ElevenLabs
    except ImportError:
        print("❌ Package elevenlabs non installé")
        print("   pip install elevenlabs")
        sys.exit(1)
    
    if not ELEVENLABS_API_KEY:
        print("❌ ELEVENLABS_API_KEY non définie")
        sys.exit(1)
    
    client = ElevenLabs(api_key=ELEVENLABS_API_KEY)
    
    # Récupérer les infos user
    user = client.user.get()
    subscription = client.user.get_subscription()
    
    return {
        "user": user,
        "subscription": subscription
    }


def format_number(n: int) -> str:
    """Formate un nombre avec séparateurs."""
    return f"{n:,}".replace(",", " ")


def main():
    print("\n🔍 Audit des crédits ElevenLabs\n")
    print("=" * 50)
    
    try:
        info = get_subscription_info()
    except Exception as e:
        print(f"❌ Erreur API: {e}")
        sys.exit(1)
    
    sub = info["subscription"]
    
    # Infos de base
    tier = getattr(sub, "tier", "unknown")
    status = getattr(sub, "status", "unknown")
    
    print(f"📋 Plan: {tier}")
    print(f"📊 Status: {status}")
    
    # Crédits caractères (TTS)
    char_used = getattr(sub, "character_count", 0)
    char_max = getattr(sub, "character_limit", 0)
    char_remaining = char_max - char_used
    char_percent = (char_used / char_max * 100) if char_max > 0 else 0
    
    print(f"\n💬 Crédits TTS (caractères):")
    print(f"   Utilisés:  {format_number(char_used)}")
    print(f"   Maximum:   {format_number(char_max)}")
    print(f"   Restants:  {format_number(char_remaining)} ({100-char_percent:.1f}%)")
    
    # Barre de progression
    bar_width = 30
    filled = int(bar_width * char_percent / 100)
    bar = "█" * filled + "░" * (bar_width - filled)
    print(f"   [{bar}] {char_percent:.1f}%")
    
    # Infos billing
    currency = getattr(sub, "currency", "USD")
    billing_period = getattr(sub, "billing_period", "monthly")
    next_invoice = getattr(sub, "next_invoice", None)
    
    print(f"\n💳 Facturation:")
    print(f"   Devise: {currency}")
    print(f"   Période: {billing_period}")
    
    if next_invoice:
        amount = getattr(next_invoice, "amount_due_cents", 0) / 100
        next_date = getattr(next_invoice, "next_payment_attempt_unix", None)
        if next_date:
            dt = datetime.fromtimestamp(next_date)
            print(f"   Prochaine facture: {amount:.2f} {currency} le {dt.strftime('%d/%m/%Y')}")
    
    # Infos Speech-to-Text spécifiques
    print(f"\n🎙️ Speech-to-Text (Scribe v2):")
    print(f"   ⚠️  STT est facturé à la MINUTE, pas en crédits caractères")
    print(f"   💰 Tarif: ~$0.33-0.40 / heure selon le plan")
    print(f"   📝 L'erreur '45 credits required' = ~45 secondes d'audio")
    
    # Estimation
    print(f"\n📊 Estimation pour STT:")
    print(f"   1 min audio  → ~$0.0055-0.0067")
    print(f"   10 min audio → ~$0.055-0.067")
    print(f"   1h audio     → ~$0.33-0.40")
    
    # Voices
    voice_slots = getattr(sub, "voice_slots_used", 0)
    voice_max = getattr(sub, "max_voice_slots", 0)
    print(f"\n🎤 Voices: {voice_slots}/{voice_max} slots utilisés")
    
    print("\n" + "=" * 50)
    print("✅ Audit terminé\n")


if __name__ == "__main__":
    main()