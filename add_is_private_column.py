"""
Migration script to add is_private column to users table.
This makes profiles default to PUBLIC (is_private=False).

Run this script once to update your database:
    python add_is_private_column.py
"""

from database.db import engine
from sqlalchemy import text

def add_is_private_column():
    """Add is_private column to users table with default False (public)"""

    with engine.connect() as connection:
        # Start a transaction
        trans = connection.begin()

        try:
            # Check if column already exists
            check_query = text("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name='users' AND column_name='is_private'
            """)
            result = connection.execute(check_query)

            if result.fetchone():
                print("✅ Column 'is_private' already exists in users table")
                trans.rollback()
                return

            # Add the column with default False (public profiles)
            alter_query = text("""
                ALTER TABLE users
                ADD COLUMN is_private BOOLEAN NOT NULL DEFAULT FALSE
            """)
            connection.execute(alter_query)

            # Commit the transaction
            trans.commit()
            print("✅ Successfully added 'is_private' column to users table")
            print("   All existing users now have PUBLIC profiles (is_private=False)")
            print("   New users will default to PUBLIC profiles")

        except Exception as e:
            trans.rollback()
            print(f"❌ Error adding column: {e}")
            raise

if __name__ == "__main__":
    print("Starting migration to add is_private column...")
    add_is_private_column()
    print("Migration complete!")
