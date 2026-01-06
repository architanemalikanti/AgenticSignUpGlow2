#!/usr/bin/env python3
"""
Migration: Create outfit_tryon_signups table
Usage: python migrations/create_outfit_tryon_signups_table.py
"""

from database.db import engine
from sqlalchemy import text
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def create_outfit_tryon_signups_table():
    """Create outfit_tryon_signups table"""

    with engine.connect() as connection:
        trans = connection.begin()

        try:
            logger.info("Creating outfit_tryon_signups table...")
            connection.execute(text("""
                CREATE TABLE IF NOT EXISTS outfit_tryon_signups (
                    id VARCHAR(36) PRIMARY KEY,
                    user_id VARCHAR(36) NOT NULL UNIQUE REFERENCES users(id),
                    email VARCHAR(120) NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """))

            # Create index on user_id for faster lookups
            logger.info("Creating index on user_id...")
            connection.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_outfit_tryon_signups_user_id
                ON outfit_tryon_signups(user_id);
            """))

            trans.commit()
            logger.info("✅ Successfully created outfit_tryon_signups table!")

        except Exception as e:
            trans.rollback()
            logger.error(f"❌ Error creating outfit_tryon_signups table: {e}")
            raise


if __name__ == "__main__":
    logger.info("🚀 Starting migration: create outfit_tryon_signups table...")
    create_outfit_tryon_signups_table()
    logger.info("✨ Migration complete!")
