"""
Outfit Feed Endpoints
Handles outfit feed for iOS with caching, prefetching, and LLM price calculation
"""

from fastapi import BackgroundTasks, HTTPException
from database.db import SessionLocal
from database.models import Outfit, OutfitProduct
from datetime import datetime
import logging
import json
from anthropic import Anthropic
import os
import requests
import base64
import cv2
import numpy as np

logger = logging.getLogger(__name__)

# Initialize Anthropic client for price calculation
anthropic_client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))


def calculate_total_price_with_llm(products: list) -> str:
    """
    Use LLM to parse product prices and calculate total

    Args:
        products: List of OutfitProduct objects with price_display fields

    Returns:
        Total price as string (e.g., "$99")
    """
    if not products:
        return "$0"

    # Build price list for LLM
    price_list = [p.price_display for p in products]

    try:
        prompt = f"""Extract the numeric price from each item and calculate the total.

Prices: {', '.join(price_list)}

Return ONLY the total as a number (no currency symbol). If any price is unclear, skip it.

Examples:
- "$49.99, $25.00" → 74.99
- "₹1,299, ₹999" → 2298
- "$30, Free" → 30
"""

        response = anthropic_client.messages.create(
            model="claude-3-haiku-20240307",
            max_tokens=50,
            messages=[{"role": "user", "content": prompt}]
        )

        total = response.content[0].text.strip()

        # Format based on currency (detect from first price)
        first_price = price_list[0]
        if '₹' in first_price:
            return f"₹{total}"
        elif '€' in first_price:
            return f"€{total}"
        else:
            return f"${total}"

    except Exception as e:
        logger.error(f"Error calculating price with LLM: {e}")
        return "$0"


def search_google_shopping_products(query: str, num_results: int = 10):
    """
    Search Google Shopping for products using SerpAPI

    Args:
        query: Search query (e.g., "black leather jacket women")
        num_results: Number of results to return

    Returns:
        List of product dictionaries
    """
    api_key = os.getenv("SERPAPI_API_KEY")
    if not api_key:
        logger.error("❌ SERPAPI_API_KEY not found in environment")
        return []

    try:
        url = "https://serpapi.com/search"
        params = {
            "engine": "google_shopping",
            "q": query,
            "location": "United States",
            "gl": "us",
            "hl": "en",
            "num": num_results,
            "api_key": api_key
        }

        logger.info(f"🛍️ Searching Google Shopping for: {query}")
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()

        products = []
        for item in data.get("shopping_results", [])[:num_results]:
            products.append({
                "title": item.get("title", ""),
                "price": item.get("price", "Price not available"),
                "brand": item.get("source", ""),
                "image_url": item.get("thumbnail", ""),
                "product_url": item.get("link", ""),
                "source": item.get("source", "")
            })

        logger.info(f"✅ Found {len(products)} products")
        return products

    except Exception as e:
        logger.error(f"❌ Error searching Google Shopping: {e}")
        return []


def analyze_outfit_and_cache_products(outfit_id: str, image_url: str):
    """
    Analyze outfit image using Claude VLM and search for products

    Flow:
    1. Download outfit image
    2. Use Claude VLM to identify clothing items
    3. For each item, search Google Shopping
    4. Save top 3 products per item to OutfitProduct table

    Args:
        outfit_id: UUID of the outfit
        image_url: Public URL of the outfit image
    """
    db = SessionLocal()
    try:
        logger.info(f"🔍 Analyzing outfit {outfit_id} from {image_url}")

        # Download image
        response = requests.get(image_url, timeout=10)
        response.raise_for_status()
        image_data = base64.standard_b64encode(response.content).decode("utf-8")

        # Determine media type
        if image_url.lower().endswith('.png'):
            media_type = "image/png"
        elif image_url.lower().endswith('.webp'):
            media_type = "image/webp"
        else:
            media_type = "image/jpeg"

        # Use Claude VLM to detect clothing items
        prompt = """Analyze this outfit image and list the main clothing items and accessories visible.

For each item, provide:
1. Item name (e.g., "black leather jacket", "white sneakers")
2. Brief description of style/details

Return as JSON array:
[
    {"item": "black leather jacket", "description": "cropped style with silver zippers"},
    {"item": "blue denim jeans", "description": "high-waisted straight leg"},
    ...
]

Focus on the most prominent items (top 3-5). Be specific about colors and styles."""

        message = anthropic_client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=500,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": image_data,
                            },
                        },
                        {
                            "type": "text",
                            "text": prompt
                        }
                    ],
                }
            ],
        )

        # Parse detected items
        items_text = message.content[0].text.strip()
        # Extract JSON from response (Claude might wrap it in markdown)
        if "```json" in items_text:
            items_text = items_text.split("```json")[1].split("```")[0].strip()
        elif "```" in items_text:
            items_text = items_text.split("```")[1].split("```")[0].strip()

        detected_items = json.loads(items_text)
        logger.info(f"✅ Detected {len(detected_items)} items in outfit")

        # For each item, search Google Shopping
        rank = 1
        for item_data in detected_items[:5]:  # Max 5 items
            item_name = item_data.get("item", "")
            description = item_data.get("description", "")

            # Search Google Shopping
            search_query = f"{item_name} women fashion"
            products = search_google_shopping_products(search_query, num_results=3)

            # Save top 3 products
            for product in products[:3]:
                outfit_product = OutfitProduct(
                    outfit_id=outfit_id,
                    product_name=product["title"],
                    brand=product["brand"],
                    retailer=product["source"],
                    price_display=product["price"],
                    product_image_url=product["image_url"],
                    product_url=product["product_url"],
                    rank=rank
                )
                db.add(outfit_product)
                rank += 1

        db.commit()
        logger.info(f"✅ Cached {rank-1} products for outfit {outfit_id}")

    except Exception as e:
        db.rollback()
        logger.error(f"❌ Error analyzing outfit {outfit_id}: {e}")
    finally:
        db.close()


async def get_outfit_by_id(outfit_id: str, background_tasks: BackgroundTasks):
    """
    Get specific outfit by ID with caching and prefetching

    Returns:
        {
            "outfit_id": "uuid",
            "title": "1999 celeb caught by paparazzi, $99",
            "image_url": "https://...",
            "products": [
                {
                    "name": "Leather Jacket",
                    "brand": "Zara",
                    "retailer": "Zara",
                    "price": "$49.99",
                    "image_url": "https://...",
                    "product_url": "https://...",
                    "rank": 1
                },
                ...
            ]
        }
    """
    db = SessionLocal()
    try:
        # Get outfit by ID
        outfit = db.query(Outfit).filter(Outfit.id == outfit_id).first()

        if not outfit:
            raise HTTPException(status_code=404, detail="Outfit not found")

        # Get products for outfit
        products = db.query(OutfitProduct).filter(
            OutfitProduct.outfit_id == outfit.id
        ).order_by(OutfitProduct.rank).all()

        # If no products cached, trigger CV analysis in background
        if not products:
            logger.info(f"⚡ No products cached for outfit {outfit.id}, triggering analysis...")
            background_tasks.add_task(analyze_outfit_and_cache_products, outfit.id, outfit.image_url)

        # Calculate total price using LLM
        total_price = calculate_total_price_with_llm(products) if products else "$0"

        # Build title with price
        title_with_price = f"{outfit.base_title}, {total_price}"

        # Prefetch next 3 outfits in background
        next_outfits = db.query(Outfit).filter(
            Outfit.created_at > outfit.created_at
        ).order_by(Outfit.created_at).limit(3).all()

        for next_outfit in next_outfits:
            # Check if products are cached
            cached_products = db.query(OutfitProduct).filter(
                OutfitProduct.outfit_id == next_outfit.id
            ).count()

            if cached_products == 0:
                logger.info(f"🔮 Prefetching products for outfit {next_outfit.id}")
                background_tasks.add_task(analyze_outfit_and_cache_products, next_outfit.id, next_outfit.image_url)

        return {
            "outfit_id": outfit.id,
            "title": title_with_price,
            "image_url": outfit.image_url,
            "gender": outfit.gender,
            "products": [
                {
                    "name": p.product_name,
                    "brand": p.brand,
                    "retailer": p.retailer,
                    "price": p.price_display,
                    "image_url": p.product_image_url,
                    "product_url": p.product_url,
                    "rank": int(p.rank)
                }
                for p in products
            ]
        }

    finally:
        db.close()


async def get_all_outfits():
    """
    Get all outfits (for iOS to fetch list and manage locally)

    Returns list of all outfit IDs in order
    """
    db = SessionLocal()
    try:
        outfits = db.query(Outfit).order_by(Outfit.created_at).all()

        return {
            "total": len(outfits),
            "outfits": [
                {
                    "outfit_id": o.id,
                    "title": o.base_title,
                    "image_url": o.image_url,
                    "gender": o.gender,
                    "created_at": o.created_at.isoformat()
                }
                for o in outfits
            ]
        }

    finally:
        db.close()


async def get_next_outfit(user_id: str, count: int, background_tasks: BackgroundTasks):
    """
    Get the next N outfits for this user (Instagram-style batch loading)

    Returns multiple outfits at once for smooth infinite scrolling.
    Tracks progress per user so next call continues where they left off.

    Args:
        user_id: User ID from auth token
        count: Number of outfits to return (default 10, like Instagram)

    Returns:
        List of outfits in same format as get_outfit_by_id()
    """
    from database.models import UserProgress

    logger.info(f"🔍 get_next_outfit called with user_id={user_id}, count={count}")

    db = SessionLocal()
    try:
        # Get user's current progress
        user_progress = db.query(UserProgress).filter(
            UserProgress.user_id == user_id
        ).first()
        logger.info(f"📊 User progress: {user_progress}")

        # Get all outfits ordered by created_at
        all_outfits = db.query(Outfit).order_by(Outfit.created_at).all()
        logger.info(f"👗 Found {len(all_outfits)} total outfits")

        if not all_outfits:
            logger.error("❌ No outfits available in database")
            raise HTTPException(status_code=404, detail="No outfits available")

        # Determine starting index
        if user_progress:
            # User has viewed outfits before - start from next one
            current_index = next(
                (i for i, o in enumerate(all_outfits) if o.id == user_progress.current_outfit_id),
                -1
            )
            start_index = (current_index + 1) % len(all_outfits)
        else:
            # First time viewing - start at beginning
            start_index = 0

        # Get next N outfits (wrapping around if needed)
        outfits_to_return = []
        for i in range(count):
            outfit_index = (start_index + i) % len(all_outfits)
            outfits_to_return.append(all_outfits[outfit_index])

        # Update progress to last outfit in batch
        last_outfit = outfits_to_return[-1]
        if user_progress:
            user_progress.current_outfit_id = last_outfit.id
            user_progress.last_viewed_at = datetime.utcnow()
        else:
            user_progress = UserProgress(
                user_id=user_id,
                current_outfit_id=last_outfit.id,
                last_viewed_at=datetime.utcnow()
            )
            db.add(user_progress)
        db.commit()

        # Build response for each outfit
        result = []
        for outfit in outfits_to_return:
            # Get products for this outfit
            products = db.query(OutfitProduct).filter(
                OutfitProduct.outfit_id == outfit.id
            ).order_by(OutfitProduct.rank).all()

            # If no products cached, trigger CV analysis in background
            if not products:
                logger.info(f"⚡ No products cached for outfit {outfit.id}, triggering analysis...")
                background_tasks.add_task(analyze_outfit_and_cache_products, outfit.id, outfit.image_url)

            # Calculate total price using LLM
            total_price = calculate_total_price_with_llm(products) if products else "$0"

            # Build title with price
            title_with_price = f"{outfit.base_title}, {total_price}"

            result.append({
                "outfit_id": outfit.id,
                "title": title_with_price,
                "image_url": outfit.image_url,
                "gender": outfit.gender,
                "products": [
                    {
                        "name": p.product_name,
                        "brand": p.brand,
                        "retailer": p.retailer,
                        "price": p.price_display,
                        "image_url": p.product_image_url,
                        "product_url": p.product_url,
                        "rank": int(p.rank)
                    }
                    for p in products
                ]
            })

        logger.info(f"📦 Returned batch of {len(result)} outfits for user {user_id}")
        return result

    finally:
        db.close()
