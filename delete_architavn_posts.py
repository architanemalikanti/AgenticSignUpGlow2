#!/usr/bin/env python3
"""
Script to delete architavn's last 6 posts from the database.

Usage:
    python3 delete_architavn_posts.py
"""
import os
import sys
from dotenv import load_dotenv
import psycopg2

# Load environment variables
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

def delete_posts():
    """Delete architavn's last 3 posts"""

    if not DATABASE_URL:
        print("❌ DATABASE_URL not found in environment")
        sys.exit(1)

    try:
        # Connect to database
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()

        print("🔍 Finding architavn's user...")

        # Find architavn's user_id
        cur.execute("SELECT id, username FROM users WHERE username = %s", ("architavn",))
        user = cur.fetchone()

        if not user:
            print("❌ User 'architavn' not found")
            cur.close()
            conn.close()
            sys.exit(1)

        user_id, username = user
        print(f"✅ Found user: {username} (ID: {user_id})")

        # Get last 6 posts
        print(f"\n🔍 Finding last 6 posts...")
        cur.execute("""
            SELECT id, title, caption, created_at
            FROM posts
            WHERE user_id = %s
            ORDER BY created_at DESC
            LIMIT 6
        """, (user_id,))

        posts = cur.fetchall()

        if not posts:
            print("❌ No posts found for this user")
            cur.close()
            conn.close()
            return

        print(f"\n📋 Found {len(posts)} post(s) to delete:")
        for post_id, title, caption, created_at in posts:
            print(f"\n  Post ID: {post_id}")
            print(f"  Title: {title}")
            print(f"  Caption: {caption[:50]}..." if caption and len(caption) > 50 else f"  Caption: {caption}")
            print(f"  Created: {created_at}")

        # Confirm deletion
        print("\n⚠️  WARNING: This will permanently delete these posts!")
        confirm = input("Type 'DELETE' to confirm: ")

        if confirm != "DELETE":
            print("❌ Deletion cancelled")
            cur.close()
            conn.close()
            return

        # Delete all related data first, then posts
        print("\n🗑️  Deleting posts and all associated data...")
        for post_id, _, _, _ in posts:
            print(f"\n  📝 Processing post {post_id}...")

            # Delete post_media
            cur.execute("SELECT COUNT(*) FROM post_media WHERE post_id = %s", (post_id,))
            media_count = cur.fetchone()[0]
            if media_count > 0:
                cur.execute("DELETE FROM post_media WHERE post_id = %s", (post_id,))
                print(f"     🖼️  Deleted {media_count} media item(s)")

            # Delete likes
            cur.execute("SELECT COUNT(*) FROM likes WHERE post_id = %s", (post_id,))
            like_count = cur.fetchone()[0]
            if like_count > 0:
                cur.execute("DELETE FROM likes WHERE post_id = %s", (post_id,))
                print(f"     ❤️  Deleted {like_count} like(s)")

            # Delete comments
            cur.execute("SELECT COUNT(*) FROM comments WHERE post_id = %s", (post_id,))
            comment_count = cur.fetchone()[0]
            if comment_count > 0:
                cur.execute("DELETE FROM comments WHERE post_id = %s", (post_id,))
                print(f"     💬 Deleted {comment_count} comment(s)")

            # Delete reports
            cur.execute("SELECT COUNT(*) FROM reports WHERE post_id = %s", (post_id,))
            report_count = cur.fetchone()[0]
            if report_count > 0:
                cur.execute("DELETE FROM reports WHERE post_id = %s", (post_id,))
                print(f"     🚩 Deleted {report_count} report(s)")

            # Finally delete the post
            cur.execute("DELETE FROM posts WHERE id = %s", (post_id,))
            print(f"     ✅ Deleted post {post_id}")

        conn.commit()

        print(f"\n✅ Successfully deleted {len(posts)} post(s) and all associated data")

        cur.close()
        conn.close()

    except psycopg2.Error as e:
        print(f"❌ Database error: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    print("=" * 60)
    print("Delete architavn's Last 6 Posts")
    print("=" * 60)
    delete_posts()
