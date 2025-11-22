"""
Migration script to add favorite_color and city columns to users table
Run this with: python add_favorite_color_city_migration.py
"""

import os
from dotenv import load_dotenv
import psycopg2

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

def run_migration():
    """Add favorite_color and city columns to users table"""
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()

        # Check if favorite_color column exists
        cursor.execute("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name='users' AND column_name='favorite_color';
        """)

        if not cursor.fetchone():
            print("Adding favorite_color column...")
            cursor.execute("""
                ALTER TABLE users
                ADD COLUMN favorite_color VARCHAR(50);
            """)
            print("✅ Added favorite_color column")
        else:
            print("✅ favorite_color column already exists")

        # Check if city column exists
        cursor.execute("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name='users' AND column_name='city';
        """)

        if not cursor.fetchone():
            print("Adding city column...")
            cursor.execute("""
                ALTER TABLE users
                ADD COLUMN city VARCHAR(200);
            """)
            print("✅ Added city column")
        else:
            print("✅ city column already exists")

        conn.commit()
        print("\n✅ Migration completed successfully!")

        cursor.close()
        conn.close()

    except Exception as e:
        print(f"❌ Error running migration: {e}")
        raise

if __name__ == "__main__":
    run_migration()
