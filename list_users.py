"""
Script to list all users in the app.
Usage: python list_users.py
"""

from database.db import SessionLocal
from database.models import User


def list_all_users():
    """List all users with their details."""

    db = SessionLocal()

    try:
        users = db.query(User).all()

        print("=" * 60)
        print("  APP USERS")
        print("=" * 60)
        print(f"\nTotal users: {len(users)}\n")

        for i, user in enumerate(users, 1):
            print(f"{i}. {user.name} (@{user.username})")
            print(f"   Email: {user.email}")
            print(f"   City: {user.city or 'N/A'}")
            print(f"   Occupation: {user.occupation or 'N/A'}")
            print(f"   Gender: {user.gender or 'N/A'}")
            print(f"   Profile: {'Private' if user.is_private else 'Public'}")
            print(f"   User ID: {user.id}")
            print()

        print("=" * 60)

    except Exception as e:
        print(f"❌ Error listing users: {e}")

    finally:
        db.close()


if __name__ == '__main__':
    list_all_users()
