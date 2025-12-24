"""
Migration: Add follower_sentence field to users table
Date: 2025-12-23
Description: Adds a column to store AI-generated follower/following sentence for each user

Usage:
    python migrations/add_follower_sentence.py
"""

from sqlalchemy import text
from database.db import SessionLocal, engine
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


def run_migration():
    """Add follower_sentence column to users table"""

    db = SessionLocal()

    try:
        logger.info("🔄 Starting migration: add follower_sentence to users table")

        # Check if column already exists
        check_query = text("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'users' AND column_name = 'follower_sentence'
        """)

        result = db.execute(check_query).fetchone()

        if result:
            logger.warning("⚠️  Column 'follower_sentence' already exists. Skipping migration.")
            return

        # Add the column
        logger.info("➕ Adding follower_sentence column...")
        alter_query = text("""
            ALTER TABLE users
            ADD COLUMN follower_sentence VARCHAR(500)
        """)
        db.execute(alter_query)
        db.commit()

        logger.info("✅ Successfully added follower_sentence column")

        # Verify the column was added
        verify_query = text("""
            SELECT column_name, data_type, character_maximum_length, is_nullable
            FROM information_schema.columns
            WHERE table_name = 'users' AND column_name = 'follower_sentence'
        """)

        verification = db.execute(verify_query).fetchone()

        if verification:
            logger.info(f"✅ Verification successful:")
            logger.info(f"   Column: {verification[0]}")
            logger.info(f"   Type: {verification[1]}")
            logger.info(f"   Max Length: {verification[2]}")
            logger.info(f"   Nullable: {verification[3]}")
        else:
            logger.error("❌ Verification failed: Column not found after migration")

    except Exception as e:
        logger.error(f"❌ Migration failed: {e}")
        db.rollback()
        raise
    finally:
        db.close()
        logger.info("🔚 Migration script completed")


if __name__ == "__main__":
    run_migration()
