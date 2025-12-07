import os
from openai import OpenAI
from pinecone import Pinecone
from dotenv import load_dotenv

load_dotenv()

# Initialize OpenAI client
openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Initialize Pinecone
pc = Pinecone(api_key=os.getenv("PINECONE_API_KEY"))
index = pc.Index(os.getenv("PINECONE_INDEX_NAME"))  # Set PINECONE_INDEX_NAME in .env


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
            model="text-embedding-3-small"  # Better and cheaper than ada-002
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
