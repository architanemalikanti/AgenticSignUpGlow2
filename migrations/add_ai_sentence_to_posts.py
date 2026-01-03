"""
Migration script to add ai_sentence column to posts table.
Run this on your EC2 instance.

Usage: python add_ai_sentence_to_posts.py
"""

from sqlalchemy import create_engine, text
from dotenv import load_dotenv
import os

load_dotenv()


def add_ai_sentence_column():
    """Add ai_sentence column to posts table."""

    engine = create_engine(os.getenv('DATABASE_URL'))

    try:
        with engine.connect() as conn:
            print("🔄 Adding 'ai_sentence' column to posts table...")

            # Check if column already exists
            result = conn.execute(text("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name='posts' AND column_name='ai_sentence'
            """))
            exists = result.fetchone()

            if exists:
                print("⚠️  'ai_sentence' column already exists!")
                return False

            # Add ai_sentence column
            conn.execute(text("""
                ALTER TABLE posts
                ADD COLUMN ai_sentence VARCHAR
            """))

            conn.commit()

            print("✅ 'ai_sentence' column added successfully!")
            return True

    except Exception as e:
        print(f"❌ Error adding column: {e}")
        return False


if __name__ == '__main__':
    print("=" * 60)
    print("  Add ai_sentence Column to Posts Table")
    print("=" * 60)
    print()

    success = add_ai_sentence_column()

    print()
    if success:
        print("🎉 Migration completed successfully!")
    else:
        print("⚠️  Migration did not complete.")
    print()
