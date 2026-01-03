"""
Script to list all users in the app.
Shows name, username, email, and whether they have posts.
"""

from database.db import SessionLocal
from database.models import User, Post
from sqlalchemy import func

def list_all_users():
    """List all users with their post counts."""
    db = SessionLocal()

    try:
        # Get all users with post counts
        users_with_posts = db.query(
            User,
            func.count(Post.id).label('post_count')
        ).outerjoin(Post, User.id == Post.user_id).group_by(User.id).order_by(User.name).all()

        print(f"\n{'='*80}")
        print(f"  ALL USERS IN GLOW APP")
        print(f"{'='*80}\n")

        if not users_with_posts:
            print("❌ No users found")
            return

        print(f"Total users: {len(users_with_posts)}\n")
        print(f"{'Name':<20} {'Username':<20} {'Email':<30} {'Posts':<10}")
        print(f"{'-'*80}")

        users_with_posts_list = []
        users_without_posts_list = []

        for user, post_count in users_with_posts:
            if post_count > 0:
                users_with_posts_list.append((user, post_count))
            else:
                users_without_posts_list.append((user, post_count))

        # Print users WITH posts first
        if users_with_posts_list:
            print("\n✅ USERS WITH POSTS:")
            for user, post_count in users_with_posts_list:
                name = user.name[:18] if user.name else "Unknown"
                username = user.username[:18] if user.username else "unknown"
                email = user.email[:28] if user.email else "N/A"
                print(f"{name:<20} @{username:<19} {email:<30} {post_count} post{'s' if post_count != 1 else ''}")

        # Print users WITHOUT posts
        if users_without_posts_list:
            print(f"\n⚠️  USERS WITHOUT POSTS ({len(users_without_posts_list)}):")
            for user, post_count in users_without_posts_list:
                name = user.name[:18] if user.name else "Unknown"
                username = user.username[:18] if user.username else "unknown"
                email = user.email[:28] if user.email else "N/A"
                print(f"{name:<20} @{username:<19} {email:<30} 0 posts")

        print(f"\n{'='*80}")
        print(f"Summary:")
        print(f"  - Users with posts: {len(users_with_posts_list)}")
        print(f"  - Users without posts: {len(users_without_posts_list)}")
        print(f"  - Total users: {len(users_with_posts)}")
        print(f"{'='*80}\n")

    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        db.close()


if __name__ == '__main__':
    list_all_users()
