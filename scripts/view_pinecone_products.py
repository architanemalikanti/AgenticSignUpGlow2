#!/usr/bin/env python3
"""
View products stored in Pinecone
Shows sample products and checks if they have product_url
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from cv_service.product_retrival_computer_vision import get_search_engine
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def view_pinecone_products(sample_size=10):
    """View sample products from Pinecone"""

    logger.info("🔍 Connecting to Pinecone...")
    search_engine = get_search_engine()

    # Get index stats
    stats = search_engine.get_index_stats()
    logger.info(f"\n📊 Pinecone Index Stats:")
    logger.info(f"   Total products: {stats.get('total_vectors', 0)}")
    logger.info(f"   Dimension: {stats.get('dimension', 0)}")
    logger.info(f"   Index fullness: {stats.get('index_fullness', 0)}")

    # Fetch a few products to check their data
    logger.info(f"\n📦 Fetching {sample_size} sample products...\n")

    try:
        # Query with a dummy vector to get some results
        import numpy as np
        dummy_vector = np.random.rand(2144).tolist()

        results = search_engine.index.query(
            vector=dummy_vector,
            top_k=sample_size,
            include_metadata=True
        )

        products_with_urls = 0
        products_without_urls = 0

        logger.info("=" * 80)
        for i, match in enumerate(results['matches'], 1):
            metadata = match.get('metadata', {})
            product_url = metadata.get('product_url', '')

            if product_url:
                products_with_urls += 1
            else:
                products_without_urls += 1

            logger.info(f"\nProduct {i}:")
            logger.info(f"  ID: {match['id']}")
            logger.info(f"  Name: {metadata.get('name', 'N/A')}")
            logger.info(f"  Brand: {metadata.get('brand', 'N/A')}")
            logger.info(f"  Price: {metadata.get('price', 'N/A')}")
            logger.info(f"  Category: {metadata.get('category', 'N/A')}")
            logger.info(f"  Image URL: {metadata.get('image_url', 'N/A')[:60]}...")

            if product_url:
                logger.info(f"  Product URL: ✅ {product_url}")  # Show full URL
            else:
                logger.info(f"  Product URL: ❌ EMPTY")

            logger.info("-" * 80)

        logger.info(f"\n📊 Summary:")
        logger.info(f"   Products WITH links: {products_with_urls}/{sample_size}")
        logger.info(f"   Products WITHOUT links: {products_without_urls}/{sample_size}")

    except Exception as e:
        logger.error(f"❌ Error fetching products: {e}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="View products in Pinecone")
    parser.add_argument(
        '--count',
        type=int,
        default=10,
        help='Number of sample products to view (default: 10)'
    )
    args = parser.parse_args()

    view_pinecone_products(sample_size=args.count)
