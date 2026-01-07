#!/usr/bin/env python3
"""
Migration: Create user_outfits table
Usage: python migrations/create_user_outfits_table.py
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


def create_user_outfits_table():
    """Create user_outfits table"""

    with engine.connect() as connection:
        trans = connection.begin()

        try:
            logger.info("Creating user_outfits table...")
            connection.execute(text("""
                CREATE TABLE IF NOT EXISTS user_outfits (
                    id VARCHAR(36) PRIMARY KEY,
                    user_id VARCHAR(36) NOT NULL REFERENCES users(id),
                    outfit_id VARCHAR(36) NOT NULL REFERENCES outfits(id),
                    saved_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

                    -- Prevent duplicate saves (user can only save same outfit once)
                    UNIQUE(user_id, outfit_id)
                );
            """))

            # Create index for faster lookups
            logger.info("Creating indexes...")
            connection.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_user_outfits_user_id
                ON user_outfits(user_id);
            """))

            connection.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_user_outfits_outfit_id
                ON user_outfits(outfit_id);
            """))

            trans.commit()
            logger.info("✅ Successfully created user_outfits table!")

        except Exception as e:
            trans.rollback()
            logger.error(f"❌ Error creating user_outfits table: {e}")
            raise


if __name__ == "__main__":
    logger.info("🚀 Starting migration: create user_outfits table...")
    create_user_outfits_table()
    logger.info("✨ Migration complete!")
