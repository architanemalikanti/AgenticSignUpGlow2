#!/usr/bin/env python3
"""
Seed brands table with curated fashion brands
Usage: python scripts/seed_brands.py
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from database.db import SessionLocal
from database.models import Brand
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


FASHION_BRANDS = [
    # Luxury
    {"name": "PRADA", "price_range": "luxury", "style_tags": ["luxury", "minimalist", "sophisticated"]},
    {"name": "Gucci", "price_range": "luxury", "style_tags": ["luxury", "bold", "eclectic"]},
    {"name": "Louis Vuitton", "price_range": "luxury", "style_tags": ["luxury", "classic", "iconic"]},
    {"name": "Chanel", "price_range": "luxury", "style_tags": ["luxury", "timeless", "elegant"]},
    {"name": "Dior", "price_range": "luxury", "style_tags": ["luxury", "romantic", "feminine"]},
    {"name": "Saint Laurent", "price_range": "luxury", "style_tags": ["luxury", "edgy", "rock-and-roll"]},
    {"name": "Bottega Veneta", "price_range": "luxury", "style_tags": ["luxury", "minimalist", "craftsmanship"]},
    {"name": "Balenciaga", "price_range": "luxury", "style_tags": ["luxury", "avant-garde", "streetwear"]},
    {"name": "Celine", "price_range": "luxury", "style_tags": ["luxury", "minimalist", "understated"]},
    {"name": "Hermès", "price_range": "luxury", "style_tags": ["luxury", "classic", "heritage"]},
    {"name": "Valentino", "price_range": "luxury", "style_tags": ["luxury", "romantic", "bold"]},
    {"name": "Versace", "price_range": "luxury", "style_tags": ["luxury", "bold", "glamorous"]},
    {"name": "Fendi", "price_range": "luxury", "style_tags": ["luxury", "playful", "sophisticated"]},
    {"name": "Loewe", "price_range": "luxury", "style_tags": ["luxury", "craftsmanship", "artistic"]},
    {"name": "The Row", "price_range": "luxury", "style_tags": ["luxury", "minimalist", "refined"]},
    {"name": "Loro Piana", "price_range": "luxury", "style_tags": ["luxury", "quiet-luxury", "cashmere"]},
    {"name": "Brunello Cucinelli", "price_range": "luxury", "style_tags": ["luxury", "quiet-luxury", "italian"]},

    # Contemporary/Designer
    {"name": "Jacquemus", "price_range": "mid-range", "style_tags": ["contemporary", "playful", "french"]},
    {"name": "Ganni", "price_range": "mid-range", "style_tags": ["contemporary", "danish", "feminine"]},
    {"name": "Staud", "price_range": "mid-range", "style_tags": ["contemporary", "california", "vintage-inspired"]},
    {"name": "Toteme", "price_range": "mid-range", "style_tags": ["contemporary", "minimalist", "scandinavian"]},
    {"name": "Khaite", "price_range": "mid-range", "style_tags": ["contemporary", "minimalist", "american"]},
    {"name": "Nanushka", "price_range": "mid-range", "style_tags": ["contemporary", "minimalist", "vegan-leather"]},
    {"name": "Acne Studios", "price_range": "mid-range", "style_tags": ["contemporary", "scandinavian", "denim"]},
    {"name": "A.P.C.", "price_range": "mid-range", "style_tags": ["contemporary", "minimalist", "french"]},
    {"name": "Lemaire", "price_range": "mid-range", "style_tags": ["contemporary", "minimalist", "french"]},
    {"name": "Our Legacy", "price_range": "mid-range", "style_tags": ["contemporary", "scandinavian", "menswear"]},

    # Accessible Luxury
    {"name": "Reformation", "price_range": "mid-range", "style_tags": ["sustainable", "feminine", "california"]},
    {"name": "Aritzia", "price_range": "mid-range", "style_tags": ["canadian", "minimalist", "everyday"]},
    {"name": "Sandro", "price_range": "mid-range", "style_tags": ["french", "parisian", "chic"]},
    {"name": "Maje", "price_range": "mid-range", "style_tags": ["french", "feminine", "bohemian"]},
    {"name": "& Other Stories", "price_range": "affordable", "style_tags": ["scandinavian", "trend-forward", "affordable"]},
    {"name": "COS", "price_range": "affordable", "style_tags": ["minimalist", "scandinavian", "affordable"]},
    {"name": "Everlane", "price_range": "affordable", "style_tags": ["basics", "sustainable", "transparent"]},

    # Streetwear/Contemporary
    {"name": "Stüssy", "price_range": "mid-range", "style_tags": ["streetwear", "california", "skate"]},
    {"name": "Carhartt WIP", "price_range": "affordable", "style_tags": ["streetwear", "workwear", "utilitarian"]},
    {"name": "Noah", "price_range": "mid-range", "style_tags": ["streetwear", "sustainable", "prep"]},
    {"name": "Aimé Leon Dore", "price_range": "mid-range", "style_tags": ["streetwear", "preppy", "new-york"]},
    {"name": "Kith", "price_range": "mid-range", "style_tags": ["streetwear", "new-york", "luxury-sportswear"]},
    {"name": "Palace", "price_range": "mid-range", "style_tags": ["streetwear", "skate", "british"]},
    {"name": "Supreme", "price_range": "mid-range", "style_tags": ["streetwear", "skate", "hype"]},

    # Fast Fashion/Affordable
    {"name": "Zara", "price_range": "affordable", "style_tags": ["fast-fashion", "trend-forward", "affordable"]},
    {"name": "H&M", "price_range": "affordable", "style_tags": ["fast-fashion", "basics", "affordable"]},
    {"name": "Uniqlo", "price_range": "affordable", "style_tags": ["basics", "japanese", "affordable"]},
    {"name": "Mango", "price_range": "affordable", "style_tags": ["fast-fashion", "spanish", "affordable"]},

    # Italian/Heritage
    {"name": "Dolce & Gabbana", "price_range": "luxury", "style_tags": ["luxury", "italian", "bold"]},
    {"name": "Prada", "price_range": "luxury", "style_tags": ["luxury", "italian", "intellectual"]},
    {"name": "Miu Miu", "price_range": "luxury", "style_tags": ["luxury", "playful", "feminine"]},
    {"name": "Marni", "price_range": "luxury", "style_tags": ["luxury", "artistic", "colorful"]},
    {"name": "Max Mara", "price_range": "luxury", "style_tags": ["luxury", "italian", "tailoring"]},

    # Avant-Garde
    {"name": "Rick Owens", "price_range": "luxury", "style_tags": ["avant-garde", "dark", "architectural"]},
    {"name": "Comme des Garçons", "price_range": "luxury", "style_tags": ["avant-garde", "japanese", "conceptual"]},
    {"name": "Yohji Yamamoto", "price_range": "luxury", "style_tags": ["avant-garde", "japanese", "poetic"]},
    {"name": "Issey Miyake", "price_range": "luxury", "style_tags": ["avant-garde", "japanese", "pleats"]},
]


def seed_brands():
    """Populate brands table with curated fashion brands"""
    db = SessionLocal()

    try:
        logger.info(f"🌱 Seeding {len(FASHION_BRANDS)} brands...")

        added_count = 0
        skipped_count = 0

        for brand_data in FASHION_BRANDS:
            # Check if brand already exists
            existing = db.query(Brand).filter(Brand.name == brand_data["name"]).first()

            if existing:
                logger.debug(f"⏭️  Brand already exists: {brand_data['name']}")
                skipped_count += 1
                continue

            # Create new brand
            brand = Brand(
                name=brand_data["name"],
                price_range=brand_data["price_range"],
                style_tags=brand_data["style_tags"]
            )
            db.add(brand)
            added_count += 1
            logger.info(f"✨ Added: {brand_data['name']}")

        db.commit()

        logger.info(f"✅ Seeding complete!")
        logger.info(f"   Added: {added_count} brands")
        logger.info(f"   Skipped: {skipped_count} brands (already existed)")
        logger.info(f"   Total: {len(FASHION_BRANDS)} brands in seed data")

    except Exception as e:
        db.rollback()
        logger.error(f"❌ Error seeding brands: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    logger.info("🚀 Starting brand seeding...")
    seed_brands()
    logger.info("✨ Done!")
