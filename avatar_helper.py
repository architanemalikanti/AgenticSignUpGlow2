"""
Helper function to get cartoon avatar URLs from S3 for FEMALE users based on ethnicity.
"""
import os
from dotenv import load_dotenv

load_dotenv()

def get_cartoon_avatar(gender: str, ethnicity: str) -> str:
    """
    Map female user's ethnicity to a cartoon avatar image URL from S3.
    This function should only be called for female users.

    Args:
        gender: User's gender (should be "female")
        ethnicity: User's ethnicity (e.g., "asian", "black", "white", "hispanic", "middle eastern", "mixed")

    Returns:
        S3 URL to the cartoon avatar image for females
    """
    # Get S3 base URL from environment variable
    # Format: https://your-bucket-name.s3.us-west-2.amazonaws.com
    BASE_URL = os.getenv("S3_AVATAR_BASE_URL", "https://glow-avatars-bucket.s3.us-west-1.amazonaws.com")

    # Normalize ethnicity to lowercase for consistent matching
    ethnicity = ethnicity.lower().strip() if ethnicity else "other"

    # Avatar mapping: ethnicity -> female avatar image
    female_avatars = {
        "asian": f"{BASE_URL}/female_asian.png",
        "black": f"{BASE_URL}/female_black.png",
        "white": f"{BASE_URL}/female_white.png",
        "hispanic": f"{BASE_URL}/female_hispanic.png",
        "middle eastern": f"{BASE_URL}/female_middle_eastern.png",
        "south asian": f"{BASE_URL}/female_south_asian.png",
    }

    # Get avatar for ethnicity or fallback to white as default
    avatar_url = female_avatars.get(ethnicity, female_avatars["white"])

    return avatar_url
