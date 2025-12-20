#!/usr/bin/env python3
"""
Migration script to create the comments table.
Run this to add the comments table to your database.

Usage:
    python3 create_comments_table_migration.py
"""
import os
import sys
from dotenv import load_dotenv
import psycopg2

# Load environment variables
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

def create_comments_table():
    """Create the comments table in the database"""

    if not DATABASE_URL:
        print("❌ DATABASE_URL not found in environment")
        sys.exit(1)

    try:
        # Connect to database
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()

        print("🔄 Creating comments table...")

        # Create comments table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS comments (
                id VARCHAR(36) PRIMARY KEY,
                post_id VARCHAR(36) NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
                user_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # Create indexes for performance
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_comments_post_id ON comments(post_id);
        """)

        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_comments_user_id ON comments(user_id);
        """)

        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_comments_created_at ON comments(created_at);
        """)

        conn.commit()

        print("✅ Successfully created comments table")
        print("✅ Added indexes for performance")
        print("✅ Comments cascade delete when post/user is deleted")

        # Verify table was created
        cur.execute("""
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_name = 'comments'
            ORDER BY ordinal_position;
        """)

        columns = cur.fetchall()
        print("\n📋 Comments table structure:")
        for col_name, col_type in columns:
            print(f"  - {col_name}: {col_type}")

        cur.close()
        conn.close()

        print("\n🎉 Migration completed successfully!")

    except psycopg2.Error as e:
        print(f"❌ Database error: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    print("=" * 50)
    print("Comments Table Migration")
    print("=" * 50)
    create_comments_table()
