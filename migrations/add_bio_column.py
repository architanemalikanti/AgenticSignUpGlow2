#!/usr/bin/env python3
"""
Migration script to add bio column to users table.

Usage:
    python3 add_bio_column.py
"""
import os
import sys
from dotenv import load_dotenv
import psycopg2

# Load environment variables
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

def add_bio_column():
    """Add bio column to users table"""

    if not DATABASE_URL:
        print("❌ DATABASE_URL not found in environment")
        sys.exit(1)

    try:
        # Connect to database
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()

        print("🔄 Adding 'bio' column to users table...")

        # Check if column already exists
        cur.execute("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name='users' AND column_name='bio'
        """)
        exists = cur.fetchone()

        if exists:
            print("⚠️  'bio' column already exists!")
            cur.close()
            conn.close()
            return

        # Add bio column
        cur.execute("""
            ALTER TABLE users
            ADD COLUMN bio VARCHAR(500)
        """)

        conn.commit()

        print("✅ 'bio' column added successfully!")
        print("   Type: VARCHAR(500)")
        print("   Nullable: Yes")
        print("   Purpose: AI-generated Instagram-style bio")

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
    print("Add Bio Column to Users Table")
    print("=" * 60)
    add_bio_column()
