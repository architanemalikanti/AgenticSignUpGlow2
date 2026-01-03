#!/usr/bin/env python3
"""
Migration: Add gender column to outfits table
Usage: python migrations/add_gender_to_outfits.py
"""

from database.db import engine
from sqlalchemy import text
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def add_gender_column():
    """Add gender column to outfits table"""

    with engine.connect() as connection:
        trans = connection.begin()

        try:
            logger.info("Adding 'gender' column to outfits table...")
            connection.execute(text("""
                ALTER TABLE outfits
                ADD COLUMN IF NOT EXISTS gender VARCHAR(20);
            """))

            trans.commit()
            logger.info("✅ Successfully added gender column to outfits table!")

        except Exception as e:
            trans.rollback()
            logger.error(f"❌ Error adding gender column: {e}")
            raise


if __name__ == "__main__":
    logger.info("🚀 Starting migration: add gender to outfits...")
    add_gender_column()
    logger.info("✨ Migration complete!")
