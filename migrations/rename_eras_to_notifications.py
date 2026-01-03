"""
Migration script to rename 'eras' table to 'notifications'
Run this on your EC2 instance to migrate the database.
"""

from sqlalchemy import create_engine, text
from dotenv import load_dotenv
import os

load_dotenv()

def migrate_eras_to_notifications():
    """Rename eras table to notifications."""

    engine = create_engine(os.getenv('DATABASE_URL'))

    with engine.connect() as conn:
        print("🔄 Starting migration: eras -> notifications")

        # Check if eras table exists
        result = conn.execute(text("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_schema = 'public'
                AND table_name = 'eras'
            )
        """))
        eras_exists = result.fetchone()[0]

        if not eras_exists:
            print("❌ 'eras' table does not exist. Nothing to migrate.")
            return False

        # Check if notifications table already exists
        result = conn.execute(text("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_schema = 'public'
                AND table_name = 'notifications'
            )
        """))
        notifications_exists = result.fetchone()[0]

        if notifications_exists:
            print("⚠️  'notifications' table already exists!")
            print("   If you want to migrate, first drop the notifications table.")
            return False

        # Get count of records
        result = conn.execute(text("SELECT COUNT(*) FROM eras"))
        count = result.fetchone()[0]
        print(f"📊 Found {count} records in 'eras' table")

        # Rename the table
        print("🔄 Renaming table 'eras' to 'notifications'...")
        conn.execute(text("ALTER TABLE eras RENAME TO notifications"))
        conn.commit()
        print("✅ Table renamed successfully!")

        # Verify the rename
        result = conn.execute(text("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_schema = 'public'
                AND table_name = 'notifications'
            )
        """))
        success = result.fetchone()[0]

        if success:
            result = conn.execute(text("SELECT COUNT(*) FROM notifications"))
            new_count = result.fetchone()[0]
            print(f"✅ Migration complete! 'notifications' table now has {new_count} records")
            return True
        else:
            print("❌ Migration failed!")
            return False


if __name__ == '__main__':
    print("=" * 60)
    print("  Migration: Rename 'eras' table to 'notifications'")
    print("=" * 60)
    print()

    success = migrate_eras_to_notifications()

    print()
    if success:
        print("🎉 Migration completed successfully!")
        print("   You can now use the 'notifications' table.")
    else:
        print("⚠️  Migration did not complete.")
    print()
