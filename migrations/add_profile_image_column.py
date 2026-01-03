"""
Migration script to add profile_image column to existing users table.
Run this on your EC2 server if the users table already exists.

Usage: python add_profile_image_column.py
"""

from database.db import engine
from sqlalchemy import text
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def add_profile_image_column():
    """Add profile_image column to users table."""
    try:
        with engine.connect() as conn:
            # Check if column already exists
            result = conn.execute(text("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name='users' AND column_name='profile_image';
            """))

            if result.fetchone():
                logger.info("⚠️  Column 'profile_image' already exists in users table. Skipping migration.")
                return

            # Add the column
            logger.info("Adding profile_image column to users table...")
            conn.execute(text("""
                ALTER TABLE users
                ADD COLUMN profile_image VARCHAR(500);
            """))
            conn.commit()

            logger.info("✅ Successfully added profile_image column to users table!")
            logger.info("Column type: VARCHAR(500)")

    except Exception as e:
        logger.error(f"❌ Error adding profile_image column: {e}")
        raise

if __name__ == "__main__":
    add_profile_image_column()
