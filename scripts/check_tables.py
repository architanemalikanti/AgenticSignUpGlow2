"""
Script to check what tables exist in the database.
Usage: python check_tables.py
"""

from sqlalchemy import create_engine, text
from dotenv import load_dotenv
import os

load_dotenv()


def check_database_tables():
    """List all tables in the database."""

    engine = create_engine(os.getenv('DATABASE_URL'))

    try:
        with engine.connect() as conn:
            # Get all tables
            result = conn.execute(text("""
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
                ORDER BY table_name
            """))

            tables = [row[0] for row in result.fetchall()]

            print("=" * 60)
            print("  DATABASE TABLES")
            print("=" * 60)
            print(f"\nFound {len(tables)} tables:\n")

            for table in tables:
                print(f"  ✓ {table}")

            # Check for posts specifically
            print("\n" + "=" * 60)
            if 'posts' in tables:
                # Count posts
                result = conn.execute(text("SELECT COUNT(*) FROM posts"))
                count = result.fetchone()[0]
                print(f"✅ 'posts' table exists with {count} posts")
            else:
                print("❌ 'posts' table does NOT exist")
                print("   You may need to create the posts table or run migrations")

            print("=" * 60)

    except Exception as e:
        print(f"❌ Error checking database: {e}")


if __name__ == '__main__':
    check_database_tables()
