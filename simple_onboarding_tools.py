"""
Simple onboarding tools for streamlined signup flow.
Collects: name, username, password, confirm password, favorite color, city, occupation
"""

from langchain_core.tools import tool
from redis_client import r
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
def set_favorite_color(session_id: str, color: str) -> str:
    """Set the user's favorite color in Redis."""
    try:
        redis_key = f"session:{session_id}"
        session_data_str = r.get(redis_key)

        if not session_data_str:
            return "Session not found"

        session_data = json.loads(session_data_str)
        session_data['signup_data']['favorite_color'] = color
        r.set(redis_key, json.dumps(session_data))

        logger.info(f"✅ Set favorite color: {color}")
        return f"Love {color}! That's a great choice."
    except Exception as e:
        logger.error(f"Error setting favorite color: {e}")
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
        required_fields = ['name', 'username', 'email', 'password', 'favorite_color', 'city', 'occupation', 'gender']
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
                favorite_color=signup_data['favorite_color'],
                city=signup_data['city'],
                session_id=session_id,
                created_at=datetime.utcnow()
            )

            db.add(new_user)
            db.commit()
            db.refresh(new_user)

            # Generate JWT tokens
            from jwt_utils import create_access_token, create_refresh_token
            access_token = create_access_token(user_id)
            refresh_token = create_refresh_token(user_id)

            # Store user_id and tokens in Redis
            session_data['user_id'] = user_id
            session_data['access_token'] = access_token
            session_data['refresh_token'] = refresh_token
            session_data['signup_data']['favorite_color'] = signup_data['favorite_color']
            session_data['signup_data']['city'] = signup_data['city']
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
