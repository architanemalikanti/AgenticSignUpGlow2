#!/usr/bin/env python3
"""
Scrape fashion products from real retailers and index them to Pinecone
Targets: Forever 21, Myntra, H&M, Zara, Shein, etc.
"""

import os
import sys
import cv2
import requests
import logging
import time
from pathlib import Path

# Add parent directory to path for imports
sys.path.append(str(Path(__file__).parent.parent))

from product_retrival_computer_vision import (
    get_feature_extractor,
    get_search_engine
)
from product_retrival_computer_vision.tools.shopping_tools import search_google_shopping

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# Fashion brands and categories to scrape
BRANDS = [
    "Forever 21",
    "Myntra",
    "H&M",
    "Zara",
    "Shein",
    "ASOS",
    "Mango",
    "Urban Outfitters"
]

CATEGORIES = [
    "women black dress",
    "women white t-shirt",
    "women blue jeans",
    "women leather jacket",
    "women sneakers",
    "women handbag",
    "women sunglasses",
    "women cardigan",
    "women blazer",
    "women midi skirt",
    "women crop top",
    "women denim jacket",
    "women ankle boots",
    "women trench coat",
    "women maxi dress"
]

# Color keywords for filtering
COLORS = [
    "black", "white", "blue", "red", "green", "pink",
    "yellow", "brown", "beige", "grey", "navy", "burgundy"
]


def extract_color_from_text(text: str) -> str:
    """Extract primary color from product name/description"""
    text_lower = text.lower()
    for color in COLORS:
        if color in text_lower:
            return color
    return "multicolor"


def download_image(url: str, save_path: str) -> bool:
    """Download image from URL"""
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()

        with open(save_path, 'wb') as f:
            f.write(response.content)

        return True
    except Exception as e:
        logger.error(f"Error downloading image: {e}")
        return False


def scrape_and_index_products(target_count: int = 500):
    """
    Scrape fashion products and index them to Pinecone

    Args:
        target_count: Number of products to scrape and index
    """
    # Initialize CV pipeline
    logger.info("🚀 Initializing CV pipeline...")
    extractor = get_feature_extractor()
    search_engine = get_search_engine()

    # Create temp directory for product images
    temp_dir = Path("/tmp/fashion_products")
    temp_dir.mkdir(exist_ok=True)

    indexed_count = 0
    products_batch = []

    try:
        # Scrape from each category
        for category in CATEGORIES:
            if indexed_count >= target_count:
                break

            logger.info(f"\n📦 Scraping: {category}")

            # Search Google Shopping
            products = search_google_shopping(
                query=f"{category} fashion",
                num_results=50  # Get more to filter
            )

            for product in products:
                if indexed_count >= target_count:
                    break

                try:
                    # Download product image
                    image_url = product['image_url']
                    product_id = f"PROD_{indexed_count:05d}"
                    image_path = temp_dir / f"{product_id}.jpg"

                    logger.info(f"  [{indexed_count+1}/{target_count}] Processing: {product['title'][:50]}...")

                    if not download_image(image_url, str(image_path)):
                        continue

                    # Load image
                    image = cv2.imread(str(image_path))
                    if image is None:
                        logger.warning(f"    ⚠️ Could not load image")
                        continue

                    # Extract features (includes color)
                    features = extractor.extract_all_features(image)
                    embedding = features['combined']

                    # Extract color from title
                    color = extract_color_from_text(product['title'])

                    # Extract category (simplified)
                    category_name = category.split()[-1]  # Last word

                    # Parse price to numeric
                    price_str = product['price']
                    try:
                        # Extract numeric value (e.g., "$49.99" -> 49.99)
                        price_numeric = float(''.join(c for c in price_str if c.isdigit() or c == '.'))
                    except:
                        price_numeric = 0.0

                    # Prepare metadata
                    metadata = {
                        'name': product['title'],
                        'brand': product['brand'] or 'Unknown',
                        'retailer': product['source'] or 'Unknown',
                        'price': price_str,
                        'price_numeric': price_numeric,
                        'category': category_name,
                        'color': color,
                        'image_url': image_url,
                        'product_url': product['product_url']
                    }

                    # Add to batch
                    products_batch.append({
                        'id': product_id,
                        'embedding': embedding,
                        'metadata': metadata
                    })

                    indexed_count += 1

                    # Batch upsert every 50 products
                    if len(products_batch) >= 50:
                        logger.info(f"  💾 Batch upserting {len(products_batch)} products...")
                        search_engine.upsert_batch(products_batch)
                        products_batch = []

                    # Small delay to avoid rate limits
                    time.sleep(0.1)

                except Exception as e:
                    logger.error(f"    ❌ Error processing product: {e}")
                    continue

        # Upsert remaining products
        if products_batch:
            logger.info(f"💾 Final batch upserting {len(products_batch)} products...")
            search_engine.upsert_batch(products_batch)

        # Get index stats
        stats = search_engine.get_index_stats()
        logger.info(f"\n✅ Indexing complete!")
        logger.info(f"   Total indexed: {indexed_count} products")
        logger.info(f"   Pinecone stats: {stats}")

    except KeyboardInterrupt:
        logger.info("\n⚠️ Interrupted by user")
        if products_batch:
            logger.info(f"💾 Saving {len(products_batch)} remaining products...")
            search_engine.upsert_batch(products_batch)

    except Exception as e:
        logger.error(f"❌ Error during scraping: {e}")
        raise


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Scrape and index fashion products")
    parser.add_argument(
        '--count',
        type=int,
        default=500,
        help='Number of products to scrape (default: 500)'
    )
    args = parser.parse_args()

    logger.info("🛍️ Starting fashion product scraping...")
    scrape_and_index_products(target_count=args.count)
    logger.info("✨ All done!")
