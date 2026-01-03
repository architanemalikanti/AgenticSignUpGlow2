#!/usr/bin/env python3
"""
Script to add outfits to the database
Usage: python scripts/add_outfits.py
"""

from database.db import SessionLocal
from database.models import Outfit
import uuid

db = SessionLocal()

try:
    # Define your outfits here
    outfits = [
        {
            "id": str(uuid.uuid4()),
            "base_title": "1999 celeb caught by paparazzi",
            "image_url": "https://your-cdn.com/outfit1.jpg",
            "gender": "women"  # "women", "men", or "unisex"
        },
        {
            "id": str(uuid.uuid4()),
            "base_title": "Street style icon NYC",
            "image_url": "https://your-cdn.com/outfit2.jpg",
            "gender": "women"
        },
        {
            "id": str(uuid.uuid4()),
            "base_title": "Y2K throwback vibes",
            "image_url": "https://your-cdn.com/outfit3.jpg",
            "gender": "men"
        },
        # Add more outfits here...
    ]

    # Insert outfits
    for outfit_data in outfits:
        outfit = Outfit(**outfit_data)
        db.add(outfit)

    db.commit()
    print(f"✅ Successfully added {len(outfits)} outfits!")

except Exception as e:
    db.rollback()
    print(f"❌ Error adding outfits: {e}")

finally:
    db.close()
