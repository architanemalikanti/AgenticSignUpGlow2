"""
Script to delete all posts for Sahara.
"""

from database.db import SessionLocal
from database.models import User, Post

def delete_sahara_posts():
    """Delete all posts for Sahara."""
    db = SessionLocal()

    try:
        # Find Sahara
        sahara = db.query(User).filter(User.name.ilike('%sahara%')).first()

        if not sahara:
            print("❌ Sahara not found")
            return

        print(f"👤 Found: {sahara.name} (@{sahara.username}) - ID: {sahara.id}")

        # Get all posts
        posts = db.query(Post).filter(Post.user_id == sahara.id).all()

        if not posts:
            print("   No posts to delete")
            return

        print(f"   Found {len(posts)} posts")

        # Delete each post
        for post in posts:
            print(f"   🗑️  Deleting: {post.id} - {post.title}")
            db.delete(post)

        # Commit
        db.commit()
        print(f"\n✅ Successfully deleted {len(posts)} posts!")

    except Exception as e:
        db.rollback()
        print(f"❌ Error: {e}")
    finally:
        db.close()


if __name__ == '__main__':
    print("=" * 60)
    print("  Delete Sahara's Posts")
    print("=" * 60)
    print()
    delete_sahara_posts()
    print()
