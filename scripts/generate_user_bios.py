"""
Script to generate AI bios for existing users who don't have bios yet.
Excludes the user with email architan009@gmail.com

Usage:
    python scripts/generate_user_bios.py
"""

import sys
import os
from pathlib import Path

# Add parent directory to path so we can import modules
script_dir = Path(__file__).parent
parent_dir = script_dir.parent
sys.path.insert(0, str(parent_dir))

from database.db import SessionLocal
from database.models import User
from anthropic import Anthropic
import logging
import time

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


def generate_bio(user: User) -> str:
    """
    Generate an Instagram-style bio for a user based on their profile data.

    Args:
        user: User object with profile information

    Returns:
        Generated bio string
    """
    # Collect available user data
    info_parts = []

    if user.occupation:
        info_parts.append(f"Occupation: {user.occupation}")
    if user.university:
        info_parts.append(f"University: {user.university}")
    if user.college_major:
        info_parts.append(f"Major: {user.college_major}")
    if user.city:
        info_parts.append(f"City: {user.city}")
    if user.ethnicity:
        info_parts.append(f"Ethnicity: {user.ethnicity}")

    user_info = "\n".join(info_parts) if info_parts else "No additional info"

    prompt = f"""Generate a short, chic Instagram-style bio for this person.

User Info:
- Name: {user.name}
- Gender: {user.gender if user.gender else "Not specified"}
{user_info}

Requirements:
- 1-2 sentences max
- Lowercase, casual tone
- Gen-z style
- Incorporate their interests, location, or occupation naturally
- Make it fun and authentic
- No emojis

Examples:
"cs major at cornell. building the future one bug at a time"
"designer in nyc. coffee enthusiast and pinterest curator"
"stanford grad student. lover of late night coding sessions"
"marketing girlie in sf. always hunting for the best matcha"

Generate a bio for {user.name}:"""

    try:
        client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=100,
            messages=[{"role": "user", "content": prompt}]
        )

        bio = response.content[0].text.strip().strip('"\'')
        return bio

    except Exception as e:
        logger.error(f"❌ Error generating bio for {user.name}: {e}")
        # Fallback bio
        if user.occupation and user.city:
            return f"{user.occupation.lower()} in {user.city.lower()}"
        elif user.university:
            return f"student at {user.university.lower()}"
        else:
            return "just vibing"


def run_bio_generation():
    """Generate bios for all users who don't have them (excluding architan009@gmail.com)"""

    db = SessionLocal()

    try:
        logger.info("🚀 Starting bio generation for users without bios...")

        # Query users who need bios
        users_without_bios = db.query(User).filter(
            User.email != 'architan009@gmail.com',
            (User.bio == None) | (User.bio == '')
        ).all()

        total_users = len(users_without_bios)

        if total_users == 0:
            logger.info("✅ All users already have bios!")
            return

        logger.info(f"📊 Found {total_users} users without bios")
        logger.info("⏳ This will take a while... generating bios with AI")

        success_count = 0
        error_count = 0

        for i, user in enumerate(users_without_bios, 1):
            logger.info(f"\n[{i}/{total_users}] Generating bio for {user.name} (@{user.username})...")

            try:
                # Generate bio
                bio = generate_bio(user)

                # Save to database
                user.bio = bio
                db.commit()

                logger.info(f"✨ Generated: \"{bio}\"")
                success_count += 1

                # Rate limit: Wait 1 second between API calls
                if i < total_users:
                    time.sleep(1)

            except Exception as e:
                logger.error(f"❌ Failed to generate bio for {user.name}: {e}")
                error_count += 1
                db.rollback()

        logger.info("\n" + "="*50)
        logger.info(f"✅ Bio generation complete!")
        logger.info(f"   Success: {success_count}")
        logger.info(f"   Errors: {error_count}")
        logger.info(f"   Total processed: {total_users}")
        logger.info("="*50)

    except Exception as e:
        logger.error(f"❌ Fatal error: {e}")
        db.rollback()
        raise

    finally:
        db.close()


if __name__ == "__main__":
    run_bio_generation()
