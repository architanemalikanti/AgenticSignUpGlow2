#!/usr/bin/env python3
"""
Migration: Delete all outfits from database
Usage: python -m migrations.delete_all_outfits
"""

from database.db import SessionLocal
from database.models import Outfit
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def delete_all_outfits():
    """Show all outfits and delete them"""

    db = SessionLocal()

    try:
        # First, show all outfits
        outfits = db.query(Outfit).all()
        logger.info(f"📊 Total outfits in database: {len(outfits)}")

        if len(outfits) == 0:
            logger.info("✨ No outfits to delete!")
            return

        # Show first 10 outfits as preview
        logger.info("\n📸 Preview of outfits (showing first 10):")
        for i, outfit in enumerate(outfits[:10], 1):
            logger.info(f"  {i}. ID: {outfit.id}")
            logger.info(f"     Title: {outfit.base_title}")
            logger.info(f"     Gender: {outfit.gender}")
            logger.info(f"     URL: {outfit.image_url[:80]}...")
            logger.info("")

        if len(outfits) > 10:
            logger.info(f"... and {len(outfits) - 10} more\n")

        # Delete all outfits
        logger.info("🗑️  Deleting all outfits...")
        deleted_count = db.query(Outfit).delete()
        db.commit()

        logger.info(f"✅ Successfully deleted {deleted_count} outfits!")

    except Exception as e:
        db.rollback()
        logger.error(f"❌ Error deleting outfits: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    logger.info("🚀 Starting outfit deletion migration...")
    delete_all_outfits()
    logger.info("✨ Migration complete!")
