#!/usr/bin/env python3
"""
Script to retrieve a post by ID (either post_id or redis_id).

Usage:
    python3 get_post_by_id.py <post_id_or_redis_id>
"""
import os
import sys
from dotenv import load_dotenv
import psycopg2
import redis
import json

# Load environment variables
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

def get_post_by_id(identifier: str):
    """Get post by post_id or redis_id"""

    if not DATABASE_URL:
        print("❌ DATABASE_URL not found in environment")
        sys.exit(1)

    try:
        # First, try Redis to see if it's a redis_id
        print(f"\n🔍 Checking Redis for redis_id: {identifier}...")
        try:
            r = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)
            status_key = f"post_status:{identifier}"
            status_data = r.get(status_key)

            if status_data:
                status = json.loads(status_data)
                print(f"✅ Found Redis status:")
                print(f"   Status: {status.get('status')}")
                print(f"   Message: {status.get('message')}")
                if 'post_id' in status:
                    post_id = status['post_id']
                    print(f"   Post ID: {post_id}")
                    identifier = post_id  # Use this to query the database
                else:
                    print("   ⚠️  No post_id in Redis yet (post still processing or failed)")
            else:
                print("   ℹ️  Not found in Redis (expired or not a redis_id)")
        except Exception as redis_error:
            print(f"   ⚠️  Redis error: {redis_error}")

        # Query database for post
        print(f"\n🔍 Querying database for post_id: {identifier}...")
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()

        # Get post details
        cur.execute("""
            SELECT p.id, p.user_id, p.title, p.caption, p.location,
                   p.ai_sentence, p.created_at, u.name, u.username
            FROM posts p
            JOIN users u ON p.user_id = u.id
            WHERE p.id = %s
        """, (identifier,))

        post = cur.fetchone()

        if not post:
            print("❌ Post not found in database")
            print("\n💡 Try searching recent posts by user:")
            print("   python3 get_architavn_posts.py")
            cur.close()
            conn.close()
            return

        post_id, user_id, title, caption, location, ai_sentence, created_at, name, username = post

        print(f"\n✅ Found post!\n")
        print("=" * 80)
        print(f"\n📝 POST DETAILS:")
        print(f"   Post ID: {post_id}")
        print(f"   User: {name} (@{username})")
        print(f"   User ID: {user_id}")
        print(f"   Title: {title or '(no title)'}")
        print(f"   Location: {location or '(no location)'}")

        if caption:
            print(f"\n📄 Caption:")
            print(f"   {caption}")

        if ai_sentence:
            print(f"\n✨ AI Announcement:")
            print(f"   {ai_sentence}")

        print(f"\n⏰ Created: {created_at}")

        # Get media
        cur.execute("""
            SELECT id, media_url, created_at
            FROM post_media
            WHERE post_id = %s
            ORDER BY created_at
        """, (post_id,))

        media_items = cur.fetchall()

        if media_items:
            print(f"\n🖼️  MEDIA ({len(media_items)} file(s)):")
            for idx, (media_id, media_url, media_created) in enumerate(media_items, 1):
                print(f"\n   [{idx}] Media ID: {media_id}")
                # Show URL preview
                if media_url.startswith('data:image'):
                    print(f"       Type: Base64 encoded image")
                    print(f"       Size: {len(media_url)} characters")
                else:
                    print(f"       URL: {media_url[:100]}...")
                print(f"       Created: {media_created}")
        else:
            print(f"\n🖼️  MEDIA: None")

        # Get engagement stats
        cur.execute("SELECT COUNT(*) FROM likes WHERE post_id = %s", (post_id,))
        like_count = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM comments WHERE post_id = %s", (post_id,))
        comment_count = cur.fetchone()[0]

        print(f"\n📊 ENGAGEMENT:")
        print(f"   Likes: {like_count}")
        print(f"   Comments: {comment_count}")

        print("\n" + "=" * 80)

        cur.close()
        conn.close()

    except psycopg2.Error as e:
        print(f"❌ Database error: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python3 get_post_by_id.py <post_id_or_redis_id>")
        print("\nExample:")
        print("  python3 get_post_by_id.py d28fc897-3d92-4bf2-a6a6-d91a5013e0ab")
        sys.exit(1)

    identifier = sys.argv[1]

    print("=" * 80)
    print("Get Post by ID")
    print("=" * 80)

    get_post_by_id(identifier)
