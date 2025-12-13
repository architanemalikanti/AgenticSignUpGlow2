"""
Script to delete all posts for specific users by name.
Usage: python delete_user_posts.py
"""

from database.db import SessionLocal
from database.models import User, Post, PostMedia
from sqlalchemy import or_

def delete_posts_for_users(names):
    """Delete all posts for users with given names."""
    db = SessionLocal()

    try:
        # Find users
        users = db.query(User).filter(
            or_(*[User.name.ilike(f'%{name}%') for name in names])
        ).all()

        if not users:
            print("❌ No users found with those names")
            return

        total_deleted = 0

        for user in users:
            print(f"\n👤 User: {user.name} (@{user.username}) - ID: {user.id}")

            # Get all posts for this user
            posts = db.query(Post).filter(Post.user_id == user.id).all()

            if not posts:
                print(f"   No posts to delete")
                continue

            print(f"   Found {len(posts)} posts")

            # Delete each post (cascade will delete post_media)
            for post in posts:
                print(f"   🗑️  Deleting post: {post.id} - {post.title}")
                db.delete(post)

            total_deleted += len(posts)

        # Commit all deletions
        db.commit()
        print(f"\n✅ Successfully deleted {total_deleted} posts!")

    except Exception as e:
        db.rollback()
        print(f"❌ Error deleting posts: {e}")
    finally:
        db.close()


if __name__ == '__main__':
    print("=" * 60)
    print("  Delete Posts for Angelica and Hayley")
    print("=" * 60)
    print()

    delete_posts_for_users(['angelica', 'hayley'])

    print()
