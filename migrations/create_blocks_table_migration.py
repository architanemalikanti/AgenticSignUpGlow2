#!/usr/bin/env python3
"""
Migration script to create the blocks table.
Run this to add the blocks table to your database.

Usage:
    python3 create_blocks_table_migration.py
"""
import os
import sys
from dotenv import load_dotenv
import psycopg2

# Load environment variables
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

def create_blocks_table():
    """Create the blocks table in the database"""

    if not DATABASE_URL:
        print("❌ DATABASE_URL not found in environment")
        sys.exit(1)

    try:
        # Connect to database
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()

        print("🔄 Creating blocks table...")

        # Create blocks table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS blocks (
                id VARCHAR(36) PRIMARY KEY,
                blocker_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                blocked_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

                -- Ensure unique blocks (can't block same user twice)
                CONSTRAINT unique_block UNIQUE (blocker_id, blocked_id),

                -- Can't block yourself (database-level constraint)
                CONSTRAINT no_self_block CHECK (blocker_id != blocked_id)
            );
        """)

        # Create indexes for performance
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_blocks_blocker_id ON blocks(blocker_id);
        """)

        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_blocks_blocked_id ON blocks(blocked_id);
        """)

        conn.commit()

        print("✅ Successfully created blocks table")
        print("✅ Added indexes for performance")
        print("✅ Added unique constraint to prevent duplicate blocks")
        print("✅ Added check constraint to prevent self-blocking")

        # Verify table was created
        cur.execute("""
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_name = 'blocks'
            ORDER BY ordinal_position;
        """)

        columns = cur.fetchall()
        print("\n📋 Blocks table structure:")
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
    print("Blocks Table Migration")
    print("=" * 50)
    create_blocks_table()
