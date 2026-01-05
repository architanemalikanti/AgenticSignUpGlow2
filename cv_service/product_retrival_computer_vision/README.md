# Fashion Product Retrieval with Computer Vision

Complete CV pipeline for detecting fashion items in outfit images and finding similar products.

## Pipeline Overview

```
Outfit Image → YOLO Detection → Feature Extraction → Vector Search → Similar Products
```

### 1. Object Detection (YOLO)
- Detects individual clothing items in outfit images
- Segments out background noise
- Extracts clean bounding boxes

### 2. Feature Extraction (ResNet50)
- Extracts 2048-dim deep embeddings
- Computes color histograms
- Combines visual features

### 3. Vector Search (Pinecone)
- Stores product embeddings in vector database
- Fast cosine similarity search
- Returns top-K similar products

## Setup

### Install Dependencies
```bash
pip install -r requirements.txt
```

### Environment Variables
```bash
# Required
export PINECONE_API_KEY="your_pinecone_api_key"

# Optional
export SERPAPI_API_KEY="your_serpapi_key"  # For Google Shopping fallback
```

### Download YOLO Model (Optional)
Place custom trained fashion YOLO model at:
```
models/yolov8_fashion.pt
```

If not provided, will use pretrained YOLOv8n as fallback.

## Usage

### Complete Pipeline Example

```python
from product_retrival_computer_vision import (
    get_detector,
    get_feature_extractor,
    get_search_engine
)

# Initialize pipeline
detector = get_detector()
extractor = get_feature_extractor()
search_engine = get_search_engine()

# 1. Detect fashion items
detected_items = detector.detect_items("outfit.jpg")

# 2. Extract features for each item
for item in detected_items:
    features = extractor.extract_all_features(item.cropped_image)
    embedding = features['combined']

    # 3. Search for similar products
    results = search_engine.search_similar(
        query_embedding=embedding,
        top_k=5,
        category_filter=item.category
    )

    for result in results:
        print(f"  {result.product_name} - {result.brand} - {result.price}")
        print(f"  Similarity: {result.similarity_score:.3f}")
        print(f"  {result.product_url}")
```

### Index Products to Pinecone

```python
from product_retrival_computer_vision import get_feature_extractor, get_search_engine
import cv2

extractor = get_feature_extractor()
search_engine = get_search_engine()

# Load product image
product_image = cv2.imread("product.jpg")

# Extract embedding
features = extractor.extract_all_features(product_image)
embedding = features['combined']

# Add to vector database
search_engine.upsert_product(
    product_id="PROD_12345",
    embedding=embedding,
    metadata={
        'name': 'Black Leather Jacket',
        'brand': 'Zara',
        'retailer': 'Zara',
        'price': '$89.99',
        'price_numeric': 89.99,
        'category': 'jacket',
        'image_url': 'https://...',
        'product_url': 'https://...'
    }
)
```

### Batch Indexing

```python
products = []
for product_data in your_product_catalog:
    image = cv2.imread(product_data['image_path'])
    features = extractor.extract_all_features(image)

    products.append({
        'id': product_data['id'],
        'embedding': features['combined'],
        'metadata': {
            'name': product_data['name'],
            'brand': product_data['brand'],
            'price': product_data['price'],
            'category': product_data['category'],
            # ... other metadata
        }
    })

# Batch upsert (faster)
search_engine.upsert_batch(products)
```

## Integration with Outfit Feed

The CV pipeline integrates with the outfit feed in `api/outfit_endpoints.py`:

```python
from product_retrival_computer_vision import get_detector, get_feature_extractor, get_search_engine

def analyze_outfit_cv(outfit_image_url: str):
    # 1. Detect items
    detector = get_detector()
    items = detector.detect_items(outfit_image_url)

    # 2. Extract features and search
    extractor = get_feature_extractor()
    search_engine = get_search_engine()

    products = []
    for item in items:
        features = extractor.extract_all_features(item.cropped_image)
        results = search_engine.search_similar(features['combined'], top_k=3)
        products.extend(results)

    return products
```

## Model Files

Place model weights in the `models/` directory:
- `yolov8_fashion.pt` - Custom trained YOLO model for fashion detection
- Other models download automatically on first use

## Performance

- **Detection**: ~100ms per image (GPU), ~500ms (CPU)
- **Feature Extraction**: ~50ms per item (GPU), ~200ms (CPU)
- **Vector Search**: <10ms for 1M vectors

## Next Steps

1. **Train Custom YOLO**: Fine-tune on fashion dataset (DeepFashion2, etc.)
2. **Fashion-Specific Embeddings**: Use FashionNet or train custom embeddings
3. **Attribute Detection**: Add collar type, sleeve length, pattern detection
4. **Product Catalog**: Scrape and index products from fashion retailers
