import os
from openai import OpenAI
from pinecone import Pinecone
from dotenv import load_dotenv

load_dotenv()

# Initialize OpenAI client
openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Initialize Pinecone
pc = Pinecone(api_key=os.getenv("PINECONE_API_KEY"))
index = pc.Index(os.getenv("PINECONE_INDEX_NAME"))


def create_user_profile_embedding(user):
    """
    Create an embedding for a user's profile and store it in Pinecone.

    Args:
        user: User model object with profile data

    Returns:
        str: Success message or error
    """
    try:
        profile_text = f"""
        City: {user.city}
        Occupation: {user.occupation}
        Gender: {user.gender}
        Ethnicity: {user.ethnicity}
        """

        # Create the embedding using new OpenAI API
        response = openai_client.embeddings.create(
            input=profile_text,
            model="text-embedding-3-small"
        )

        embedding_vector = response.data[0].embedding

        # Store in Pinecone with metadata
        index.upsert(
            vectors=[{
                "id": user.id,
                "values": embedding_vector,
                "metadata": {
                    "user_id": user.id,
                    "name": user.name,
                    "username": user.username,
                    "city": user.city,
                    "occupation": user.occupation,
                    "gender": user.gender,
                    "ethnicity": user.ethnicity,
                    "profile_image": user.profile_image if user.profile_image else ""
                }
            }]
        )

        return f"Successfully created embedding for user {user.id}"

    except Exception as e:
        return f"Error creating embedding: {str(e)}"


def generate_ai_groups(user_id: str) -> list:
    """
    Generate 5 AI-generated group descriptions for finding similar users.
    Groups are personalized based on the user's profile.

    Args:
        user_id: The user requesting recommendations (for personalization)

    Returns:
        List of 5 group description strings
    """
    from anthropic import Anthropic
    from database.db import SessionLocal
    from database.models import User
    import json

    try:
        # Get user's profile to personalize recommendations
        db = SessionLocal()
        user = db.query(User).filter(User.id == user_id).first()
        db.close()

        if not user:
            # Fallback if user not found
            user_city = "the city"
            user_occupation = "students"
            user_gender = "people"
        else:
            user_city = user.city or "the city"
            user_occupation = user.occupation or "students"
            user_gender = user.gender or "people"

        client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

        prompt = f"""Generate 5 diverse, funny group descriptions for finding similar people.

The user is: {user_gender}, lives in {user_city}, occupation: {user_occupation}

IMPORTANT FORMAT:
- First description: Single line only (5-10 words)
- Descriptions 2-5: Two lines each - main line + shorter sassy line in parentheses

Make them witty, playful, and a bit irreverent.

Examples:
1. "other students in sf surviving on iced coffee"
2. "cornellians who thought sf was gonna be the goat city. (nyc > sf fight me)"
3. "sf girls pretending they have it together. (we don't)"
4. "students romanticizing their quarter life crisis. (it's not a vibe)"
5. "tech people who actually touch grass sometimes. (shocking i know)"

The second line should be shorter (3-5 words) and add a sassy/funny commentary in parentheses.

Return ONLY a JSON array of 5 strings, no other text.

Format: ["description 1", "description 2. (sassy comment)", "description 3. (sassy comment)", ...]"""

        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}]
        )

        content = response.content[0].text.strip()

        # Parse JSON
        if "[" in content:
            start = content.find("[")
            end = content.rfind("]") + 1
            json_str = content[start:end]
            groups = json.loads(json_str)
            return groups[:5]
        else:
            # Fallback
            return [
                "college students exploring their interests",
                "young professionals in tech",
                "creative types in the city",
                "people passionate about travel",
                "students balancing work and life"
            ]

    except Exception as e:
        print(f"Error generating AI groups: {e}")
        return [
            "college students exploring their interests",
            "young professionals in tech",
            "creative types in the city",
            "people passionate about travel",
            "students balancing work and life"
        ]


def find_users_from_ai_description(description: str, top_k: int = 5) -> list:
    """
    Find users matching an AI-generated description using semantic search.
    Includes each user's most recent post.

    Args:
        description: AI-generated group description (e.g., "college students in NYC into fashion")
        top_k: Number of users to return (default 5)

    Returns:
        List of user dicts with profile info and most recent post
    """
    try:
        # Step 1: Convert description to embedding
        response = openai_client.embeddings.create(
            input=description,
            model="text-embedding-3-small"
        )
        query_embedding = response.data[0].embedding

        # Step 2: Query Pinecone for similar user embeddings
        results = index.query(
            vector=query_embedding,
            top_k=top_k,
            include_metadata=True
        )

        # Step 3: Format results with most recent post
        from database.db import SessionLocal
        from database.models import Post, PostMedia
        from sqlalchemy import desc

        db = SessionLocal()
        matched_users = []

        for match in results['matches']:
            user_data = match['metadata']
            user_id = user_data.get("user_id")

            # Get most recent post for this user
            most_recent_post = None
            post = db.query(Post).filter(
                Post.user_id == user_id
            ).order_by(desc(Post.created_at)).first()

            if post:
                # Get media for this post
                media_urls = [m.media_url for m in post.media]

                most_recent_post = {
                    "post_id": post.id,
                    "title": post.title,
                    "caption": post.caption,
                    "location": post.location,
                    "media_urls": media_urls,
                    "created_at": post.created_at.isoformat() if post.created_at else None
                }

            matched_users.append({
                "user_id": user_id,
                "name": user_data.get("name"),
                "username": user_data.get("username", ""),
                "city": user_data.get("city"),
                "occupation": user_data.get("occupation"),
                "gender": user_data.get("gender"),
                "ethnicity": user_data.get("ethnicity"),
                "profile_image": user_data.get("profile_image", ""),
                "similarity_score": match['score'],
                "most_recent_post": most_recent_post
            })

        db.close()
        return matched_users

    except Exception as e:
        print(f"Error finding users: {e}")
        return []
