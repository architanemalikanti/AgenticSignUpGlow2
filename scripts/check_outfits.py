#!/usr/bin/env python3
"""
Check outfits in database
Usage: python scripts/check_outfits.py
"""

from database.db import SessionLocal
from database.models import Outfit

db = SessionLocal()

try:
    outfits = db.query(Outfit).all()

    print(f"📊 Total outfits in database: {len(outfits)}")
    print()

    if len(outfits) == 0:
        print("❌ No outfits found!")
    else:
        print("✅ Outfits found:")
        print("-" * 80)

        for i, outfit in enumerate(outfits, 1):
            print(f"{i}. ID: {outfit.id}")
            print(f"   Title: {outfit.base_title}")
            print(f"   Gender: {outfit.gender}")
            print(f"   Image: {outfit.image_url[:60]}...")
            print(f"   Created: {outfit.created_at}")
            print()

finally:
    db.close()
