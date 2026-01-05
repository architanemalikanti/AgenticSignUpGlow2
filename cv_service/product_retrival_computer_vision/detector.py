"""
Fashion Item Detector using YOLO
Detects and segments individual clothing items from outfit images
"""

import cv2
import numpy as np
from ultralytics import YOLO
import logging
from typing import List, Tuple, Union
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class DetectedItem:
    """Detected fashion item with bounding box and metadata"""
    category: str          # e.g., "shirt", "pants", "shoes"
    bbox: Tuple[int, int, int, int]  # (x1, y1, x2, y2)
    confidence: float
    segmentation_mask: np.ndarray  # Binary mask for the item
    cropped_image: np.ndarray      # Isolated item image


class FashionDetector:
    """
    YOLO-based fashion item detector
    Detects clothing items and extracts clean bounding boxes
    """

    def __init__(self, model_path: str = "models/yolov8_fashion.pt"):
        """
        Initialize the detector

        Args:
            model_path: Path to trained YOLO model weights
        """
        try:
            self.model = YOLO(model_path)
            logger.info(f"✅ Loaded YOLO model from {model_path}")
        except Exception as e:
            logger.warning(f"⚠️ Could not load custom model: {e}")
            logger.info("📦 Using YOLOv8 base model (download on first use)")
            self.model = YOLO('yolov8n.pt')  # Fallback to pretrained

        # Fashion item categories (customize based on your training)
        self.fashion_categories = {
            0: "shirt",
            1: "pants",
            2: "dress",
            3: "shoes",
            4: "jacket",
            5: "bag",
            6: "hat",
            7: "accessories"
        }

    def detect_items(self, image_input: Union[str, np.ndarray], conf_threshold: float = 0.5) -> List[DetectedItem]:
        """
        Detect fashion items in an image

        Args:
            image_input: Either a path to the image file (str) or numpy array (cv2 image)
            conf_threshold: Confidence threshold for detections

        Returns:
            List of DetectedItem objects
        """
        try:
            # Read image (handle both file path and numpy array)
            if isinstance(image_input, str):
                image = cv2.imread(image_input)
                if image is None:
                    raise ValueError(f"Could not read image from {image_input}")
            elif isinstance(image_input, np.ndarray):
                image = image_input
            else:
                raise ValueError(f"Invalid image_input type: {type(image_input)}. Expected str or np.ndarray")

            # Run YOLO detection
            results = self.model(image, conf=conf_threshold)

            detected_items = []
            for result in results:
                boxes = result.boxes
                masks = result.masks if hasattr(result, 'masks') else None

                for i, box in enumerate(boxes):
                    # Get bounding box coordinates
                    x1, y1, x2, y2 = map(int, box.xyxy[0])
                    confidence = float(box.conf[0])
                    class_id = int(box.cls[0])

                    # Get category name
                    category = self.fashion_categories.get(class_id, f"item_{class_id}")

                    # Extract segmentation mask (if available)
                    if masks is not None and len(masks) > i:
                        mask = masks[i].data[0].cpu().numpy()
                        mask = cv2.resize(mask, (image.shape[1], image.shape[0]))
                    else:
                        # Create rectangular mask if segmentation not available
                        mask = np.zeros(image.shape[:2], dtype=np.uint8)
                        mask[y1:y2, x1:x2] = 255

                    # Crop item from image
                    cropped = image[y1:y2, x1:x2].copy()

                    # Remove background using mask
                    mask_crop = mask[y1:y2, x1:x2]
                    if mask_crop.shape[:2] == cropped.shape[:2]:
                        cropped[mask_crop == 0] = 255  # White background

                    detected_items.append(DetectedItem(
                        category=category,
                        bbox=(x1, y1, x2, y2),
                        confidence=confidence,
                        segmentation_mask=mask,
                        cropped_image=cropped
                    ))

            logger.info(f"🔍 Detected {len(detected_items)} fashion items")
            return detected_items

        except Exception as e:
            logger.error(f"❌ Error detecting items: {e}")
            return []


# Global detector instance (lazy loaded)
_detector_instance = None


def get_detector() -> FashionDetector:
    """Get or create global detector instance"""
    global _detector_instance
    if _detector_instance is None:
        _detector_instance = FashionDetector()
    return _detector_instance
