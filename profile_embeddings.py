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
    Groups are personalized based on the user's profile with even distribution across categories.

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
    import random

    try:
        # Get user's profile to personalize recommendations
        db = SessionLocal()
        user = db.query(User).filter(User.id == user_id).first()
        db.close()

        if not user:
            # Fallback if user not found
            user_city = "sf"
            user_occupation = "students"
            user_gender = "female"
            user_ethnicity = ""
        else:
            user_city = user.city or "sf"
            user_occupation = user.occupation or "students"
            user_gender = user.gender or "female"
            user_ethnicity = user.ethnicity or ""

        # Define categories for even distribution (rotate based on time + user)
        import time
        categories = [
            {
                "name": "dating",
                "instruction": f"Generate a DATING recommendation - people the user would match with romantically. IF USER IS FEMALE: show MEN (soft boys, desi boys, finance bros, nerdy boys, ambitious men, etc). IF USER IS MALE: show WOMEN (ambitious girls, creative girls, smart girls, etc). MUST include gender keywords (boys/men/girls/women)."
            },
            {
                "name": "career_success",
                "instruction": "Generate a CAREER SUCCESS recommendation - high achievers like CEOs, Forbes 30u30 types, founders killing it, people manifesting success. Include diverse races (brown girl ceos, black founders, asian entrepreneurs, etc)."
            },
            {
                "name": "other_careers",
                "instruction": "Generate an OTHER CAREERS recommendation - specific industries like marketing girlies, IB girlies/bros, consulting people, creative types, dancers, influencers, etc. Be VERY specific to SF culture."
            },
            {
                "name": "ambitious",
                "instruction": "Generate an AMBITIOUS PEOPLE recommendation - motivated, disciplined people who will inspire the user. Can be women or men depending on user's interests (ambitious women of SF, driven founders, disciplined athletes, etc)."
            },
            {
                "name": "networking",
                "instruction": "Generate a NETWORKING recommendation - angel investors, VCs, YC partners, mentors, people who can help with startups/career. Focus on people looking to invest or connect."
            },
            {
                "name": "specific_groups",
                "instruction": "Generate a SPECIFIC NICHE recommendation - YC founders, B2B AI SaaS people, specific tech communities, run clubs, industry-specific groups. Be hyper-specific to SF tech culture."
            }
        ]

        # Rotate through categories with randomness for true even distribution
        # Use time in minutes to rotate faster + add randomness
        rotation_seed = int(time.time() / 300) + hash(user_id) + random.randint(0, 1000)  # Changes every 5 min
        selected_category = categories[rotation_seed % len(categories)]

        print(f"🎯 Selected category: {selected_category['name']} for user {user_id[:8]}")

        client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

        prompt = f"""Generate {count} ICONIC, specific, entertaining group recommendation. Make the user stop scrolling.

CATEGORY FOCUS: {selected_category['instruction']}

USER PROFILE:
- City: {user_city}
- Occupation: {user_occupation}
- Gender: {user_gender}
- Ethnicity: {user_ethnicity}

🚨 CRITICAL: DO NOT over-index on user's ethnicity! Show DIVERSE races across ALL categories. If user is desi, DON'T only show desi people - show ALL races equally (white, black, latino, asian, etc).

CRITICAL RULES:

1. STAY IN YOUR CATEGORY
   - You MUST generate content for the category specified above
   - If category is DATING: MUST include gender keywords AND show ALL races (not just user's ethnicity)
   - If category is CAREER SUCCESS: Show CEOs, Forbes 30u30, high achievers of ALL races
   - If category is OTHER CAREERS: Show specific industries (marketing, IB, consulting, influencers, etc)
   - If category is AMBITIOUS: Show motivated/disciplined people who inspire
   - If category is NETWORKING: Show investors, VCs, mentors, connectors
   - If category is SPECIFIC GROUPS: Show YC founders, B2B SaaS, niche communities

2. DIVERSITY IS MANDATORY
   - DO NOT match user's ethnicity - show DIFFERENT races
   - If user is desi → show white/black/latino/asian/mixed people
   - If user is white → show desi/black/latino/asian people
   - Rotate through ALL demographics, not just similar to user

3. BE HYPER-SPECIFIC & USEFUL
   ❌ BAD: "engineers in sf"
   ✅ GOOD: "soft boys who will cook for u while u debug code"

4. SF-SPECIFIC CULTURE:
   - Tech: yc founders, nvidia interns, meta escapees, stripe engineers, openai researchers
   - Students: berkeley cs kids, stanford dropouts, class of 2025/2026 interns
   - Community: nob hill run club, marina girls, mission creatives, matcha/boba spots
   - Finance: IB analysts, VCs, angel investors

5. DATING CATEGORY - SHOW VARIETY (don't match user's ethnicity):
   IF USER IS FEMALE → show MEN of DIFFERENT races:
   - "soft boys who'll cook for u", "finance bros who plan thoughtful dates"
   - "nerdy boys who think ur ambition is hot", "latino men who'll dance with u"
   - "black men building generational wealth", "white boys with emotional intelligence"

   IF USER IS MALE → show WOMEN of DIFFERENT races:
   - "ambitious girls building empires", "girls who send u voice memos at 3am"
   - "smart girls who'll debate philosophy with u", "asian girls manifesting forbes 30u30"

5. BANNED PHRASES:
   - "diverse professionals", "networking and brunching", "match your energy", "hot"
   - anything corporate/boring/generic

6. STYLE:
   - lowercase only
   - TWO LINES (separated by \\n):
     * Line 1: Main description (5-10 words)
     * Line 2: Spicy/unhinged detail (3-8 words) - impressive, not apologetic

EXAMPLES:
- "brown girl ceos in sf absolutely killing it\\nfuture forbes 30u30 and they know it"
- "soft boys who'll listen to ur rants\\nemotionally intelligent men are the new flex"
- "angel investors looking for the next unicorn\\nif ur pitch deck slaps they'll write the check"
- "marketing girlies of sf who matcha and pilates\\nand still close deals by 3pm"
- "yc founders building b2b ai saas\\nthey've seen the cap table trauma and survived"

Return ONLY JSON array of {count} string (each string has \\n for line break):
["line1\\nline2"]"""

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
    import re

    try:
        # Step 1: Parse gender from description
        description_lower = description.lower()
        target_gender = None

        # Check for male keywords
        male_keywords = ['boys', 'bros', 'men', 'guys', 'males', 'dudes', 'kings', 'dads', 'fathers', 'husbands', 'boyfriends']
        if any(keyword in description_lower for keyword in male_keywords):
            target_gender = 'male'

        # Check for female keywords (these override male if both present)
        female_keywords = ['girls', 'girlies', 'women', 'ladies', 'females', 'gals', 'queens', 'moms', 'mothers', 'wives', 'girlfriends']
        if any(keyword in description_lower for keyword in female_keywords):
            target_gender = 'female'

        print(f"🔍 Searching for gender: {target_gender or 'any'} (description: {description[:50]}...)")

        # Step 2: Convert description to embedding
        response = openai_client.embeddings.create(
            input=description,
            model="text-embedding-3-small"
        )
        query_embedding = response.data[0].embedding

        # Step 3: Query Pinecone for ALL users, then filter
        # Fetch more users to account for gender filtering
        fetch_count = 100  # Fetch many users to ensure we have enough after filtering
        results = index.query(
            vector=query_embedding,
            top_k=fetch_count,
            include_metadata=True
        )

        # Step 4: Format results with most recent post (only include users who have posts AND match gender)
        from database.db import SessionLocal
        from database.models import Post, PostMedia
        from sqlalchemy import desc

        db = SessionLocal()
        matched_users = []

        for match in results['matches']:
            user_data = match['metadata']
            user_id = user_data.get("user_id")
            user_gender = user_data.get("gender", "").lower()

            # Filter by gender if specified in description
            if target_gender:
                # Normalize gender values
                if target_gender == 'male' and user_gender not in ['male', 'man', 'boy', 'm']:
                    continue
                if target_gender == 'female' and user_gender not in ['female', 'woman', 'girl', 'f']:
                    continue

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

            # Collect more users than needed for randomization
            if len(matched_users) >= top_k * 3:
                break

        db.close()

        # Step 5: Randomly sample to show variety and ensure all users appear eventually
        if len(matched_users) > top_k:
            matched_users = random.sample(matched_users, top_k)

        print(f"✅ Found {len(matched_users)} users matching description (filtered by gender: {target_gender or 'any'})")

        return matched_users

    except Exception as e:
        print(f"Error finding users: {e}")
        return []
