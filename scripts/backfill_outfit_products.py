#!/usr/bin/env python3
"""
Backfill products for existing outfits that don't have products cached

Usage:
  python scripts/backfill_outfit_products.py              # Only process outfits without products
  python scripts/backfill_outfit_products.py --force-all  # Re-process ALL outfits (clears existing)
"""

from database.db import SessionLocal
from database.models import Outfit, OutfitProduct
from api.outfit_endpoints import analyze_outfit_and_cache_products
import logging
import asyncio

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def backfill_products(force_all=False):
    """Analyze all outfits that don't have products and cache them"""

    db = SessionLocal()

    try:
        # Get all outfits
        all_outfits = db.query(Outfit).all()
        logger.info(f"📊 Total outfits in database: {len(all_outfits)}")

        if force_all:
            # Clear ALL existing products
            logger.info(f"🗑️ Force mode: Clearing all existing products...")
            deleted_count = db.query(OutfitProduct).delete()
            db.commit()
            logger.info(f"✅ Deleted {deleted_count} existing products")

            outfits_to_process = all_outfits
            logger.info(f"🔄 Will re-process ALL {len(outfits_to_process)} outfits")
        else:
            # Find outfits without products
            outfits_to_process = []
            for outfit in all_outfits:
                product_count = db.query(OutfitProduct).filter(
                    OutfitProduct.outfit_id == outfit.id
                ).count()

                if product_count == 0:
                    outfits_to_process.append(outfit)

            logger.info(f"🔍 Found {len(outfits_to_process)} outfits without products")

            if len(outfits_to_process) == 0:
                logger.info("✨ All outfits already have products!")
                return

        # Analyze each outfit
        for i, outfit in enumerate(outfits_to_process, 1):
            logger.info(f"\n[{i}/{len(outfits_to_process)}] Processing: {outfit.base_title}")
            logger.info(f"   ID: {outfit.id}")
            logger.info(f"   Image: {outfit.image_url[:80]}...")

            try:
                await analyze_outfit_and_cache_products(outfit.id, outfit.image_url)
                logger.info(f"   ✅ Products cached successfully")
            except Exception as e:
                logger.error(f"   ❌ Error analyzing outfit: {e}")
                continue

        logger.info(f"\n🎉 Backfill complete!")
        logger.info(f"   Processed: {len(outfits_to_process)} outfits")

    except Exception as e:
        logger.error(f"❌ Error during backfill: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Backfill products for outfits")
    parser.add_argument(
        '--force-all',
        action='store_true',
        help='Re-process ALL outfits (clears existing products first)'
    )
    args = parser.parse_args()

    if args.force_all:
        logger.info("🚀 Starting FULL reprocessing of ALL outfits (force mode)...")
    else:
        logger.info("🚀 Starting product backfill for outfits without products...")

    asyncio.run(backfill_products(force_all=args.force_all))
    logger.info("✨ All done!")
