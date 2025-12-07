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
                    "city": user.city,
                    "occupation": user.occupation,
                    "gender": user.gender,
                    "ethnicity": user.ethnicity
                }
            }]
        )

        return f"Successfully created embedding for user {user.id}"

    except Exception as e:
        return f"Error creating embedding: {str(e)}"


def generate_ai_groups(user_id: str) -> list:
    """
    Generate 5 AI-generated group descriptions for finding similar users.

    Args:
        user_id: The user requesting recommendations (for personalization)

    Returns:
        List of 5 group description strings
    """
    from anthropic import Anthropic
    import json

    try:
        client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

        prompt = """Generate 5 diverse, interesting group descriptions for finding similar people.
Each description should be a short phrase (5-10 words) describing a type of person.

Examples:
- "college students in NYC into fashion"
- "tech workers in SF who love hiking"
- "artists in LA exploring creativity"
- "finance people in NYC with travel bug"

Make them diverse, interesting, and representative of different lifestyles/interests.
Return ONLY a JSON array of 5 strings, no other text.

Format: ["description 1", "description 2", "description 3", "description 4", "description 5"]"""

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

    Args:
        description: AI-generated group description (e.g., "college students in NYC into fashion")
        top_k: Number of users to return (default 5)

    Returns:
        List of user dicts with profile info
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

        # Step 3: Format results
        matched_users = []
        for match in results['matches']:
            user_data = match['metadata']
            matched_users.append({
                "user_id": user_data.get("user_id"),
                "name": user_data.get("name"),
                "username": user_data.get("username", ""),
                "city": user_data.get("city"),
                "occupation": user_data.get("occupation"),
                "gender": user_data.get("gender"),
                "ethnicity": user_data.get("ethnicity"),
                "similarity_score": match['score']
            })

        return matched_users

    except Exception as e:
        print(f"Error finding users: {e}")
        return []
