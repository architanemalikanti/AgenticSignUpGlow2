#!/usr/bin/env python3
"""
Bulk import outfits from Firebase Storage
- Fetches images from Firebase Storage
- Uses Claude VLM to generate outfit titles
- Saves to Postgres database

Usage: python scripts/bulk_import_outfits_from_firebase.py
"""

import os
import uuid
import base64
import requests
from pathlib import Path
from anthropic import Anthropic
from database.db import SessionLocal
from database.models import Outfit
import firebase_admin
from firebase_admin import credentials, storage
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize Anthropic
anthropic_client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

# Initialize Firebase
def init_firebase():
    """Initialize Firebase Admin SDK"""
    # Path to your Firebase service account key JSON
    cred_path = os.getenv("FIREBASE_CREDENTIALS_PATH", "./firebase-credentials.json")

    if not os.path.exists(cred_path):
        logger.error(f"❌ Firebase credentials not found at {cred_path}")
        logger.info("💡 Set FIREBASE_CREDENTIALS_PATH env var or place credentials at ./firebase-credentials.json")
        return None

    try:
        cred = credentials.Certificate(cred_path)
        firebase_admin.initialize_app(cred, {
            'storageBucket': os.getenv("FIREBASE_STORAGE_BUCKET")  # e.g., "your-app.appspot.com"
        })
        logger.info("✅ Firebase initialized successfully")
        return storage.bucket()
    except Exception as e:
        logger.error(f"❌ Error initializing Firebase: {e}")
        return None


def generate_outfit_title_with_vlm(image_url: str) -> str:
    """
    Args:
        image_url: Public URL of the outfit image

    Returns:
        Generated title string (e.g., "1999 celeb caught by paparazzi")
    """
    try:
        # Download image data
        response = requests.get(image_url, timeout=10)
        response.raise_for_status()
        image_data = base64.standard_b64encode(response.content).decode("utf-8")

        # Determine media type from URL
        if image_url.lower().endswith('.png'):
            media_type = "image/png"
        elif image_url.lower().endswith('.webp'):
            media_type = "image/webp"
        else:
            media_type = "image/jpeg"

        # Ask Claude to generate a catchy title
        prompt = """think like an editorialist at Vogue: name the moment, not the outfit. 
Use Claude VLM to analyze outfit image and name the moment. 

here are pattens you can use:
Time → “south indian princess at golden hour”, “pop star seen slipping out at midnight” 

Social context, imagine what's happening in the scene → “1999 it girl caught by the paparazzi”

"the nyc darling", "rich girls in paris at 7am", "the it girl, 11pm" are other examples setting the scene. 


keep the text lowercase, no full sentences. 

Return ONLY the title, nothing else."""

        message = anthropic_client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=100,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": image_data,
                            },
                        },
                        {
                            "type": "text",
                            "text": prompt
                        }
                    ],
                }
            ],
        )

        title = message.content[0].text.strip().strip('"').strip("'")
        logger.info(f"✨ Generated title: {title}")
        return title

    except Exception as e:
        logger.error(f"❌ Error generating title with VLM: {e}")
        return "Fashion outfit"  # Fallback title


def bulk_import_outfits(bucket, folder_path: str = "outfits/"):
    """
    Import all outfits from Firebase Storage folder

    Args:
        bucket: Firebase storage bucket
        folder_path: Path to folder containing outfit images
    """
    db = SessionLocal()

    try:
        # List all images in the folder
        blobs = bucket.list_blobs(prefix=folder_path)

        imported_count = 0
        skipped_count = 0

        for blob in blobs:
            # Skip non-image files
            if not any(blob.name.lower().endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.webp']):
                logger.info(f"⏭️ Skipping non-image file: {blob.name}")
                continue

            # Get public URL
            blob.make_public()
            image_url = blob.public_url

            logger.info(f"📸 Processing: {blob.name}")

            # Check if outfit already exists (by image URL)
            existing = db.query(Outfit).filter(Outfit.image_url == image_url).first()
            if existing:
                logger.info(f"⏭️ Outfit already exists, skipping: {blob.name}")
                skipped_count += 1
                continue

            # Generate title using Claude VLM
            base_title = generate_outfit_title_with_vlm(image_url)

            # Create outfit in database
            outfit = Outfit(
                id=str(uuid.uuid4()),
                base_title=base_title,
                image_url=image_url,
                gender="women"  # Default to women for now
            )

            db.add(outfit)
            db.commit()

            logger.info(f"✅ Imported outfit: {base_title}")
            imported_count += 1

        logger.info(f"\n🎉 Import complete!")
        logger.info(f"   Imported: {imported_count} outfits")
        logger.info(f"   Skipped: {skipped_count} (already exist)")

    except Exception as e:
        db.rollback()
        logger.error(f"❌ Error during bulk import: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    logger.info("🚀 Starting bulk outfit import from Firebase...")

    # Initialize Firebase
    bucket = init_firebase()
    if not bucket:
        logger.error("❌ Failed to initialize Firebase. Exiting.")
        exit(1)

    # Get folder path from env or use default
    folder_path = os.getenv("FIREBASE_OUTFITS_FOLDER", "outfits/")
    logger.info(f"📁 Looking for images in: {folder_path}")

    # Run bulk import
    bulk_import_outfits(bucket, folder_path)

    logger.info("✨ All done!")
