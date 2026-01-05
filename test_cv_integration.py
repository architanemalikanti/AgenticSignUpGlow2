#!/usr/bin/env python3
"""
Test CV Service Integration
Run this on your main backend to verify CV service is working
"""

import asyncio
import sys
import os
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from services.cv_client import get_cv_client


async def test_health_check():
    """Test 1: Health check"""
    print("\n" + "="*50)
    print("TEST 1: Health Check")
    print("="*50)

    try:
        cv = get_cv_client()
        print(f"CV Service URL: {cv.base_url}")

        is_healthy = await cv.health_check()

        if is_healthy:
            print("✅ SUCCESS: CV service is healthy and reachable!")
            return True
        else:
            print("❌ FAILED: CV service is not healthy")
            return False

    except Exception as e:
        print(f"❌ ERROR: {e}")
        return False


async def test_detect_items(image_path: str = None):
    """Test 2: Detect items in image"""
    print("\n" + "="*50)
    print("TEST 2: Detect Fashion Items")
    print("="*50)

    if not image_path:
        print("⏭️  SKIPPED: No test image provided")
        print("   To test detection, run: python test_cv_integration.py <image_path>")
        return None

    if not os.path.exists(image_path):
        print(f"❌ ERROR: Image not found: {image_path}")
        return False

    try:
        cv = get_cv_client()
        print(f"Testing with image: {image_path}")

        results = await cv.detect_items(image_path=image_path)

        print(f"✅ SUCCESS: Detected {len(results)} items")
        for i, item in enumerate(results, 1):
            print(f"   Item {i}: {item['category']} (confidence: {item['confidence']:.2f})")

        return True

    except Exception as e:
        print(f"❌ ERROR: {e}")
        return False


async def test_analyze_outfit(image_path: str = None):
    """Test 3: Full pipeline - analyze outfit"""
    print("\n" + "="*50)
    print("TEST 3: Analyze Outfit (Full Pipeline)")
    print("="*50)

    if not image_path:
        print("⏭️  SKIPPED: No test image provided")
        return None

    if not os.path.exists(image_path):
        print(f"❌ ERROR: Image not found: {image_path}")
        return False

    try:
        cv = get_cv_client()
        print(f"Testing full pipeline with: {image_path}")

        result = await cv.analyze_outfit(image_path=image_path, top_k=3)

        items = result.get('items', [])

        if not items:
            print("⚠️  No items detected in image")
            return True

        print(f"✅ SUCCESS: Analyzed outfit with {len(items)} items")

        for i, item in enumerate(items, 1):
            detected = item['detected_item']
            similar = item['similar_products']

            print(f"\n   Item {i}: {detected['category']} (confidence: {detected['confidence']:.2f})")
            print(f"   Found {len(similar)} similar products:")

            for j, product in enumerate(similar[:3], 1):
                metadata = product['metadata']
                print(f"      {j}. {metadata.get('name', 'N/A')} - Similarity: {product['similarity_score']:.3f}")

        return True

    except Exception as e:
        print(f"❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    """Run all tests"""
    print("\n" + "🔍 CV SERVICE INTEGRATION TESTS" + "\n")

    # Get test image path from command line args
    image_path = sys.argv[1] if len(sys.argv) > 1 else None

    results = []

    # Test 1: Health check (always run)
    results.append(await test_health_check())

    # Test 2 & 3: Only if image provided
    if image_path:
        results.append(await test_detect_items(image_path))
        results.append(await test_analyze_outfit(image_path))
    else:
        print("\n" + "💡 TIP: Provide an outfit image to test detection:")
        print("   python test_cv_integration.py path/to/outfit.jpg")

    # Summary
    print("\n" + "="*50)
    print("SUMMARY")
    print("="*50)

    passed = sum(1 for r in results if r is True)
    failed = sum(1 for r in results if r is False)
    skipped = sum(1 for r in results if r is None)

    print(f"✅ Passed: {passed}")
    if failed > 0:
        print(f"❌ Failed: {failed}")
    if skipped > 0:
        print(f"⏭️  Skipped: {skipped}")

    if failed == 0 and passed > 0:
        print("\n🎉 All tests passed! CV service is ready to use.")
        sys.exit(0)
    elif failed > 0:
        print("\n⚠️  Some tests failed. Check the errors above.")
        sys.exit(1)
    else:
        print("\n⚠️  No tests completed. Check your configuration.")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
