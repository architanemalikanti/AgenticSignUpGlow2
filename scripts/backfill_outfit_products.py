#!/usr/bin/env python3
"""
Backfill products for existing outfits that don't have products cached

Usage: python scripts/backfill_outfit_products.py
"""

from database.db import SessionLocal
from database.models import Outfit, OutfitProduct
from api.outfit_endpoints import analyze_outfit_and_cache_products
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def backfill_products():
    """Analyze all outfits that don't have products and cache them"""

    db = SessionLocal()

    try:
        # Get all outfits
        all_outfits = db.query(Outfit).all()
        logger.info(f"📊 Total outfits in database: {len(all_outfits)}")

        # Find outfits without products
        outfits_without_products = []
        for outfit in all_outfits:
            product_count = db.query(OutfitProduct).filter(
                OutfitProduct.outfit_id == outfit.id
            ).count()

            if product_count == 0:
                outfits_without_products.append(outfit)

        logger.info(f"🔍 Found {len(outfits_without_products)} outfits without products")

        if len(outfits_without_products) == 0:
            logger.info("✨ All outfits already have products!")
            return

        # Analyze each outfit
        for i, outfit in enumerate(outfits_without_products, 1):
            logger.info(f"\n[{i}/{len(outfits_without_products)}] Processing: {outfit.base_title}")
            logger.info(f"   ID: {outfit.id}")
            logger.info(f"   Image: {outfit.image_url[:80]}...")

            try:
                analyze_outfit_and_cache_products(outfit.id, outfit.image_url)
                logger.info(f"   ✅ Products cached successfully")
            except Exception as e:
                logger.error(f"   ❌ Error analyzing outfit: {e}")
                continue

        logger.info(f"\n🎉 Backfill complete!")
        logger.info(f"   Processed: {len(outfits_without_products)} outfits")

    except Exception as e:
        logger.error(f"❌ Error during backfill: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    logger.info("🚀 Starting product backfill for existing outfits...")
    backfill_products()
    logger.info("✨ All done!")
