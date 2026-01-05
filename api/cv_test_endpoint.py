"""
Test Endpoint for CV Integration
Add this to your FastAPI app to test the CV service flow
"""

from fastapi import APIRouter, File, UploadFile, HTTPException
from pydantic import BaseModel
from services.cv_client import get_cv_client
import httpx
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/test", tags=["Testing"])


class ImageURLRequest(BaseModel):
    image_url: str
    top_k: int = 3


@router.post("/cv-detection")
async def test_cv_detection(file: UploadFile = File(...)):
    """
    Test endpoint: Upload an outfit image and get detected items

    Usage:
        curl -X POST http://your-backend:8000/test/cv-detection \
             -F "file=@outfit.jpg"
    """
    try:
        # Read uploaded image
        image_bytes = await file.read()

        # Call CV service
        cv_client = get_cv_client()
        detected_items = await cv_client.detect_items(image_bytes=image_bytes)

        # Clear from memory
        del image_bytes

        return {
            "success": True,
            "message": f"Detected {len(detected_items)} items",
            "items": [
                {
                    "category": item['category'],
                    "confidence": item['confidence'],
                    "bbox": item['bbox']
                }
                for item in detected_items
            ]
        }

    except Exception as e:
        logger.error(f"CV detection test failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/cv-analyze-outfit")
async def test_cv_analyze_outfit(file: UploadFile = File(...)):
    """
    Test endpoint: Upload outfit image and get full analysis with similar products

    Usage:
        curl -X POST http://your-backend:8000/test/cv-analyze-outfit \
             -F "file=@outfit.jpg"
    """
    try:
        # Read uploaded image
        image_bytes = await file.read()

        # Call CV service for full analysis
        cv_client = get_cv_client()
        result = await cv_client.analyze_outfit(image_bytes=image_bytes, top_k=3)

        # Clear from memory
        del image_bytes

        items = result.get('items', [])

        # Format response
        formatted_items = []
        for item in items:
            detected = item['detected_item']
            similar = item['similar_products']

            formatted_items.append({
                "detected": {
                    "category": detected['category'],
                    "confidence": detected['confidence']
                },
                "similar_products": [
                    {
                        "name": p['metadata'].get('name', 'N/A'),
                        "brand": p['metadata'].get('brand', 'N/A'),
                        "price": p['metadata'].get('price', 'N/A'),
                        "similarity": p['similarity_score'],
                        "url": p['metadata'].get('product_url', '')
                    }
                    for p in similar
                ]
            })

        return {
            "success": True,
            "message": f"Analyzed outfit with {len(items)} items",
            "items": formatted_items
        }

    except Exception as e:
        logger.error(f"CV outfit analysis test failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/cv-health")
async def test_cv_health():
    """
    Test endpoint: Check if CV service is reachable

    Usage:
        curl http://your-backend:8000/test/cv-health
    """
    try:
        cv_client = get_cv_client()
        is_healthy = await cv_client.health_check()

        if is_healthy:
            return {
                "success": True,
                "message": "CV service is healthy",
                "cv_service_url": cv_client.base_url
            }
        else:
            return {
                "success": False,
                "message": "CV service is not responding",
                "cv_service_url": cv_client.base_url
            }

    except Exception as e:
        logger.error(f"CV health check failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/cv-analyze-from-url")
async def test_cv_analyze_from_url(request: ImageURLRequest):
    """
    Test endpoint: Provide Firebase/S3 image URL and get analysis
    Perfect for testing with images already hosted!

    Usage (Postman):
        POST http://your-backend:8000/test/cv-analyze-from-url
        Body (JSON):
        {
            "image_url": "https://firebasestorage.googleapis.com/...",
            "top_k": 3
        }
    """
    try:
        # Download image from URL
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(request.image_url)
            response.raise_for_status()
            image_bytes = response.content

        logger.info(f"Downloaded image from URL: {request.image_url}")

        # Call CV service for full analysis
        cv_client = get_cv_client()
        result = await cv_client.analyze_outfit(
            image_bytes=image_bytes,
            top_k=request.top_k
        )

        # Explicitly clear image from memory (though Python GC would handle this anyway)
        del image_bytes

        items = result.get('items', [])

        # Format response
        formatted_items = []
        for item in items:
            detected = item['detected_item']
            similar = item['similar_products']

            formatted_items.append({
                "detected": {
                    "category": detected['category'],
                    "confidence": detected['confidence']
                },
                "similar_products": [
                    {
                        "name": p['metadata'].get('name', 'N/A'),
                        "brand": p['metadata'].get('brand', 'N/A'),
                        "price": p['metadata'].get('price', 'N/A'),
                        "similarity": p['similarity_score'],
                        "url": p['metadata'].get('product_url', '')
                    }
                    for p in similar
                ]
            })

        return {
            "success": True,
            "message": f"Analyzed outfit from URL with {len(items)} items",
            "source_url": request.image_url,
            "items": formatted_items
        }

    except httpx.HTTPError as e:
        logger.error(f"Failed to download image from URL: {e}")
        raise HTTPException(status_code=400, detail=f"Could not download image: {str(e)}")
    except Exception as e:
        logger.error(f"CV outfit analysis from URL failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
