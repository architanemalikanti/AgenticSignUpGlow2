#!/usr/bin/env python3
"""
Test Outfit Retrieval Performance
Measures how long it takes to fetch 1, 4, and 10 outfits
"""

import requests
import time
import json

# Your backend URL
BACKEND_URL = "http://your-ec2-ip:8000"  # ← Change this!
TEST_USER_ID = "performance_test_user"


def test_outfit_retrieval(count: int):
    """Test fetching N outfits and measure time"""
    print(f"\n{'='*60}")
    print(f"Testing: Fetch {count} outfit(s)")
    print('='*60)

    start_time = time.time()

    try:
        response = requests.get(
            f"{BACKEND_URL}/outfits/next",
            params={
                "user_id": TEST_USER_ID,
                "count": count
            },
            timeout=60
        )

        end_time = time.time()
        duration = end_time - start_time

        if response.status_code == 200:
            data = response.json()
            print(f"✅ SUCCESS")
            print(f"   Time: {duration:.2f}s ({duration*1000:.0f}ms)")
            print(f"   Outfits returned: {len(data)}")

            # Show first outfit as sample
            if data:
                first = data[0]
                print(f"\n   Sample outfit:")
                print(f"   - Title: {first.get('title', 'N/A')}")
                print(f"   - Products: {len(first.get('products', []))}")
                print(f"   - Image: {first.get('image_url', 'N/A')[:50]}...")

            return {
                "count": count,
                "duration": duration,
                "success": True,
                "outfits_returned": len(data)
            }
        else:
            print(f"❌ FAILED")
            print(f"   Status: {response.status_code}")
            print(f"   Error: {response.text[:200]}")
            return {
                "count": count,
                "duration": duration,
                "success": False,
                "error": response.text[:200]
            }

    except Exception as e:
        end_time = time.time()
        duration = end_time - start_time
        print(f"❌ ERROR: {e}")
        return {
            "count": count,
            "duration": duration,
            "success": False,
            "error": str(e)
        }


def main():
    print("\n🎯 OUTFIT RETRIEVAL PERFORMANCE TEST")
    print(f"Backend: {BACKEND_URL}")
    print(f"User ID: {TEST_USER_ID}")

    # Test different counts
    test_counts = [1, 4, 10]
    results = []

    for count in test_counts:
        result = test_outfit_retrieval(count)
        results.append(result)
        time.sleep(1)  # Brief pause between tests

    # Summary
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)

    successful = [r for r in results if r['success']]

    if successful:
        print("\n📊 Performance Results:")
        print(f"{'Count':<10} {'Time':<15} {'Avg per outfit':<20}")
        print("-" * 45)

        for r in successful:
            avg_per_outfit = r['duration'] / r['outfits_returned'] if r['outfits_returned'] > 0 else 0
            print(f"{r['count']:<10} {r['duration']:.2f}s ({r['duration']*1000:.0f}ms)     {avg_per_outfit:.2f}s ({avg_per_outfit*1000:.0f}ms) per outfit")

        print("\n💡 Notes:")
        print("- First call may be slower (CV service warmup)")
        print("- Subsequent calls use cached products (faster)")
        print("- CV detection + Pinecone search happens in background")

    else:
        print("\n⚠️ All tests failed. Check:")
        print("- Is your backend running?")
        print("- Is CV service (Colab) running?")
        print("- Is CV_SERVICE_URL set in .env?")

    # Failed tests
    failed = [r for r in results if not r['success']]
    if failed:
        print(f"\n❌ {len(failed)} test(s) failed:")
        for r in failed:
            print(f"   Count {r['count']}: {r.get('error', 'Unknown error')[:100]}")


if __name__ == "__main__":
    main()
