"""
Fix migration: Set all existing users to PRIVATE.
New users (after this) will be PUBLIC by default.

Run this once on EC2 to make existing users private:
    python3 fix_existing_users_private.py
"""

from database.db import engine
from sqlalchemy import text
from datetime import datetime

def set_existing_users_private():
    """Set all existing users to private (is_private=True)"""

    with engine.connect() as connection:
        trans = connection.begin()

        try:
            # Get count of existing users
            count_query = text("SELECT COUNT(*) FROM users WHERE is_private = FALSE")
            result = connection.execute(count_query)
            user_count = result.fetchone()[0]

            print(f"Found {user_count} users with public profiles")

            # Set all existing users to PRIVATE
            update_query = text("""
                UPDATE users
                SET is_private = TRUE
                WHERE is_private = FALSE
            """)
            connection.execute(update_query)

            trans.commit()
            print(f"✅ Successfully set {user_count} existing users to PRIVATE")
            print("   New users signing up from now on will be PUBLIC by default")

        except Exception as e:
            trans.rollback()
            print(f"❌ Error updating users: {e}")
            raise

if __name__ == "__main__":
    print("Starting migration to set existing users to private...")
    set_existing_users_private()
    print("Migration complete!")
