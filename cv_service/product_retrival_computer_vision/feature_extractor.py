"""
Feature Extractor for Fashion Items
Extracts visual features and deep embeddings using pre-trained CNNs
"""

import cv2
import numpy as np
import torch
import torchvision.transforms as transforms
from torchvision.models import resnet50, ResNet50_Weights
from PIL import Image
import logging
from typing import Dict

logger = logging.getLogger(__name__)


class FashionFeatureExtractor:
    """
    Extract visual features and embeddings from fashion items
    Uses ResNet50 pre-trained on ImageNet
    """

    def __init__(self, model_name: str = "resnet50"):
        """
        Initialize feature extractor

        Args:
            model_name: Name of the model to use (resnet50, efficientnet, etc.)
        """
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        logger.info(f"🖥️ Using device: {self.device}")

        # Load pre-trained model
        if model_name == "resnet50":
            weights = ResNet50_Weights.IMAGENET1K_V2
            self.model = resnet50(weights=weights)
            # Remove the final classification layer to get embeddings
            self.model = torch.nn.Sequential(*list(self.model.children())[:-1])
        else:
            raise ValueError(f"Model {model_name} not supported yet")

        self.model = self.model.to(self.device)
        self.model.eval()

        # Image preprocessing
        self.transform = transforms.Compose([
            transforms.Resize(256),
            transforms.CenterCrop(224),
            transforms.ToTensor(),
            transforms.Normalize(
                mean=[0.485, 0.456, 0.406],
                std=[0.229, 0.224, 0.225]
            )
        ])

        logger.info(f"✅ Loaded {model_name} feature extractor")

    def extract_embedding(self, image: np.ndarray) -> np.ndarray:
        """
        Extract deep embedding from a fashion item image

        Args:
            image: OpenCV image (BGR format) or PIL Image

        Returns:
            Embedding vector (2048-dimensional for ResNet50)
        """
        try:
            # Convert BGR to RGB if needed
            if isinstance(image, np.ndarray):
                if len(image.shape) == 2:  # Grayscale
                    image = cv2.cvtColor(image, cv2.COLOR_GRAY2RGB)
                elif image.shape[2] == 3:  # BGR
                    image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)

                # Convert to PIL Image
                image = Image.fromarray(image)

            # Preprocess and extract features
            img_tensor = self.transform(image).unsqueeze(0).to(self.device)

            with torch.no_grad():
                embedding = self.model(img_tensor)
                embedding = embedding.squeeze().cpu().numpy()

            return embedding

        except Exception as e:
            logger.error(f"❌ Error extracting embedding: {e}")
            return np.zeros(2048)  # Return zero vector on error

    def extract_dominant_color(self, image: np.ndarray) -> str:
        """
        Extract dominant color name from image

        Args:
            image: OpenCV image (BGR)

        Returns:
            Color name (e.g., "black", "blue", "red")
        """
        try:
            # Convert to HSV
            hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)

            # Get average hue, saturation, value
            h, s, v = cv2.split(hsv)
            avg_h = np.mean(h)
            avg_s = np.mean(s)
            avg_v = np.mean(v)

            # Determine color name based on HSV values
            if avg_v < 50:  # Very dark
                return "black"
            elif avg_v > 200 and avg_s < 50:  # Very light
                return "white"
            elif avg_s < 50:  # Low saturation = grey
                return "grey"
            else:
                # Determine hue-based color
                if avg_h < 10 or avg_h > 170:
                    return "red"
                elif 10 <= avg_h < 25:
                    return "orange"
                elif 25 <= avg_h < 35:
                    return "yellow"
                elif 35 <= avg_h < 85:
                    return "green"
                elif 85 <= avg_h < 130:
                    return "blue"
                elif 130 <= avg_h < 160:
                    return "purple"
                else:
                    return "pink"

        except Exception as e:
            logger.error(f"❌ Error extracting dominant color: {e}")
            return "unknown"

    def extract_color_histogram(self, image: np.ndarray, bins: int = 32) -> np.ndarray:
        """
        Extract color histogram features

        Args:
            image: OpenCV image (BGR)
            bins: Number of bins per channel

        Returns:
            Color histogram feature vector
        """
        try:
            # Convert to HSV for better color representation
            hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)

            # Compute histogram for each channel
            hist_h = cv2.calcHist([hsv], [0], None, [bins], [0, 180])
            hist_s = cv2.calcHist([hsv], [1], None, [bins], [0, 256])
            hist_v = cv2.calcHist([hsv], [2], None, [bins], [0, 256])

            # Normalize
            hist_h = cv2.normalize(hist_h, hist_h).flatten()
            hist_s = cv2.normalize(hist_s, hist_s).flatten()
            hist_v = cv2.normalize(hist_v, hist_v).flatten()

            # Concatenate
            histogram = np.concatenate([hist_h, hist_s, hist_v])

            return histogram

        except Exception as e:
            logger.error(f"❌ Error extracting color histogram: {e}")
            return np.zeros(bins * 3)

    def extract_all_features(self, image: np.ndarray) -> Dict[str, np.ndarray]:
        """
        Extract all features from a fashion item

        Args:
            image: OpenCV image (BGR)

        Returns:
            Dictionary with different feature types
        """
        # Extract dominant color name
        dominant_color = self.extract_dominant_color(image)

        features = {
            'deep_embedding': self.extract_embedding(image),
            'color_histogram': self.extract_color_histogram(image),
            'dominant_color': dominant_color  # Color name for filtering
        }

        # Combine into single feature vector
        deep_emb = features['deep_embedding']
        color_hist = features['color_histogram']

        # Normalize each component
        deep_emb_norm = deep_emb / (np.linalg.norm(deep_emb) + 1e-8)
        color_hist_norm = color_hist / (np.linalg.norm(color_hist) + 1e-8)

        # Weight the features (adjust weights based on importance)
        combined = np.concatenate([
            deep_emb_norm * 0.8,  # Deep features weighted higher
            color_hist_norm * 0.2  # Color features weighted lower
        ])

        features['combined'] = combined

        return features


# Global extractor instance (lazy loaded)
_extractor_instance = None


def get_feature_extractor() -> FashionFeatureExtractor:
    """Get or create global feature extractor instance"""
    global _extractor_instance
    if _extractor_instance is None:
        _extractor_instance = FashionFeatureExtractor()
    return _extractor_instance
