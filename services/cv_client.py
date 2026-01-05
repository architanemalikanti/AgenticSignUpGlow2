"""
CV Service Client
HTTP client for calling the separate CV service
"""

import httpx
import os
import logging
from typing import List, Optional, Dict, Any
import base64

logger = logging.getLogger(__name__)

# CV Service URL from environment variable
CV_SERVICE_URL = os.getenv("CV_SERVICE_URL", "http://localhost:8001")


class CVServiceClient:
    """Client for interacting with the CV service"""

    def __init__(self, base_url: str = None):
        self.base_url = base_url or CV_SERVICE_URL
        self.client = httpx.AsyncClient(timeout=30.0)

    async def health_check(self) -> bool:
        """Check if CV service is healthy"""
        try:
            response = await self.client.get(f"{self.base_url}/health")
            return response.status_code == 200
        except Exception as e:
            logger.error(f"CV service health check failed: {e}")
            return False

    async def detect_items(self, image_path: str = None, image_bytes: bytes = None) -> List[Dict[str, Any]]:
        """
        Detect fashion items in an image

        Args:
            image_path: Path to image file (if available locally)
            image_bytes: Image bytes (if uploading from memory)

        Returns:
            List of detected items with bounding boxes and cropped images
        """
        try:
            if image_path:
                with open(image_path, 'rb') as f:
                    files = {'file': f}
                    response = await self.client.post(
                        f"{self.base_url}/detect",
                        files=files
                    )
            elif image_bytes:
                files = {'file': ('image.jpg', image_bytes, 'image/jpeg')}
                response = await self.client.post(
                    f"{self.base_url}/detect",
                    files=files
                )
            else:
                raise ValueError("Either image_path or image_bytes must be provided")

            response.raise_for_status()
            return response.json()

        except Exception as e:
            logger.error(f"Error calling CV detect endpoint: {e}")
            raise

    async def search_similar_products(
        self,
        image_base64: str,
        top_k: int = 5,
        category_filter: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Search for similar products given an image

        Args:
            image_base64: Base64-encoded image
            top_k: Number of similar products to return
            category_filter: Optional category filter (e.g., "dress", "jacket")

        Returns:
            Search results with similar products
        """
        try:
            payload = {
                "image_base64": image_base64,
                "top_k": top_k,
                "category_filter": category_filter
            }

            response = await self.client.post(
                f"{self.base_url}/search",
                json=payload
            )
            response.raise_for_status()
            return response.json()

        except Exception as e:
            logger.error(f"Error calling CV search endpoint: {e}")
            raise

    async def analyze_outfit(
        self,
        image_path: str = None,
        image_bytes: bytes = None,
        top_k: int = 3
    ) -> Dict[str, Any]:
        """
        Complete pipeline: detect items and find similar products

        Args:
            image_path: Path to outfit image
            image_bytes: Outfit image bytes
            top_k: Number of similar products per detected item

        Returns:
            Detected items with similar products for each
        """
        try:
            if image_path:
                with open(image_path, 'rb') as f:
                    files = {'file': f}
                    response = await self.client.post(
                        f"{self.base_url}/analyze-outfit",
                        files=files,
                        params={'top_k': top_k}
                    )
            elif image_bytes:
                files = {'file': ('image.jpg', image_bytes, 'image/jpeg')}
                response = await self.client.post(
                    f"{self.base_url}/analyze-outfit",
                    files=files,
                    params={'top_k': top_k}
                )
            else:
                raise ValueError("Either image_path or image_bytes must be provided")

            response.raise_for_status()
            return response.json()

        except Exception as e:
            logger.error(f"Error calling CV analyze-outfit endpoint: {e}")
            raise

    async def close(self):
        """Close the HTTP client"""
        await self.client.aclose()


# Singleton instance
_cv_client = None


def get_cv_client() -> CVServiceClient:
    """Get or create CV client singleton"""
    global _cv_client
    if _cv_client is None:
        _cv_client = CVServiceClient()
    return _cv_client
