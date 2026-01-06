#!/usr/bin/env python3
"""
Clear all products from Pinecone index
⚠️ WARNING: This will delete ALL products from the database!
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from cv_service.product_retrival_computer_vision import get_search_engine
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def clear_pinecone():
    """Delete all vectors from Pinecone index"""

    logger.info("🔍 Connecting to Pinecone...")
    search_engine = get_search_engine()

    # Get stats before deletion
    stats_before = search_engine.get_index_stats()
    total_before = stats_before.get('total_vectors', 0)

    logger.info(f"\n📊 Current index stats:")
    logger.info(f"   Total products: {total_before}")

    if total_before == 0:
        logger.info("\n✅ Index is already empty!")
        return

    # Confirm deletion
    logger.info(f"\n⚠️  WARNING: About to delete ALL {total_before} products from Pinecone!")
    response = input("Type 'DELETE' to confirm: ")

    if response != "DELETE":
        logger.info("❌ Deletion cancelled")
        return

    try:
        logger.info("\n🗑️  Deleting all vectors...")

        # Delete all vectors from the index
        search_engine.index.delete(delete_all=True)

        logger.info("⏳ Waiting for deletion to complete...")

        # Wait a moment for deletion to propagate
        import time
        time.sleep(2)

        # Check stats after deletion
        stats_after = search_engine.get_index_stats()
        total_after = stats_after.get('total_vectors', 0)

        logger.info(f"\n✅ Deletion complete!")
        logger.info(f"   Products before: {total_before}")
        logger.info(f"   Products after: {total_after}")

        if total_after == 0:
            logger.info("\n🎉 Pinecone index is now empty and ready for fresh data!")
        else:
            logger.warning(f"\n⚠️  Warning: {total_after} products still remain (may take time to propagate)")

    except Exception as e:
        logger.error(f"❌ Error clearing Pinecone: {e}")
        raise


if __name__ == "__main__":
    logger.info("🧹 Pinecone Database Cleaner")
    logger.info("=" * 60)
    clear_pinecone()
