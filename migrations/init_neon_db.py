#!/usr/bin/env python3
"""
Initialize Neon database with all tables
Creates all tables based on current SQLAlchemy models (cleaned up - no posts, designs, etc.)

Usage: python migrations/init_neon_db.py
"""
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from database.db import engine, Base
from database.models import (
    User, Follow, FollowRequest, Notification, Report, Block,
    Outfit, OutfitProduct, UserProgress, OutfitTryOnSignup, UserOutfit,
    Brand, UserBrand
)
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def init_database():
    """Create all tables from SQLAlchemy models"""

    logger.info("🚀 Starting Neon database initialization...")

    try:
        # Create all tables
        logger.info("📋 Creating tables...")
        Base.metadata.create_all(bind=engine)

        logger.info("✅ All tables created successfully!")

        # Print created tables
        logger.info("\n📋 Created tables:")
        for table in Base.metadata.sorted_tables:
            logger.info(f"   - {table.name}")

        logger.info("\n🎉 Database initialization complete!")

    except Exception as e:
        logger.error(f"❌ Error creating tables: {e}")
        raise


if __name__ == "__main__":
    init_database()
