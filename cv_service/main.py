"""
CV Service - Standalone FastAPI service for computer vision processing
Handles fashion item detection, feature extraction, and similarity search
"""

from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import cv2
import numpy as np
import logging
from typing import List, Optional
import base64

from product_retrival_computer_vision import (
    get_detector,
    get_feature_extractor,
    get_search_engine
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Fashion CV Service", version="1.0.0")

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize CV components (lazy loading)
_detector = None
_feature_extractor = None
_search_engine = None


def get_detector_instance():
    global _detector
    if _detector is None:
        logger.info("Initializing detector...")
        _detector = get_detector()
    return _detector


def get_feature_extractor_instance():
    global _feature_extractor
    if _feature_extractor is None:
        logger.info("Initializing feature extractor...")
        _feature_extractor = get_feature_extractor()
    return _feature_extractor


def get_search_engine_instance():
    global _search_engine
    if _search_engine is None:
        logger.info("Initializing search engine...")
        _search_engine = get_search_engine()
    return _search_engine


# Request/Response models
class DetectedItemResponse(BaseModel):
    category: str
    confidence: float
    bbox: List[float]  # [x1, y1, x2, y2]
    cropped_image_base64: str


class SearchProductRequest(BaseModel):
    image_base64: str
    top_k: int = 5
    category_filter: Optional[str] = None


class SearchResult(BaseModel):
    product_id: str
    similarity_score: float
    metadata: dict


class SearchResponse(BaseModel):
    results: List[SearchResult]


@app.get("/")
async def root():
    return {
        "service": "Fashion CV Service",
        "version": "1.0.0",
        "status": "running"
    }


@app.get("/health")
async def health():
    return {"status": "healthy"}


@app.post("/detect", response_model=List[DetectedItemResponse])
async def detect_items(file: UploadFile = File(...)):
    """
    Detect fashion items in an uploaded image
    Returns bounding boxes and cropped images for each detected item
    """
    try:
        # Read image
        contents = await file.read()
        nparr = np.frombuffer(contents, np.uint8)
        image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        if image is None:
            raise HTTPException(status_code=400, detail="Invalid image file")

        # Detect items
        detector = get_detector_instance()
        detected_items = detector.detect_items(image)

        # Convert to response format
        results = []
        for item in detected_items:
            # Encode cropped image to base64
            _, buffer = cv2.imencode('.jpg', item.cropped_image)
            cropped_base64 = base64.b64encode(buffer).decode('utf-8')

            results.append(DetectedItemResponse(
                category=item.category,
                confidence=item.confidence,
                bbox=item.bbox,
                cropped_image_base64=cropped_base64
            ))

        logger.info(f"Detected {len(results)} items")
        return results

    except Exception as e:
        logger.error(f"Error in detection: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/search", response_model=SearchResponse)
async def search_similar_products(request: SearchProductRequest):
    """
    Search for similar products given an image
    Returns top-K similar products from vector database
    """
    try:
        # Decode base64 image
        image_bytes = base64.b64decode(request.image_base64)
        nparr = np.frombuffer(image_bytes, np.uint8)
        image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        if image is None:
            raise HTTPException(status_code=400, detail="Invalid image data")

        # Extract features
        extractor = get_feature_extractor_instance()
        features = extractor.extract_all_features(image)
        embedding = features['combined']

        # Search for similar products
        search_engine = get_search_engine_instance()
        results = search_engine.search_similar(
            query_embedding=embedding,
            top_k=request.top_k,
            category_filter=request.category_filter
        )

        # Convert to response format
        search_results = []
        for result in results:
            search_results.append(SearchResult(
                product_id=result.product_id,
                similarity_score=result.similarity_score,
                metadata=result.metadata
            ))

        logger.info(f"Found {len(search_results)} similar products")
        return SearchResponse(results=search_results)

    except Exception as e:
        logger.error(f"Error in search: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/analyze-outfit")
async def analyze_outfit(file: UploadFile = File(...), top_k: int = 1):
    """
    Complete pipeline: detect items in outfit and find similar products for each
    """
    try:
        # Read image
        contents = await file.read()
        nparr = np.frombuffer(contents, np.uint8)
        image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        if image is None:
            raise HTTPException(status_code=400, detail="Invalid image file")

        # Detect items
        detector = get_detector_instance()
        detected_items = detector.detect_items(image)

        if not detected_items:
            return {"items": [], "message": "No fashion items detected"}

        # Extract features and search for each item
        extractor = get_feature_extractor_instance()
        search_engine = get_search_engine_instance()

        results = []
        for item in detected_items:
            features = extractor.extract_all_features(item.cropped_image)
            embedding = features['combined']

            similar_products = search_engine.search_similar(
                query_embedding=embedding,
                top_k=top_k,
                category_filter=None  # No category filter - use embeddings only
            )

            # Encode cropped image
            _, buffer = cv2.imencode('.jpg', item.cropped_image)
            cropped_base64 = base64.b64encode(buffer).decode('utf-8')

            results.append({
                "detected_item": {
                    "category": item.category,
                    "confidence": item.confidence,
                    "bbox": item.bbox,
                    "cropped_image_base64": cropped_base64
                },
                "similar_products": [
                    {
                        "product_id": p.product_id,
                        "similarity_score": p.similarity_score,
                        "metadata": p.metadata
                    }
                    for p in similar_products
                ]
            })

        logger.info(f"Analyzed outfit: {len(results)} items detected")
        return {"items": results}

    except Exception as e:
        logger.error(f"Error in outfit analysis: {e}")
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
