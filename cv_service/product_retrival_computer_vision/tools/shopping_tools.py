"""
Shopping search tools for finding actual products with images, prices, and links.
Uses SerpAPI for Google Shopping results.
"""

import os
import logging
import requests
from typing import List, Dict, Optional
from langchain_core.tools import tool

logger = logging.getLogger(__name__)


def search_google_shopping(query: str, location: str = "United States", num_results: int = 10) -> List[Dict]:
    """
    Search Google Shopping for products using SerpAPI.

    Args:
        query: Search query (e.g., "black mini dress under $50")
        location: Location for shopping results (default: "United States")
        num_results: Number of results to return (default: 10)

    Returns:
        List of product dictionaries with: title, price, brand, image, link, source
    """
    api_key = os.getenv("SERPAPI_API_KEY")

    if not api_key:
        logger.error("❌ SERPAPI_API_KEY not found in environment variables")
        return []

    try:
        # SerpAPI endpoint for Google Shopping
        url = "https://serpapi.com/search"

        params = {
            "engine": "google_shopping",
            "q": query,
            "location": location,
            "gl": "us",
            "hl": "en",
            "num": num_results,
            "api_key": api_key
        }

        logger.info(f"🛍️ Searching Google Shopping for: {query}")
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()

        data = response.json()

        # Parse shopping results
        shopping_results = data.get("shopping_results", [])

        products = []
        for item in shopping_results[:num_results]:
            product = {
                "title": item.get("title", ""),
                "price": item.get("price", "Price not available"),
                "brand": item.get("source", ""),  # Store/brand name
                "image_url": item.get("thumbnail", ""),
                "product_url": item.get("product_link", ""),  # Correct field from SerpAPI
                "source": item.get("source", ""),
                "rating": item.get("rating", None),
                "reviews": item.get("reviews", None),
                "delivery": item.get("delivery", "")
            }
            products.append(product)

        logger.info(f"✅ Found {len(products)} products")
        return products

    except Exception as e:
        logger.error(f"❌ Error searching Google Shopping: {e}")
        return []


@tool
def shopping_search_tool(query: str) -> str:
    """
    Search for fashion products on Google Shopping. Returns products with images, prices, brands, and links.
    Use this when the user asks for specific clothing items, accessories, or fashion products.

    Args:
        query: What to search for (e.g., "black mini dress under $50", "silver hoop earrings cheap")

    Returns:
        Formatted string with product details including images, prices, and purchase links.
    """
    products = search_google_shopping(query)

    if not products:
        return f"No products found for '{query}'. Try a different search term."

    # Format products for the AI
    result = f"Found {len(products)} products for '{query}':\n\n"

    for i, product in enumerate(products, 1):
        result += f"{i}. {product['title']}\n"
        result += f"   Price: {product['price']}\n"
        result += f"   Brand/Store: {product['brand']}\n"
        result += f"   Link: {product['product_url']}\n"
        result += f"   Image: {product['image_url']}\n"

        if product.get('rating'):
            result += f"   Rating: {product['rating']} ({product.get('reviews', 0)} reviews)\n"

        result += "\n"

    return result


def get_structured_products(query: str, location: str = "United States", num_results: int = 10) -> List[Dict]:
    """
    Get structured product data for direct use in API responses.

    Args:
        query: Search query
        location: Shopping location
        num_results: Number of products to return

    Returns:
        List of structured product dictionaries ready for JSON response
    """
    return search_google_shopping(query, location, num_results)
