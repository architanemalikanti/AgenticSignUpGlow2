#!/usr/bin/env python3
"""
Migration script to create fashion-related tables: outfits, outfit_products, and user_progress
Matches the schema from product_retrival_computer_vision/fashion-feed/backend/database/database_schema.sql

Usage: python migrations/create_fashion_tables.py
"""

from database.db import engine
from sqlalchemy import text
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def create_fashion_tables():
    """Create outfits, outfit_products, and user_progress tables (matching SQL schema)"""

    with engine.connect() as connection:
        # Start transaction
        trans = connection.begin()

        try:
            # Create outfits table (hardcoded outfits)
            logger.info("Creating 'outfits' table...")
            connection.execute(text("""
                CREATE TABLE IF NOT EXISTS outfits (
                    id VARCHAR(36) PRIMARY KEY,
                    base_title TEXT NOT NULL,
                    image_url TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """))
            logger.info("✅ 'outfits' table created successfully")

            # Create outfit_products table (cached outfit products computed via CV model)
            logger.info("Creating 'outfit_products' table...")
            connection.execute(text("""
                CREATE TABLE IF NOT EXISTS outfit_products (
                    id VARCHAR(36) PRIMARY KEY,
                    outfit_id VARCHAR(36) NOT NULL REFERENCES outfits(id) ON DELETE CASCADE,
                    product_name TEXT NOT NULL,
                    brand TEXT NOT NULL,
                    retailer TEXT,
                    price_display TEXT NOT NULL,
                    price_value_usd TEXT NOT NULL,
                    product_image_url TEXT NOT NULL,
                    product_url TEXT,
                    rank TEXT NOT NULL,
                    computed_at TIMESTAMP DEFAULT NOW()
                )
            """))
            logger.info("✅ 'outfit_products' table created successfully")

            # Create user_progress table (track where each user left off)
            logger.info("Creating 'user_progress' table...")
            connection.execute(text("""
                CREATE TABLE IF NOT EXISTS user_progress (
                    user_id VARCHAR(36) PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                    current_outfit_id VARCHAR(36) NOT NULL REFERENCES outfits(id),
                    last_viewed_at TIMESTAMP DEFAULT NOW()
                )
            """))
            logger.info("✅ 'user_progress' table created successfully")

            # Create indexes for better query performance
            logger.info("Creating indexes...")
            connection.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_outfits_created_at ON outfits(created_at);
                CREATE INDEX IF NOT EXISTS idx_outfit_products_outfit_id ON outfit_products(outfit_id);
            """))
            logger.info("✅ Indexes created successfully")

            # Commit transaction
            trans.commit()
            logger.info("🎉 All fashion tables created successfully!")

        except Exception as e:
            # Rollback on error
            trans.rollback()
            logger.error(f"❌ Error creating tables: {e}")
            raise


if __name__ == "__main__":
    logger.info("🚀 Starting fashion tables migration...")
    create_fashion_tables()
    logger.info("✨ Migration complete!")
