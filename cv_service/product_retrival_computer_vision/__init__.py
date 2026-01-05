"""
Fashion Product Retrieval using Computer Vision
Complete pipeline: Detection → Feature Extraction → Vector Search
"""

from .detector import FashionDetector, DetectedItem, get_detector
from .feature_extractor import FashionFeatureExtractor, get_feature_extractor
from .vector_search import FashionVectorSearch, SearchResult, get_search_engine

__all__ = [
    'FashionDetector',
    'DetectedItem',
    'get_detector',
    'FashionFeatureExtractor',
    'get_feature_extractor',
    'FashionVectorSearch',
    'SearchResult',
    'get_search_engine',
]

__version__ = '1.0.0'
