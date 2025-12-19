#!/usr/bin/env python3
"""
Migration script to create the reports table.
Run this to add the reports table to your database.

Usage:
    python3 create_reports_table_migration.py
"""
import os
import sys
from dotenv import load_dotenv
import psycopg2

# Load environment variables
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

def create_reports_table():
    """Create the reports table in the database"""

    if not DATABASE_URL:
        print("❌ DATABASE_URL not found in environment")
        sys.exit(1)

    try:
        # Connect to database
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()

        print("🔄 Creating reports table...")

        # Create reports table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS reports (
                id VARCHAR(36) PRIMARY KEY,
                post_id VARCHAR(36) NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
                reported_user_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                reporter_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                reason TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

                -- Indexes for faster queries
                CONSTRAINT unique_user_post_report UNIQUE (reporter_id, post_id)
            );
        """)

        # Create indexes for performance
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_reports_post_id ON reports(post_id);
        """)

        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_reports_reporter_id ON reports(reporter_id);
        """)

        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_reports_reported_user_id ON reports(reported_user_id);
        """)

        conn.commit()

        print("✅ Successfully created reports table")
        print("✅ Added indexes for performance")
        print("✅ Added unique constraint to prevent duplicate reports")

        # Verify table was created
        cur.execute("""
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_name = 'reports'
            ORDER BY ordinal_position;
        """)

        columns = cur.fetchall()
        print("\n📋 Reports table structure:")
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
    print("Reports Table Migration")
    print("=" * 50)
    create_reports_table()
