"""
Migration script to create eras table
Run this with: python create_eras_table_migration.py
"""

import os
from dotenv import load_dotenv
import psycopg2

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

def run_migration():
    """Create eras table"""
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()

        # Check if table already exists
        cursor.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_name = 'eras'
            );
        """)

        if cursor.fetchone()[0]:
            print("✅ eras table already exists")
        else:
            # Create the eras table
            cursor.execute("""
                CREATE TABLE eras (
                    id VARCHAR(36) PRIMARY KEY,
                    user_id VARCHAR(36) NOT NULL REFERENCES users(id),
                    content TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)

            # Create index on user_id for faster queries
            cursor.execute("""
                CREATE INDEX idx_eras_user_id ON eras(user_id);
            """)

            # Create index on created_at for sorting
            cursor.execute("""
                CREATE INDEX idx_eras_created_at ON eras(created_at);
            """)

            conn.commit()
            print("✅ Successfully created eras table with indexes")

        cursor.close()
        conn.close()

    except Exception as e:
        print(f"❌ Error running migration: {e}")
        raise

if __name__ == "__main__":
    run_migration()
