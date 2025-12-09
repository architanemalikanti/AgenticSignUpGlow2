"""
Migration script to create the 'likes' table.
Run this on your EC2 instance to add likes functionality.

Usage: python create_likes_table.py
"""

from sqlalchemy import create_engine, text
from dotenv import load_dotenv
import os

load_dotenv()


def create_likes_table():
    """Create the likes table in the database."""

    engine = create_engine(os.getenv('DATABASE_URL'))

    try:
        with engine.connect() as conn:
            print("🔄 Creating 'likes' table...")

            # Check if table already exists
            result = conn.execute(text("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables
                    WHERE table_schema = 'public'
                    AND table_name = 'likes'
                )
            """))
            exists = result.fetchone()[0]

            if exists:
                print("⚠️  'likes' table already exists!")
                return False

            # Create likes table
            conn.execute(text("""
                CREATE TABLE likes (
                    id VARCHAR(36) PRIMARY KEY,
                    user_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    post_id VARCHAR(36) NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(user_id, post_id)
                )
            """))

            # Create index for faster queries
            conn.execute(text("""
                CREATE INDEX idx_likes_post_id ON likes(post_id);
                CREATE INDEX idx_likes_user_id ON likes(user_id);
            """))

            conn.commit()

            print("✅ 'likes' table created successfully!")
            print("✅ Indexes created for performance")
            return True

    except Exception as e:
        print(f"❌ Error creating likes table: {e}")
        return False


if __name__ == '__main__':
    print("=" * 60)
    print("  Create Likes Table Migration")
    print("=" * 60)
    print()

    success = create_likes_table()

    print()
    if success:
        print("🎉 Migration completed successfully!")
        print("   You can now use likes functionality.")
    else:
        print("⚠️  Migration did not complete.")
    print()
