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

        prompt = f"""Generate {count} ICONIC, specific, entertaining group recommendations. Make the user stop scrolling.

USER PROFILE:
- City: {user_city}
- Occupation: {user_occupation}
- Gender: {user_gender}
- Ethnicity: {user_ethnicity}

CRITICAL RULES:

1. BE HYPER-SPECIFIC & USEFUL
   ❌ BAD: "engineers in sf"
   ✅ GOOD: "soft boys who will cook for u while u debug code"

   ❌ BAD: "diverse professionals brunching and networking"
   ✅ GOOD: "angel investors who will fund ur unhinged startup idea"

2. MAKE IT FUNNY/ENTERTAINING/EYE-OPENING
   - Add specific details that make it relatable
   - Use humor, not corporate speak
   - Make it scroll-stopping

   Examples:
   - "brown girl ceos in sf absolutely killing it...future forbes 30u30"
   - "the next taylor swift in ur era wow...the rising stars"
   - "stanford dropout kids who became billionaires before u graduated"
   - "soft engineer boys who'll explain distributed systems while making u pasta"
   - "emotionally available men who text back and plan actual dates"
   - "girls who'll send u voice memos analyzing ur situationship"
   - "boys who think ur career ambitions are attractive not intimidating"

3. RELATE IT TO THE USER'S LIFE
   - Dating: SPECIFIC types they'd want (soft boys, ambitious girls, respectful founders)
   - Career: People who can ACTUALLY help (investors, mentors in their field, successful people in their city)
   - Friends: Shared struggles/interests that are SPECIFIC
   - Cultural: Not generic diversity - specific cultural vibes

4. CITY-SPECIFIC CONTENT - SHOW THE CULTURE (hyper-specific to their city):

   SF (be VERY specific - this is the culture):
   - Tech: yc founders, nvidia interns, meta escapees, stripe engineers, openai researchers
   - Influencers: SF tech influencers, Instagram influencers documenting SF life
   - Community: nob hill run club runners, SF dancers, marina girls, mission creatives
   - Students: berkeley cs kids, stanford dropouts, class of 2025/2026 interns
   - Career: female VCs who invest in unhinged ideas, brown girl ceos manifesting forbes 30u30
   - Dating: all races/types of men (soft men, south asian men, ibanking men, white men, Black men, Latino men, nerdy boys, etc)
   - Random: people who know the best matcha spots, boba addicts, sourdough bread snobs

   NYC: finance bros with poetry obsessions, columbia kids at rooftop bars, bagel connoisseurs, fashion week survivors

   LA: tiktok creators hitting 10M, usc film kids making a24-level stuff, sunset chasers with insane playlists

5. ETHNICITY-AWARE (make it specific, not generic):
   - South Asian: "desi girlies balancing shaadi pressure and startup life", "brown kids whose parents finally understand their job"
   - Black: "black founders getting funded and changing the game", "hbcu kids running circles around ivy leagues"
   - But ALSO show 50-60% diverse content so everyone sees variety

6. OCCUPATION-BASED (make it specific to their struggles/wins):
   - Engineers: "10x engineers who touch grass", "swe's who escaped faang for startups"
   - Students: "cs kids surviving on free pizza and ambition", "college kids building the next unicorn from their dorm"
   - Finance: "ibanking survivors who made it out alive", "consultants making slides at 2am but thriving"

7. DATING DIVERSITY - SHOW ALL TYPES (ADAPT TO USER'S GENDER):

   IF USER IS FEMALE (show MEN of ALL races/personalities they'd want to date):
   - Soft men: "soft boys who'll cook for u and listen to ur rants after standup"
   - South Asian: "desi boys who understand family pressure and still choose u"
   - White men: "white boys with emotional intelligence who read books for fun"
   - Black men: "black men who are ambitious, respectful, and emotionally available"
   - Latino men: "latino men who'll dance with u and cook family recipes"
   - Ibanking: "finance bros who'll plan thoughtful dates not just expensive ones"
   - Nerdy: "nerdy boys who think ur debugging skills are attractive"
   - YC founders: "yc founders who'll respect ur ambition and actually pay for dinner"

   IF USER IS MALE (show WOMEN of ALL races/personalities they'd want to date):
   - "girls who'll take u on museum dates and debate philosophy with u"
   - "brown girls building empires who want someone equally driven"
   - "black girls who are intimidatingly smart but also really kind"
   - "white girls with good music taste who send u playlists"
   - "asian girls who are ambitious and won't settle for less"
   - "latina girls who'll match ur energy and introduce u to good food"
   - "girls who send u memes at 3am and understand ur chaos"

   IMPORTANT: Show DIVERSITY in dating - all races, all personality types, all vibes

BANNED PHRASES (never use these):
- "diverse professionals"
- "networking and brunching"
- "exploring opportunities"
- "building connections"
- "match your energy" / "match ur energy"
- "hot" (use: attractive, into, excited about, etc)
- anything corporate/boring/generic/vague influencer speak

STYLE:
- lowercase only
- iconic, funny, specific, scroll-stopping
- TWO LINES per description (separated by newline \\n):
  * Line 1: Main description (5-10 words)
  * Line 2: Funny/wholesome/ironic detail (3-8 words) - NOT mean, NOT judgmental

VIBE CHECK FOR LINE 2 - BE UNHINGED, SPICY, DIVERSE, HYPER-LOCAL:
✅ GOOD (impressive + unhinged + roast-but-hot + shows culture):
- "respectful kings who actually plan dates\\ngreen flags only we don't play"
- "brown girl ceos in sf absolutely killing it\\nfuture forbes 30u30 and they know it"
- "soft boys who'll listen to ur rants\\nemotionally intelligent men are the new flex"
- "stanford kids building the next unicorn\\nbootstrapped from their dorm not their trust fund"
- "engineers who left meta to build cool shit\\nand they're actually shipping code not sitting in meetings"
- "finance bros with taste\\nthey'll take u to the natural wine bar not fidi steakhouse"
- "nob hill run club runners\\nthey're faster than u and hotter too"
- "nvidia interns making 200k\\nand still eating free office snacks for dinner"
- "SF tech influencers with 50k followers\\ndocumenting every matcha spot in the mission"
- "class of 2025 interns grinding\\nalready have return offers and side projects"
- "female VCs who will invest in ur unhinged idea\\nif ur pitch deck slaps"
- "desi boys who understand family pressure\\nand still choose u over arranged marriage"
- "black men building generational wealth\\nand looking for a partner not a placeholder"

❌ BAD (apologetic, making excuses, not impressive, contradicts first line):
- "men who will cook for u\\nactually they js order doordash but its the thought" ← making excuses!
- "building unicorns\\nfunded by their parents credit card but we support" ← NOT impressive!
- anything that undercuts the first line or makes it less cool

TONE: unhinged, spicy, roast-but-in-a-hot-way, chaotic, diverse, scroll-stopping

Return ONLY JSON array of {count} strings (each string has \\n for line break):
["line1\\nline2", "line1\\nline2", ...]"""

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
