#!/usr/bin/env python3
"""
Migration: Create user_brands junction table for many-to-many relationship
Usage: python migrations/create_user_brands_table.py
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


def create_user_brands_table():
    """Create user_brands junction table"""

    with engine.connect() as connection:
        trans = connection.begin()

        try:
            logger.info("Creating 'user_brands' junction table...")
            connection.execute(text("""
                CREATE TABLE IF NOT EXISTS user_brands (
                    id VARCHAR(36) PRIMARY KEY,
                    user_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    brand_id VARCHAR(36) NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(user_id, brand_id)
                );
            """))

            trans.commit()
            logger.info("✅ Successfully created user_brands table!")

        except Exception as e:
            trans.rollback()
            logger.error(f"❌ Error creating user_brands table: {e}")
            raise


if __name__ == "__main__":
    logger.info("🚀 Starting migration: create user_brands junction table...")
    create_user_brands_table()
    logger.info("✨ Migration complete!")
