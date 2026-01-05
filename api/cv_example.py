"""
Example: How to use CV Service Client in your API endpoints

This shows how to integrate the CV service into your outfit feed endpoints.
"""

from fastapi import APIRouter, UploadFile, File, HTTPException
from services.cv_client import get_cv_client
import logging

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/outfit/analyze")
async def analyze_outfit_image(file: UploadFile = File(...)):
    """
    Analyze an outfit image and return detected items with similar products

    Example usage in your existing outfit endpoints
    """
    try:
        # Read uploaded image
        image_bytes = await file.read()

        # Call CV service
        cv_client = get_cv_client()
        result = await cv_client.analyze_outfit(
            image_bytes=image_bytes,
            top_k=3  # Get top 3 similar products per detected item
        )

        # Process results
        items = result.get('items', [])

        response = {
            "success": True,
            "detected_items_count": len(items),
            "items": [
                {
                    "category": item['detected_item']['category'],
                    "confidence": item['detected_item']['confidence'],
                    "similar_products": [
                        {
                            "name": p['metadata'].get('name'),
                            "brand": p['metadata'].get('brand'),
                            "price": p['metadata'].get('price'),
                            "image_url": p['metadata'].get('image_url'),
                            "product_url": p['metadata'].get('product_url'),
                            "similarity": p['similarity_score']
                        }
                        for p in item['similar_products']
                    ]
                }
                for item in items
            ]
        }

        return response

    except Exception as e:
        logger.error(f"Error analyzing outfit: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/cv/health")
async def check_cv_service_health():
    """
    Check if CV service is available
    Useful for monitoring and health checks
    """
    cv_client = get_cv_client()
    is_healthy = await cv_client.health_check()

    if is_healthy:
        return {"status": "healthy", "cv_service": "available"}
    else:
        return {"status": "unhealthy", "cv_service": "unavailable"}


# ============================================
# How to integrate into existing endpoints:
# ============================================

async def get_outfit_with_cv_analysis(outfit_image_url: str):
    """
    Example: How to add CV analysis to your existing outfit feed
    """
    import httpx

    # Download outfit image from URL
    async with httpx.AsyncClient() as client:
        response = await client.get(outfit_image_url)
        image_bytes = response.content

    # Analyze with CV service
    cv_client = get_cv_client()
    cv_results = await cv_client.analyze_outfit(
        image_bytes=image_bytes,
        top_k=5
    )

    # Return outfit data with CV analysis
    return {
        "outfit_url": outfit_image_url,
        "detected_items": cv_results.get('items', []),
        # ... your other outfit data
    }


async def search_similar_to_product_image(product_image_bytes: bytes, category: str = None):
    """
    Example: Find similar products to a given product image
    """
    import base64

    # Encode image to base64
    image_base64 = base64.b64encode(product_image_bytes).decode('utf-8')

    # Search with CV service
    cv_client = get_cv_client()
    results = await cv_client.search_similar_products(
        image_base64=image_base64,
        top_k=10,
        category_filter=category
    )

    return results


async def detect_items_only(image_bytes: bytes):
    """
    Example: Just detect fashion items without searching
    """
    cv_client = get_cv_client()
    detected_items = await cv_client.detect_items(image_bytes=image_bytes)

    return [
        {
            "category": item['category'],
            "confidence": item['confidence'],
            "bbox": item['bbox']  # [x1, y1, x2, y2]
        }
        for item in detected_items
    ]
