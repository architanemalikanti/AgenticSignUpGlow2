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
        Bio: {user.bio if user.bio else "No bio provided"}
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
                    "bio": user.bio if user.bio else "",
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
            user_bio = "student interested in tech and meeting people"
            user_gender = "female"
            user_ethnicity = ""
        else:
            user_bio = user.bio if user.bio else "exploring interests and meeting new people"
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
- Bio: {user_bio}
- Gender: {user_gender}
- Ethnicity: {user_ethnicity}

🎯 PERSONALIZATION RULE: Make recommendations RELEVANT to the user's background while showing some diversity.
- Use their bio info (interests, occupation, location, vibe) and ethnicity to personalize (e.g., "desi girls in tech", "latino founders in SF", "asian students at berkeley")
- Reference their specific context from their bio (if mentions tech → show tech people, if mentions school → show students)
- Include people from their background AND adjacent communities (mix of similar + diverse)

CRITICAL RULES:

1. STAY IN YOUR CATEGORY
   - You MUST generate content for the category specified above
   - If category is DATING: MUST include gender keywords AND reference user's background from bio
   - If category is CAREER SUCCESS: Show CEOs, Forbes 30u30 who match interests/industry from bio
   - If category is OTHER CAREERS: Show specific industries relevant to user's interests in bio
   - If category is AMBITIOUS: Show motivated people in user's community
   - If category is NETWORKING: Show investors, VCs relevant to user's interests
   - If category is SPECIFIC GROUPS: Show communities relevant to user's background from bio

2. PERSONALIZATION + DIVERSITY BALANCE
   - REFERENCE user's background (ethnicity, interests from bio) to make it relevant
   - Show a mix: some people like them + some from adjacent/diverse backgrounds
   - Examples: "desi engineers in SF", "latina founders building in tech", "black women in consulting"
   - Make them feel seen while still showing variety

3. BE HYPER-SPECIFIC & USEFUL
   ❌ BAD: "engineers in sf"
   ✅ GOOD: "soft boys who will cook for u while u debug code"

4. SF-SPECIFIC CULTURE:
   - Tech: yc founders, nvidia interns, meta escapees, stripe engineers, openai researchers
   - Students: berkeley cs kids, stanford dropouts, class of 2025/2026 interns
   - Community: nob hill run club, marina girls, mission creatives, matcha/boba spots
   - Finance: IB analysts, VCs, angel investors

5. DATING CATEGORY - PERSONALIZED TO USER:
   IF USER IS FEMALE → show MEN relevant to her background/bio:
   - If user is desi: "desi boys who'll debate philosophy with u", "south asian men building in tech"
   - If bio mentions location: reference that location (e.g., "sf boys who understand the grind")
   - Mix with: "soft boys who'll cook for u", "finance bros who plan thoughtful dates"

   IF USER IS MALE → show WOMEN relevant to his background/bio:
   - If bio mentions tech/startup: "ambitious girls building empires", "women in tech crushing it"
   - If bio mentions location: reference that location (e.g., "sf girls who send voice memos at 3am")
   - Mix with: "smart girls who'll debate philosophy with u", "creative women who inspire u"

5. BANNED PHRASES:
   - "diverse professionals", "networking and brunching", "match your energy", "hot"
   - anything corporate/boring/generic

6. STYLE:
   - lowercase only
   - TWO LINES (separated by \\n):
     * Line 1: Main description (5-10 words)
     * Line 2: Spicy/unhinged detail (3-8 words) - impressive, not apologetic

EXAMPLES (personalized to user bio):
- If user bio mentions desi + tech: "desi girls in tech absolutely killing it\\nfuture forbes 30u30 and they know it"
- If user is female + bio mentions interests: "desi boys who'll debate philosophy with u\\nsouth asian men who understand family dynamics"
- If bio mentions SF + tech: "sf engineers building the next unicorn\\nthey've seen the cap table trauma and survived"
- If bio mentions fitness/professional: "women who matcha and pilates\\nand still close deals by 3pm"
- If bio mentions startup/founding: "angel investors writing checks\\nif ur pitch deck slaps they'll fund it"

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
