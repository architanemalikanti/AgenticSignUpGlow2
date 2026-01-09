#!/usr/bin/env python3
"""
Migration: Add caption column to user_outfits table
Usage: python migrations/add_caption_to_user_outfits.py
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from database.db import engine
from sqlalchemy import text
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def add_caption_column():
    """Add caption column to user_outfits table"""

    with engine.connect() as connection:
        trans = connection.begin()

        try:
            logger.info("Adding 'caption' column to user_outfits table...")
            connection.execute(text("""
                ALTER TABLE user_outfits
                ADD COLUMN IF NOT EXISTS caption VARCHAR(500);
            """))

            trans.commit()
            logger.info("✅ Successfully added caption column to user_outfits table!")

        except Exception as e:
            trans.rollback()
            logger.error(f"❌ Error adding caption column: {e}")
            raise


if __name__ == "__main__":
    logger.info("🚀 Starting migration: add caption to user_outfits...")
    add_caption_column()
    logger.info("✨ Migration complete!")
