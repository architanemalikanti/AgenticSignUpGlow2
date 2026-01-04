"""
Simple onboarding tools for streamlined signup flow.
Collects: name, username, password, confirm password, ethnicity, city, occupation, gender
"""

from langchain_core.tools import tool
from utils.redis_client import r
import json
import logging
import bcrypt

logger = logging.getLogger(__name__)


@tool
def set_simple_name(session_id: str, name: str) -> str:
    """Set the user's first name in Redis."""
    try:
        redis_key = f"session:{session_id}"
        session_data_str = r.get(redis_key)

        if not session_data_str:
            return "Session not found"

        session_data = json.loads(session_data_str)
        session_data['signup_data']['name'] = name
        r.set(redis_key, json.dumps(session_data))

        logger.info(f"✅ Set name: {name}")
        return f"Got it! Your name is {name}."
    except Exception as e:
        logger.error(f"Error setting name: {e}")
        return f"Error: {str(e)}"


@tool
def set_simple_username(session_id: str, username: str) -> str:
    """Set the username in Redis."""
    try:
        redis_key = f"session:{session_id}"
        session_data_str = r.get(redis_key)

        if not session_data_str:
            return "Session not found"

        session_data = json.loads(session_data_str)
        session_data['signup_data']['username'] = username
        r.set(redis_key, json.dumps(session_data))

        logger.info(f"✅ Set username: {username}")
        return f"Username @{username} saved!"
    except Exception as e:
        logger.error(f"Error setting username: {e}")
        return f"Error: {str(e)}"


@tool
def set_simple_password(session_id: str, password: str) -> str:
    """Set the password in Redis."""
    try:
        redis_key = f"session:{session_id}"
        session_data_str = r.get(redis_key)

        if not session_data_str:
            return "Session not found"

        session_data = json.loads(session_data_str)
        session_data['signup_data']['password'] = password
        r.set(redis_key, json.dumps(session_data))

        logger.info(f"✅ Set password")
        return "Password saved!"
    except Exception as e:
        logger.error(f"Error setting password: {e}")
        return f"Error: {str(e)}"


@tool
def confirm_simple_password(session_id: str, confirm_password: str) -> str:
    """Confirm the password matches."""
    try:
        redis_key = f"session:{session_id}"
        session_data_str = r.get(redis_key)

        if not session_data_str:
            return "Session not found"

        session_data = json.loads(session_data_str)
        stored_password = session_data['signup_data'].get('password', '')

        if stored_password == confirm_password:
            logger.info(f"✅ Password confirmed")
            return "Password confirmed!"
        else:
            logger.warning(f"❌ Password mismatch")
            return "Passwords don't match. Please try again."
    except Exception as e:
        logger.error(f"Error confirming password: {e}")
        return f"Error: {str(e)}"


@tool
def set_ethnicity(session_id: str, ethnicity: str) -> str:
    """Set the user's ethnicity in Redis."""
    try:
        redis_key = f"session:{session_id}"
        session_data_str = r.get(redis_key)

        if not session_data_str:
            return "Session not found"

        session_data = json.loads(session_data_str)
        session_data['signup_data']['ethnicity'] = ethnicity
        r.set(redis_key, json.dumps(session_data))

        logger.info(f"✅ Set ethnicity: {ethnicity}")
        return f"Got it, thanks for sharing!"
    except Exception as e:
        logger.error(f"Error setting ethnicity: {e}")
        return f"Error: {str(e)}"


@tool
def set_city(session_id: str, city: str) -> str:
    """Set the city the user lives in."""
    try:
        redis_key = f"session:{session_id}"
        session_data_str = r.get(redis_key)

        if not session_data_str:
            return "Session not found"

        session_data = json.loads(session_data_str)
        session_data['signup_data']['city'] = city
        r.set(redis_key, json.dumps(session_data))

        logger.info(f"✅ Set city: {city}")
        return f"Nice! {city} is awesome."
    except Exception as e:
        logger.error(f"Error setting city: {e}")
        return f"Error: {str(e)}"


@tool
def set_simple_occupation(session_id: str, occupation: str) -> str:
    """Set the user's occupation in Redis."""
    try:
        redis_key = f"session:{session_id}"
        session_data_str = r.get(redis_key)

        if not session_data_str:
            return "Session not found"

        session_data = json.loads(session_data_str)
        session_data['signup_data']['occupation'] = occupation
        r.set(redis_key, json.dumps(session_data))

        logger.info(f"✅ Set occupation: {occupation}")
        return f"Cool! {occupation} sounds interesting."
    except Exception as e:
        logger.error(f"Error setting occupation: {e}")
        return f"Error: {str(e)}"


@tool
def finalize_simple_signup(session_id: str) -> str:
    """
    Finalize the simple signup by creating the user in the database.
    Returns 'verified' on success.
    """
    try:
        from database.db import SessionLocal
        from database.models import User
        import uuid
        from datetime import datetime
        import bcrypt

        redis_key = f"session:{session_id}"
        session_data_str = r.get(redis_key)

        if not session_data_str:
            return "Session not found"

        session_data = json.loads(session_data_str)
        signup_data = session_data.get('signup_data', {})

        # Validate all required fields
        required_fields = ['name', 'username', 'email', 'password', 'ethnicity', 'city', 'occupation', 'gender']
        missing_fields = [f for f in required_fields if not signup_data.get(f)]

        if missing_fields:
            return f"Missing fields: {', '.join(missing_fields)}"

        # Create user in database
        db = SessionLocal()
        try:
            # Hash password (check if already hashed, if not hash it)
            password_value = signup_data['password']
            if password_value.startswith('pbkdf2:'):
                # Already hashed from set_password tool
                hashed_password = password_value
            else:
                # Plain password, hash it with bcrypt
                hashed_password = bcrypt.hashpw(
                    password_value.encode('utf-8'),
                    bcrypt.gensalt()
                ).decode('utf-8')

            # Get cartoon avatar ONLY for females
            gender = signup_data.get('gender', '').lower().strip()
            profile_image_url = None

            if gender == 'female':
                from utils.avatar_helper import get_cartoon_avatar
                ethnicity = signup_data.get('ethnicity', '')
                profile_image_url = get_cartoon_avatar(gender, ethnicity)
                logger.info(f"🎨 Selected avatar for female/{ethnicity}: {profile_image_url}")
            else:
                logger.info(f"ℹ️  No avatar assigned (gender: {gender})")

            # Create user
            user_id = str(uuid.uuid4())
            new_user = User(
                id=user_id,
                username=signup_data['username'],
                email=signup_data['email'],  # Use actual email from signup
                name=signup_data['name'],
                password=hashed_password,
                occupation=signup_data['occupation'],
                gender=signup_data['gender'],
                ethnicity=signup_data['ethnicity'],
                city=signup_data['city'],
                profile_image=profile_image_url,  # Add cartoon avatar!
                session_id=session_id,
                created_at=datetime.utcnow()
            )

            db.add(new_user)
            db.commit()
            db.refresh(new_user)

            # Create profile embedding in Pinecone
            from services.profile_embeddings import create_user_profile_embedding
            embedding_result = create_user_profile_embedding(new_user)
            logger.info(f"📊 Embedding creation: {embedding_result}")

            # Generate JWT tokens
            from utils.jwt_utils import create_access_token, create_refresh_token
            access_token = create_access_token(user_id)
            refresh_token = create_refresh_token(user_id)

            # Generate first feed group synchronously (only 1 group)
            logger.info(f"🔄 Generating first feed for user {user_id}")
            from services.profile_embeddings import generate_ai_groups, find_users_from_ai_description

            try:
                # Generate first AI group description (only 1 group)
                groups = generate_ai_groups(user_id, count=1)
                if groups and len(groups) > 0:
                    first_description = groups[0]  # This is a string

                    # Find users matching this description
                    matched_users = find_users_from_ai_description(
                        first_description,
                        top_k=5
                    )

                    # Build the group object
                    first_group = {
                        "description": first_description,
                        "users": matched_users
                    }

                    # Store everything in Redis
                    session_data['user_id'] = user_id
                    session_data['name'] = new_user.name
                    session_data['access_token'] = access_token
                    session_data['refresh_token'] = refresh_token
                    session_data['feed_ready'] = True
                    session_data['first_group'] = first_group
                    if profile_image_url:
                        session_data['profile_image'] = profile_image_url

                    logger.info(f"✅ First feed group generated for user {user_id}")
                else:
                    # No feed generated, store without feed
                    session_data['user_id'] = user_id
                    session_data['name'] = new_user.name
                    session_data['access_token'] = access_token
                    session_data['refresh_token'] = refresh_token
                    session_data['feed_ready'] = False
                    if profile_image_url:
                        session_data['profile_image'] = profile_image_url
                    logger.warning(f"⚠️  No feed groups generated for user {user_id}")

            except Exception as feed_error:
                # If feed generation fails, still store user data
                logger.error(f"❌ Error generating feed: {feed_error}")
                session_data['user_id'] = user_id
                session_data['name'] = new_user.name
                session_data['access_token'] = access_token
                session_data['refresh_token'] = refresh_token
                session_data['feed_ready'] = False
                if profile_image_url:
                    session_data['profile_image'] = profile_image_url

            # Save to Redis
            r.set(redis_key, json.dumps(session_data))

            logger.info(f"✅ Created user {user_id} with username {signup_data['username']}")
            logger.info(f"🔑 Generated JWT tokens for user {user_id}")

            return "verified"

        except Exception as db_error:
            db.rollback()
            logger.error(f"Database error: {db_error}")
            return f"Error creating user: {str(db_error)}"
        finally:
            db.close()

    except Exception as e:
        logger.error(f"Error finalizing signup: {e}")
        return f"Error: {str(e)}"
