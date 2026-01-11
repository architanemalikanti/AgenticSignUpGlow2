#!/usr/bin/env python3
"""
Migration: Create brands table
Usage: python migrations/create_brands_table.py
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


def create_brands_table():
    """Create brands table"""

    with engine.connect() as connection:
        trans = connection.begin()

        try:
            logger.info("Creating 'brands' table...")
            connection.execute(text("""
                CREATE TABLE IF NOT EXISTS brands (
                    id VARCHAR(36) PRIMARY KEY,
                    name VARCHAR(200) NOT NULL UNIQUE,
                    description VARCHAR(500),
                    price_range VARCHAR(50),
                    style_tags TEXT[],
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """))

            trans.commit()
            logger.info("✅ Successfully created brands table!")

        except Exception as e:
            trans.rollback()
            logger.error(f"❌ Error creating brands table: {e}")
            raise


if __name__ == "__main__":
    logger.info("🚀 Starting migration: create brands table...")
    create_brands_table()
    logger.info("✨ Migration complete!")
