"""
Script to create embeddings for all existing users in the database.
Run this once to backfill embeddings for users created before the embedding feature.

Usage: python backfill_embeddings.py
"""

from database.db import SessionLocal
from database.models import User
from profile_embeddings import create_user_profile_embedding
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s:%(name)s:%(message)s'
)
logger = logging.getLogger(__name__)


def backfill_all_user_embeddings():
    """Create embeddings for all users in the database."""

    db = SessionLocal()

    try:
        # Get all users
        users = db.query(User).all()
        total_users = len(users)

        logger.info(f"📊 Found {total_users} users in database")
        logger.info(f"🚀 Starting embedding creation...\n")

        success_count = 0
        error_count = 0

        for i, user in enumerate(users, 1):
            try:
                # Check if user has required fields
                if not all([user.city, user.occupation, user.gender, user.ethnicity]):
                    logger.warning(f"⚠️  [{i}/{total_users}] Skipping user {user.id} ({user.username}) - missing profile fields")
                    error_count += 1
                    continue

                # Create embedding
                logger.info(f"🔄 [{i}/{total_users}] Creating embedding for {user.username} ({user.name})...")
                result = create_user_profile_embedding(user)

                if "Successfully" in result:
                    logger.info(f"✅ [{i}/{total_users}] {result}")
                    success_count += 1
                else:
                    logger.error(f"❌ [{i}/{total_users}] {result}")
                    error_count += 1

            except Exception as e:
                logger.error(f"❌ [{i}/{total_users}] Error processing user {user.id}: {e}")
                error_count += 1

        # Summary
        logger.info(f"\n{'='*60}")
        logger.info(f"📊 SUMMARY")
        logger.info(f"{'='*60}")
        logger.info(f"Total users: {total_users}")
        logger.info(f"✅ Successful: {success_count}")
        logger.info(f"❌ Failed: {error_count}")
        logger.info(f"{'='*60}\n")

        if success_count > 0:
            logger.info(f"🎉 Successfully created {success_count} embeddings!")

    except Exception as e:
        logger.error(f"❌ Fatal error: {e}")

    finally:
        db.close()


if __name__ == '__main__':
    print("=" * 60)
    print("  Backfill User Embeddings to Pinecone")
    print("=" * 60)
    print()

    backfill_all_user_embeddings()

    print()
    print("Done!")
