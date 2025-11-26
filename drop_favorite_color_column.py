"""
Migration script to drop favorite_color column from users table.
Run this on your EC2 server after replacing favorite_color with ethnicity.

Usage: python drop_favorite_color_column.py
"""

from database.db import engine
from sqlalchemy import text
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def drop_favorite_color_column():
    """Drop favorite_color column from users table."""
    try:
        with engine.connect() as conn:
            # Check if column exists first
            result = conn.execute(text("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name='users' AND column_name='favorite_color';
            """))

            if not result.fetchone():
                logger.info("⚠️  Column 'favorite_color' does not exist in users table. Nothing to drop.")
                return

            # Drop the column
            logger.info("Dropping favorite_color column from users table...")
            conn.execute(text("ALTER TABLE users DROP COLUMN favorite_color;"))
            conn.commit()

            logger.info("✅ Successfully dropped favorite_color column from users table!")

    except Exception as e:
        logger.error(f"❌ Error dropping favorite_color column: {e}")
        raise

if __name__ == "__main__":
    drop_favorite_color_column()
