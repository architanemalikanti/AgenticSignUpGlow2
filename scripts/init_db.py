"""
Initialize database tables for the Stream app.
Run this once on your EC2 server to create all tables.

Usage: python init_db.py
"""

from database.db import engine, Base
from database.models import User, Design, Follow, FollowRequest, Era, Post, PostMedia
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def init_database():
    """Create all database tables."""
    try:
        logger.info("Creating database tables...")

        # This creates all tables defined in models.py
        Base.metadata.create_all(bind=engine)

        logger.info("✅ Database tables created successfully!")
        logger.info("Tables created:")
        logger.info("  - users")
        logger.info("  - designs")
        logger.info("  - follows")
        logger.info("  - follow_requests")
        logger.info("  - eras")
        logger.info("  - posts")
        logger.info("  - post_media")

    except Exception as e:
        logger.error(f"❌ Error creating database tables: {e}")
        raise

if __name__ == "__main__":
    init_database()
