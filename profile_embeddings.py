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


def generate_ai_groups(user_id: str, count: int = 5) -> list:
    """
    Generate AI-generated group descriptions for finding similar users.
    Groups are personalized based on the user's profile.

    Args:
        user_id: The user requesting recommendations (for personalization)
        count: Number of groups to generate (default 5)

    Returns:
        List of group description strings
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
            user_ethnicity = ""
        else:
            user_city = user.city or "the city"
            user_occupation = user.occupation or "students"
            user_gender = user.gender or "people"
            user_ethnicity = user.ethnicity or ""

        client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

        prompt = f"""Generate {count} ultra-personalized, useful group recommendations for a user.

USER PROFILE:
- City: {user_city}
- Occupation: {user_occupation}
- Gender: {user_gender}
- Ethnicity: {user_ethnicity}

PERSONALIZATION RULES (follow ALL of these):

1. USEFUL CONTENT - Prioritize groups that help the user:
   - Dating: people they might want to date in their city
   - Career: mentors, angel investors, people in their field, networking opportunities
   - Friends: people with similar interests in their city
   - Cultural: people from their background (but also show diverse backgrounds!)

2. CITY-SPECIFIC (must adapt to user's city):
   - SF: startup founders, yc, a16z, berkeley/stanford, tech, boba, matcha, angel investors, soma engineers
   - NYC: finance, consulting, fashion, media, columbia/nyu, bagels, rooftop szn
   - LA: entertainment, influencers, usc/ucla, beach culture, content creators
   - Other cities: adapt accordingly

3. ETHNICITY-AWARE (but diverse):
   - If South Asian: include desi content (shaadi season, indian aunties, bollywood references, desi slang)
   - If Black: include Black excellence content (Black founders, HBCU culture, Black girl magic)
   - If Latino: include Latino culture content
   - IMPORTANT: Also show 60% other ethnicities for diversity - everyone should see diverse content!

4. OCCUPATION-BASED:
   - Students: college friends, study groups, internship hunting, campus culture
   - Engineers: other engineers, startup founders, tech leads
   - Finance: ibanking girlies, consultants, PE/VC people
   - Artists: creatives, musicians, designers

5. GENDER-SPECIFIC (where relevant):
   - Female: girlboss founders, female investors, girls who support girls
   - Male: soft men, respectful daters, male mentors
   - Show cross-gender content for dating/networking

6. DATING ARCHETYPES (always include 1-2):
   - Based on city + values (ambitious, respectful, soft, nerdy, artsy)
   - Example: "sf founders who'll pay for dinner and respect ur ambition"
   - Example: "soft men who love listening to ur yapping"

STYLE:
- lowercase only
- warm, funny, aesthetic, chaotic-but-safe
- no burnout, crying, or trauma
- 5-10 words max

OUTPUT FORMAT:
Return ONLY a JSON array of {count} group descriptions.
Example: ["brown girl ceos in sf", "stanford kids building the next google", "soft men who love to listen"]

Generate NOW:"""

        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=500,  # Increased for more personalized responses
            messages=[{"role": "user", "content": prompt}]
        )

        content = response.content[0].text.strip()

        # Parse JSON
        if "[" in content:
            start = content.find("[")
            end = content.rfind("]") + 1
            json_str = content[start:end]
            groups = json.loads(json_str)
            return groups[:count]
        else:
            # Fallback
            fallback_groups = [
                "college students exploring their interests",
                "young professionals in tech",
                "creative types in the city",
                "people passionate about travel",
                "students balancing work and life"
            ]
            return fallback_groups[:count]

    except Exception as e:
        print(f"Error generating AI groups: {e}")
        fallback_groups = [
            "college students exploring their interests",
            "young professionals in tech",
            "creative types in the city",
            "people passionate about travel",
            "students balancing work and life"
        ]
        return fallback_groups[:count]


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
    import random

    try:
        # Step 1: Convert description to embedding
        response = openai_client.embeddings.create(
            input=description,
            model="text-embedding-3-small"
        )
        query_embedding = response.data[0].embedding

        # Step 2: Query Pinecone for MORE users than needed (for diversity)
        # Get 30 users, then randomly sample 5 to avoid showing same users
        fetch_count = min(top_k * 6, 30)  # Fetch 6x more for randomization
        results = index.query(
            vector=query_embedding,
            top_k=fetch_count,
            include_metadata=True
        )

        # Step 3: Format results with most recent post (only include users who have posts)
        from database.db import SessionLocal
        from database.models import Post, PostMedia
        from sqlalchemy import desc

        db = SessionLocal()
        matched_users = []

        for match in results['matches']:
            user_data = match['metadata']
            user_id = user_data.get("user_id")

            # Get most recent post for this user
            post = db.query(Post).filter(
                Post.user_id == user_id
            ).order_by(desc(Post.created_at)).first()

            # ONLY include users who have posted
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

        # Step 4: Randomly sample top_k users from the results for diversity
        if len(matched_users) > top_k:
            matched_users = random.sample(matched_users, top_k)

        return matched_users

    except Exception as e:
        print(f"Error finding users: {e}")
        return []
