#!/usr/bin/env python3
"""
Script to change Matt's password on EC2
Usage: python3 change_matt_password.py
"""
import os
import sys
import bcrypt
from dotenv import load_dotenv
import psycopg2

# Load environment variables
load_dotenv()

def change_password(username: str, new_password: str):
    """Change password for a given username"""

    # Get database URL
    DATABASE_URL = os.getenv('DATABASE_URL')
    if not DATABASE_URL:
        print("❌ DATABASE_URL not found in environment")
        sys.exit(1)

    # Connect to database
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()

    try:
        # Find user
        cur.execute("SELECT id, username FROM users WHERE username = %s", (username,))
        user = cur.fetchone()

        if not user:
            print(f"❌ User '{username}' not found")
            cur.close()
            conn.close()
            sys.exit(1)

        user_id, user_username = user
        print(f"✅ Found user: {user_username} (ID: {user_id})")

        # Hash the new password
        hashed_password = bcrypt.hashpw(
            new_password.encode('utf-8'),
            bcrypt.gensalt()
        ).decode('utf-8')

        # Update password
        cur.execute("UPDATE users SET password = %s WHERE username = %s", (hashed_password, username))
        conn.commit()

        print(f"✅ Password updated for user '{username}' to '{new_password}'")

    except Exception as e:
        print(f"❌ Error: {e}")
        conn.rollback()
        sys.exit(1)
    finally:
        cur.close()
        conn.close()

if __name__ == "__main__":
    # Change Matt's password to "password"
    change_password("matt", "password")
