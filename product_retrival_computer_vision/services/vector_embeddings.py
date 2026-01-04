"""
Vector embeddings utility for user profile matching.
Creates and stores embeddings of user profiles for similarity search.
"""
import os
import logging
from typing import Optional
from openai import OpenAI

logger = logging.getLogger(__name__)

# Initialize OpenAI client
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def create_user_profile_embedding(user) -> Optional[list]:
    """
    Create a vector embedding of a user's profile for similarity matching.

    Args:
        user: User object from database with profile fields

    Returns:
        list: The embedding vector (1536 dimensions for text-embedding-3-small)
        None: If embedding creation fails
    """
    try:
        # Build profile text from user data
        profile_parts = []

        if user.name:
            profile_parts.append(f"Name: {user.name}")

        if user.gender:
            profile_parts.append(f"Gender: {user.gender}")

        if user.sexuality:
            profile_parts.append(f"Sexuality: {user.sexuality}")

        if user.ethnicity:
            profile_parts.append(f"Ethnicity: {user.ethnicity}")

        if user.pronouns:
            profile_parts.append(f"Pronouns: {user.pronouns}")

        if user.university:
            profile_parts.append(f"University: {user.university}")

        if user.college_major:
            profile_parts.append(f"Major: {user.college_major}")

        if user.occupation:
            profile_parts.append(f"Occupation: {user.occupation}")

        if user.city:
            profile_parts.append(f"Location: {user.city}")

        # Add conversation context if available
        if user.conversations and len(user.conversations) > 0:
            # Get last few messages for context (limit to avoid token overflow)
            recent_messages = user.conversations[-5:]  # Last 5 messages
            conversation_text = " ".join([
                msg.get('message', '') for msg in recent_messages
                if msg.get('sender') == 'user'  # Only user messages
            ])
            if conversation_text:
                profile_parts.append(f"Recent thoughts: {conversation_text[:500]}")  # Limit length

        # Combine all parts
        profile_text = "\n".join(profile_parts)

        logger.info(f"📝 Creating embedding for user {user.id} - Profile text length: {len(profile_text)}")

        # Create embedding using OpenAI
        response = client.embeddings.create(
            input=profile_text,
            model="text-embedding-3-small"  # 1536 dimensions, cheaper than ada-002
        )

        embedding = response.data[0].embedding

        logger.info(f"✅ Created embedding for user {user.id} - Dimension: {len(embedding)}")
        return embedding

    except Exception as e:
        logger.error(f"❌ Error creating embedding for user {user.id}: {str(e)}")
        return None


def store_user_embedding_in_postgres(user_id: str, embedding: list) -> bool:
    """
    Store the user's embedding vector in PostgreSQL.

    Note: For now, we'll store embeddings in a JSONB column.
    For production scale, consider using pgvector extension or external vector DB (Pinecone, Qdrant).

    Args:
        user_id: The user's ID
        embedding: The embedding vector

    Returns:
        bool: Success status
    """
    from database.db import SessionLocal
    from database.models import User

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()

        if not user:
            logger.error(f"User {user_id} not found")
            return False

        # TODO: For now, we can skip storing in Postgres and just log
        # In production, you would:
        # 1. Add an 'embedding' column to User model (JSONB or use pgvector extension)
        # 2. Or store in external vector DB (Pinecone, Qdrant, etc.)

        logger.info(f"✅ Embedding ready for user {user_id} (storage not implemented yet)")
        logger.info(f"   Next step: Set up Pinecone or add pgvector column to store {len(embedding)}-dim vector")

        return True

    except Exception as e:
        logger.error(f"Error storing embedding for user {user_id}: {str(e)}")
        return False
    finally:
        db.close()


def create_and_store_user_embedding(user_id: str) -> bool:
    """
    Complete pipeline: Fetch user, create embedding, and store it.

    Args:
        user_id: The user's ID

    Returns:
        bool: Success status
    """
    from database.db import SessionLocal
    from database.models import User

    db = SessionLocal()
    try:
        # Fetch user from database
        user = db.query(User).filter(User.id == user_id).first()

        if not user:
            logger.error(f"User {user_id} not found")
            return False

        # Create embedding
        embedding = create_user_profile_embedding(user)

        if not embedding:
            logger.error(f"Failed to create embedding for user {user_id}")
            return False

        # Store embedding (placeholder for now)
        success = store_user_embedding_in_postgres(user_id, embedding)

        return success

    except Exception as e:
        logger.error(f"Error in create_and_store_user_embedding for user {user_id}: {str(e)}")
        return False
    finally:
        db.close()
