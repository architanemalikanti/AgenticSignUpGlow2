"""
Vector Search Engine using Pinecone
Searches for similar fashion items using cosine similarity
"""

import os
import logging
import numpy as np
from typing import List, Dict, Optional
from dataclasses import dataclass
from pinecone import Pinecone, ServerlessSpec

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    """Similar fashion item from search"""
    product_id: str
    product_name: str
    brand: str
    retailer: str
    price: str
    image_url: str
    product_url: str
    similarity_score: float
    category: str


class FashionVectorSearch:
    """
    Vector similarity search for fashion items
    Uses Pinecone for fast approximate nearest neighbor search
    """

    def __init__(
        self,
        index_name: str = "fashion-items-glow",
        dimension: int = 2048,
        metric: str = "cosine"
    ):
        """
        Initialize Pinecone vector search

        Args:
            index_name: Name of the Pinecone index
            dimension: Dimension of embeddings (2048 for ResNet50)
            metric: Distance metric (cosine, euclidean, dotproduct)
        """
        # Get Pinecone API key
        api_key = os.getenv("PINECONE_API_KEY")
        if not api_key:
            raise ValueError("PINECONE_API_KEY not found in environment")

        # Initialize Pinecone
        self.pc = Pinecone(api_key=api_key)
        self.index_name = index_name
        self.dimension = dimension

        # Create index if it doesn't exist
        if index_name not in self.pc.list_indexes().names():
            logger.info(f"📦 Creating new Pinecone index: {index_name}")
            self.pc.create_index(
                name=index_name,
                dimension=dimension,
                metric=metric,
                spec=ServerlessSpec(
                    cloud='aws',
                    region='us-east-1'
                )
            )

        # Connect to index
        self.index = self.pc.Index(index_name)
        logger.info(f"✅ Connected to Pinecone index: {index_name}")

    def upsert_product(
        self,
        product_id: str,
        embedding: np.ndarray,
        metadata: Dict
    ):
        """
        Add or update a product in the vector database

        Args:
            product_id: Unique product ID
            embedding: Product embedding vector
            metadata: Product info (name, brand, price, url, etc.)
        """
        try:
            # Convert numpy array to list
            if isinstance(embedding, np.ndarray):
                embedding = embedding.tolist()

            # Upsert to Pinecone
            self.index.upsert(
                vectors=[(product_id, embedding, metadata)]
            )

            logger.debug(f"✅ Upserted product {product_id}")

        except Exception as e:
            logger.error(f"❌ Error upserting product: {e}")

    def upsert_batch(self, products: List[Dict]):
        """
        Batch upsert multiple products

        Args:
            products: List of dicts with 'id', 'embedding', 'metadata'
        """
        try:
            vectors = [
                (
                    p['id'],
                    p['embedding'].tolist() if isinstance(p['embedding'], np.ndarray) else p['embedding'],
                    p['metadata']
                )
                for p in products
            ]

            self.index.upsert(vectors=vectors)
            logger.info(f"✅ Batch upserted {len(products)} products")

        except Exception as e:
            logger.error(f"❌ Error batch upserting: {e}")

    def search_similar(
        self,
        query_embedding: np.ndarray,
        top_k: int = 10,
        category_filter: Optional[str] = None,
        min_price: Optional[float] = None,
        max_price: Optional[float] = None
    ) -> List[SearchResult]:
        """
        Search for similar fashion items

        Args:
            query_embedding: Query embedding vector
            top_k: Number of results to return
            category_filter: Filter by category (e.g., "shirt", "shoes")
            min_price: Minimum price filter
            max_price: Maximum price filter

        Returns:
            List of SearchResult objects
        """
        try:
            # Convert numpy to list
            if isinstance(query_embedding, np.ndarray):
                query_embedding = query_embedding.tolist()

            # Build filter
            filter_dict = {}
            if category_filter:
                filter_dict['category'] = {"$eq": category_filter}
            if min_price is not None or max_price is not None:
                filter_dict['price_numeric'] = {}
                if min_price is not None:
                    filter_dict['price_numeric']['$gte'] = min_price
                if max_price is not None:
                    filter_dict['price_numeric']['$lte'] = max_price

            # Query Pinecone
            results = self.index.query(
                vector=query_embedding,
                top_k=top_k,
                include_metadata=True,
                filter=filter_dict if filter_dict else None
            )

            # Parse results
            search_results = []
            for match in results['matches']:
                metadata = match.get('metadata', {})

                search_results.append(SearchResult(
                    product_id=match['id'],
                    product_name=metadata.get('name', 'Unknown'),
                    brand=metadata.get('brand', 'Unknown'),
                    retailer=metadata.get('retailer', 'Unknown'),
                    price=metadata.get('price', 'N/A'),
                    image_url=metadata.get('image_url', ''),
                    product_url=metadata.get('product_url', ''),
                    similarity_score=float(match['score']),
                    category=metadata.get('category', 'unknown')
                ))

            logger.info(f"🔍 Found {len(search_results)} similar items")
            return search_results

        except Exception as e:
            logger.error(f"❌ Error searching: {e}")
            return []

    def delete_product(self, product_id: str):
        """Delete a product from the index"""
        try:
            self.index.delete(ids=[product_id])
            logger.info(f"🗑️ Deleted product {product_id}")
        except Exception as e:
            logger.error(f"❌ Error deleting product: {e}")

    def get_index_stats(self) -> Dict:
        """Get statistics about the index"""
        try:
            stats = self.index.describe_index_stats()
            return {
                'total_vectors': stats.get('total_vector_count', 0),
                'dimension': stats.get('dimension', 0),
                'index_fullness': stats.get('index_fullness', 0)
            }
        except Exception as e:
            logger.error(f"❌ Error getting stats: {e}")
            return {}


# Global search engine instance (lazy loaded)
_search_engine_instance = None


def get_search_engine() -> FashionVectorSearch:
    """Get or create global search engine instance"""
    global _search_engine_instance
    if _search_engine_instance is None:
        _search_engine_instance = FashionVectorSearch()
    return _search_engine_instance
