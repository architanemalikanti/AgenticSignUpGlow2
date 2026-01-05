"""
Fashion API Helper Functions and Models
Contains helper functions and Pydantic models for fashion detection, search, and analysis
"""

from fastapi import HTTPException
from pydantic import BaseModel
from typing import List, Dict, Optional
import cv2
import numpy as np
import io
from PIL import Image
import logging

logger = logging.getLogger(__name__)

# ==========================================
# Pydantic Models
# ==========================================

class DetectedItem(BaseModel):
    category: str
    bbox: List[int]  # [x1, y1, x2, y2]
    confidence: float
    attributes: Optional[Dict] = None


class SearchResult(BaseModel):
    item_name: str
    brand: str
    price: str
    image_url: str
    product_url: str
    similarity_score: float


class DetectionResponse(BaseModel):
    success: bool
    timestamp: str
    detected_items: List[DetectedItem]
    processing_time_ms: float


class SearchResponse(BaseModel):
    success: bool
    timestamp: str
    query_item: DetectedItem
    similar_items: List[SearchResult]
    total_found: int


class AnalysisResponse(BaseModel):
    success: bool
    timestamp: str
    outfit_analysis: Dict
    style_recommendations: List[str]
    detected_items: List[DetectedItem]
    all_search_results: Dict[str, List[SearchResult]]


# ==========================================
# Helper Functions
# ==========================================

async def process_image(image_data: bytes) -> np.ndarray:
    """
    Process uploaded image data into OpenCV format

    Args:
        image_data: Raw image bytes

    Returns:
        OpenCV image array (numpy.ndarray)

    Raises:
        HTTPException: If image format is invalid
    """
    try:
        # Convert bytes to PIL Image
        image = Image.open(io.BytesIO(image_data))

        # Convert to RGB if needed
        if image.mode != 'RGB':
            image = image.convert('RGB')

        # Convert to OpenCV format
        opencv_image = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)

        return opencv_image
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid image format: {str(e)}")


def analyze_style_composition(detected_items: List) -> Dict:
    """
    Analyze the style composition of detected fashion items

    Args:
        detected_items: List of detected fashion items

    Returns:
        Dictionary containing style analysis
    """
    categories = [item.category for item in detected_items]

    # Determine style based on items present
    style_analysis = {
        "total_items": len(detected_items),
        "categories_detected": list(set(categories)),
        "primary_style": "casual",  # Default
        "color_palette": "monochromatic",
        "formality_level": "casual"
    }

    # Analyze color scheme
    colors = []
    for item in detected_items:
        if item.attributes and 'dominant_colors' in item.attributes:
            item_colors = item.attributes['dominant_colors']
            for color_info in item_colors:
                colors.append(color_info['rgb'])

    if colors:
        # Simple color analysis
        dark_colors = sum(1 for color in colors if sum(color) < 150)
        if dark_colors / len(colors) > 0.8:
            style_analysis["color_palette"] = "dark/monochromatic"

    # Determine style based on categories and materials
    if 'jacket' in categories:
        materials = []
        for item in detected_items:
            if item.category == 'jacket' and item.attributes:
                material = item.attributes.get('material', '')
                materials.append(material)

        if any('leather' in mat for mat in materials):
            style_analysis["primary_style"] = "edgy/rock"
            style_analysis["formality_level"] = "casual-cool"

    return style_analysis


def generate_style_recommendations(detected_items: List, search_results: Dict) -> List[str]:
    """
    Generate style recommendations based on detected items and search results

    Args:
        detected_items: List of detected fashion items
        search_results: Dictionary of search results by category

    Returns:
        List of style recommendation strings
    """
    recommendations = []

    categories = [item.category for item in detected_items]

    if 'jacket' in categories and 'bag' in categories:
        recommendations.append(
            "Great edgy look! The leather jacket and bag create a cohesive rock-chic aesthetic."
        )
        recommendations.append(
            "Consider adding metallic accessories to complement the chain details."
        )

    if len(search_results) > 0:
        # Add shopping recommendations
        for category, results in search_results.items():
            if results:
                top_result = results[0]
                recommendations.append(
                    f"Similar {category}: {top_result.brand} {top_result.item_name} ({top_result.price})"
                )

    recommendations.append(
        "This style would work well for: casual outings, concerts, date nights"
    )

    return recommendations
