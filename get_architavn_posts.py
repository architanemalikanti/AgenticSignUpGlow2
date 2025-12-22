#!/usr/bin/env python3
"""
Script to retrieve and display architavn's posts from the database.

Usage:
    python3 get_architavn_posts.py
"""
import os
import sys
from dotenv import load_dotenv
import psycopg2
from datetime import datetime

# Load environment variables
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

def get_posts():
    """Get all of architavn's posts"""

    if not DATABASE_URL:
        print("❌ DATABASE_URL not found in environment")
        sys.exit(1)

    try:
        # Connect to database
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()

        print("🔍 Finding architavn's user...")

        # Find architavn's user_id
        cur.execute("SELECT id, username, name FROM users WHERE username = %s", ("architavn",))
        user = cur.fetchone()

        if not user:
            print("❌ User 'architavn' not found")
            cur.close()
            conn.close()
            sys.exit(1)

        user_id, username, name = user
        print(f"✅ Found user: {name} (@{username}, ID: {user_id})")

        # Get all posts
        print(f"\n🔍 Fetching all posts...")
        cur.execute("""
            SELECT id, title, caption, location, ai_sentence, created_at
            FROM posts
            WHERE user_id = %s
            ORDER BY created_at DESC
        """, (user_id,))

        posts = cur.fetchall()

        if not posts:
            print("❌ No posts found for this user")
            cur.close()
            conn.close()
            return

        print(f"\n📋 Found {len(posts)} post(s):\n")
        print("=" * 80)

        for post_id, title, caption, location, ai_sentence, created_at in posts:
            print(f"\n📝 Post ID: {post_id}")
            print(f"   Title: {title or '(no title)'}")
            print(f"   Location: {location or '(no location)'}")

            if caption:
                caption_preview = caption[:100] + "..." if len(caption) > 100 else caption
                print(f"   Caption: {caption_preview}")
            else:
                print(f"   Caption: (no caption)")

            if ai_sentence:
                ai_preview = ai_sentence[:100] + "..." if len(ai_sentence) > 100 else ai_sentence
                print(f"   AI Sentence: {ai_preview}")

            print(f"   Created: {created_at}")

            # Get media for this post
            cur.execute("""
                SELECT id, media_url
                FROM post_media
                WHERE post_id = %s
                ORDER BY created_at
            """, (post_id,))

            media = cur.fetchall()
            if media:
                print(f"   Media: {len(media)} file(s)")
                for idx, (media_id, media_url) in enumerate(media, 1):
                    media_preview = media_url[:80] + "..." if len(media_url) > 80 else media_url
                    print(f"      {idx}. {media_preview}")
            else:
                print(f"   Media: None")

            print("-" * 80)

        cur.close()
        conn.close()

        print(f"\n✅ Total posts: {len(posts)}")

    except psycopg2.Error as e:
        print(f"❌ Database error: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    print("=" * 80)
    print("Get architavn's Posts")
    print("=" * 80)
    get_posts()
