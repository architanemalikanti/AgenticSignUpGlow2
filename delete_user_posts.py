"""
Script to delete all posts/eras for a specific user.
Usage: python delete_user_posts.py <username>
"""

import sys
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
import os

load_dotenv()

def delete_user_posts(username):
    """Delete all posts/eras for the given username."""

    engine = create_engine(os.getenv('DATABASE_URL'))

    with engine.connect() as conn:
        # Find the user
        result = conn.execute(
            text('SELECT id, username, name FROM users WHERE username = :username'),
            {'username': username}
        )
        user = result.fetchone()

        if not user:
            print(f'❌ User "{username}" not found')
            print('\nAvailable users:')
            result = conn.execute(text('SELECT username, name FROM users'))
            for u in result.fetchall():
                print(f'  - {u[0]} ({u[1]})')
            return False

        user_id, username, name = user
        print(f'✅ Found user: {username} ({name})')
        print(f'   User ID: {user_id}')

        # Check if posts table exists
        result = conn.execute(text("""
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
            AND table_name IN ('posts', 'eras')
        """))
        tables = [row[0] for row in result.fetchall()]

        total_deleted = 0

        # Delete from posts table if it exists
        if 'posts' in tables:
            result = conn.execute(
                text('SELECT COUNT(*) FROM posts WHERE user_id = :user_id'),
                {'user_id': user_id}
            )
            count = result.fetchone()[0]

            if count > 0:
                print(f'\n📝 Found {count} posts in "posts" table')

                # First, delete associated media from post_media table
                result = conn.execute(text("""
                    SELECT COUNT(*) FROM post_media
                    WHERE post_id IN (SELECT id FROM posts WHERE user_id = :user_id)
                """), {'user_id': user_id})
                media_count = result.fetchone()[0]

                if media_count > 0:
                    print(f'📸 Deleting {media_count} associated media items first...')
                    conn.execute(text("""
                        DELETE FROM post_media
                        WHERE post_id IN (SELECT id FROM posts WHERE user_id = :user_id)
                    """), {'user_id': user_id})
                    conn.commit()
                    print(f'✅ Deleted {media_count} media items')

                # Now delete the posts
                conn.execute(
                    text('DELETE FROM posts WHERE user_id = :user_id'),
                    {'user_id': user_id}
                )
                conn.commit()
                print(f'✅ Deleted {count} posts')
                total_deleted += count

        # Delete from eras table if it exists
        if 'eras' in tables:
            result = conn.execute(
                text('SELECT COUNT(*) FROM eras WHERE user_id = :user_id'),
                {'user_id': user_id}
            )
            count = result.fetchone()[0]

            if count > 0:
                print(f'\n📝 Found {count} eras in "eras" table')
                conn.execute(
                    text('DELETE FROM eras WHERE user_id = :user_id'),
                    {'user_id': user_id}
                )
                conn.commit()
                print(f'✅ Deleted {count} eras')
                total_deleted += count

        if total_deleted == 0:
            print(f'\n✨ No posts found for user "{username}"')
        else:
            print(f'\n🎉 Successfully deleted {total_deleted} total posts/eras for "{username}"')

        return True


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('Usage: python delete_user_posts.py <username>')
        print('Example: python delete_user_posts.py architavn')
        sys.exit(1)

    username = sys.argv[1]
    delete_user_posts(username)
