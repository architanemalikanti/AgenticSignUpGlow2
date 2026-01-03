"""
Migration script to add actor_id column to eras table.
Run this on your EC2 server to add the actor_id field for tracking who triggered each notification.

Usage: python add_actor_id_to_eras.py
"""

from database.db import engine
from sqlalchemy import text
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def add_actor_id_column():
    """Add actor_id column to eras table."""
    try:
        with engine.connect() as conn:
            # Check if column already exists
            result = conn.execute(text("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name='eras' AND column_name='actor_id';
            """))

            if result.fetchone():
                logger.info("⚠️  Column 'actor_id' already exists in eras table. Skipping migration.")
                return

            # Add the column
            logger.info("Adding actor_id column to eras table...")
            conn.execute(text("""
                ALTER TABLE eras
                ADD COLUMN actor_id VARCHAR(36);
            """))

            # Add foreign key constraint
            logger.info("Adding foreign key constraint...")
            conn.execute(text("""
                ALTER TABLE eras
                ADD CONSTRAINT fk_eras_actor_id
                FOREIGN KEY (actor_id) REFERENCES users(id);
            """))

            conn.commit()

            logger.info("✅ Successfully added actor_id column to eras table!")
            logger.info("Column type: VARCHAR(36) with foreign key to users(id)")

    except Exception as e:
        logger.error(f"❌ Error adding actor_id column: {e}")
        raise

if __name__ == "__main__":
    add_actor_id_column()
