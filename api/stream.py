from dotenv import load_dotenv
import os, json, logging
from pathlib import Path
from fastapi import FastAPI, Query, BackgroundTasks, File, UploadFile, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List, Optional
import traceback
import requests
from database.db import SessionLocal
from database.models import User, Follow, FollowRequest, Notification, Report, Block, Outfit, OutfitProduct, UserProgress, OutfitTryOnSignup, UserOutfit, Brand, UserBrand
from utils.redis_client import r
from aioapns import APNs, NotificationRequest
from datetime import datetime
from api.cv_test_endpoint import router as cv_test_router

# Load .env from the root directory
load_dotenv(Path(__file__).parent.parent / ".env")

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s:     %(message)s'
)
logger = logging.getLogger(__name__)

# Agent/LLM models removed - no longer using conversational endpoints

# --- FastAPI app + SSE streaming endpoint ---
app = FastAPI()

# Include CV test endpoints
app.include_router(cv_test_router)

apns = APNs(
      key='/home/ec2-user/keys/AuthKey_2JXWNB9AAR.p8',
      key_id='2JXWNB9AAR',  # This is from your filename
      team_id='FRR7RJ635S',  # Get this from Apple Developer Portal → Membership
      topic='com.test.GlowProject',  # Your bundle identifier from Xcode
      use_sandbox=True
  )

# /chat/stream endpoint removed - signup/login agent no longer needed



@app.get("/createRedisKey")
async def create_redis_key():
    """Generate a new unique session_id."""
    import uuid
    session_id = str(uuid.uuid4())
    return {"session_id": session_id}

# /simple/stream endpoint removed - onboarding agent no longer needed


# /post/stream endpoint removed - conversational post creation no longer needed


class VerificationCodeRequest(BaseModel):
    email: str


@app.post("/auth/send-verification-code")
async def send_verification_code(request: VerificationCodeRequest):
    """
    Send a 6-digit verification code to the provided email.

    Request body:
    {
        "email": "archita@example.com"
    }

    Returns:
    {
        "status": "success",
        "message": "Verification code sent to email",
        "code": "123456"  // Only included for testing, remove in production
    }
    """
    import smtplib
    from email.message import EmailMessage
    import secrets
    import os

    try:
        email = request.email

        # Generate 6-digit verification code
        verification_code = secrets.randbelow(900000) + 100000

        # Email configuration
        EMAIL_USER = os.getenv("EMAIL_USER")
        EMAIL_PASS = os.getenv("EMAIL_PASS")

        if not EMAIL_USER or not EMAIL_PASS:
            logger.error("❌ Email credentials not configured")
            return {
                "status": "error",
                "error": "Email service not configured"
            }

        # Create email
        subject = "hey bestie 💌"
        body = f"bestieee ur Glow verification code is {verification_code}. now hurry before the universe catches on ur new era! <3"

        msg = EmailMessage()
        msg["From"] = EMAIL_USER
        msg["To"] = email
        msg["Subject"] = subject
        msg.set_content(body)

        # Send email
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
            smtp.login(EMAIL_USER, EMAIL_PASS)
            smtp.send_message(msg)

        logger.info(f"✅ Verification code {verification_code} sent to {email}")

        return {
            "status": "success",
            "message": f"Verification code sent to {email}",
            "code": str(verification_code)  # iOS will compare this with user input
        }

    except Exception as e:
        logger.error(f"❌ Error sending verification code: {e}")
        return {
            "status": "error",
            "error": str(e)
        }


class LoginRequest(BaseModel):
    username: str
    password: str


@app.post("/auth/login")
async def login(request: LoginRequest):
    """
    Login endpoint - verifies username and password, returns user data and tokens.

    Request body:
    {
        "username": "architavn",
        "password": "password123"
    }

    Returns:
    {
        "status": "success",
        "user_id": "...",
        "name": "Archita",
        "username": "architavn",
        "access_token": "...",
        "refresh_token": "...",
        "profile_image": "..."
    }
    """
    import bcrypt
    from database.db import SessionLocal
    from database.models import User

    try:
        db = SessionLocal()

        # Find user by username
        user = db.query(User).filter(User.username == request.username).first()

        if not user:
            db.close()
            return {
                "status": "error",
                "error": "Invalid username or password"
            }

        # Verify password
        if not user.password:
            db.close()
            return {
                "status": "error",
                "error": "Invalid username or password"
            }

        # Check if password matches (bcrypt)
        password_matches = bcrypt.checkpw(
            request.password.encode('utf-8'),
            user.password.encode('utf-8')
        )

        if not password_matches:
            db.close()
            return {
                "status": "error",
                "error": "Invalid username or password"
            }

        # Generate JWT tokens
        from utils.jwt_utils import create_access_token, create_refresh_token
        access_token = create_access_token(user.id)
        refresh_token = create_refresh_token(user.id)

        db.close()

        logger.info(f"✅ User {user.username} logged in successfully")

        return {
            "status": "success",
            "user_id": user.id,
            "name": user.name,
            "username": user.username,
            "access_token": access_token,
            "refresh_token": refresh_token,
            "profile_image": user.profile_image if user.profile_image else None
        }

    except Exception as e:
        logger.error(f"❌ Error during login: {e}")
        if 'db' in locals():
            db.close()
        return {
            "status": "error",
            "error": str(e)
        }


class SimpleSignupRequest(BaseModel):
    username: str
    email: str
    password: str
    name: str
    instagram_bio: str  # User's original Instagram bio
    gender: str
    ethnicity: str
    occupation: Optional[str] = None  # User's occupation (optional)


@app.post("/signup/simple")
async def simple_signup(request: SimpleSignupRequest):
    """
    Minimal signup endpoint - creates user and returns user_id + tokens immediately.
    No Redis, no AI generation, no polling - just create user and return.

    Request body:
    {
        "username": "architavn",
        "email": "archita@example.com",
        "password": "password123",
        "name": "Archita",
        "instagram_bio": "cs @ berkeley",  // not used, kept for compatibility
        "gender": "female",
        "ethnicity": "south asian",
        "occupation": "software engineer"  // optional
    }

    Returns:
    {
        "status": "success",
        "user_id": "...",
        "access_token": "...",
        "refresh_token": "..."
    }
    """
    import bcrypt
    from database.db import SessionLocal
    from database.models import User
    import uuid
    from datetime import datetime
    from utils.jwt_utils import create_access_token, create_refresh_token

    db = None
    try:
        db = SessionLocal()

        # Check if username already exists
        existing_user = db.query(User).filter(User.username == request.username).first()
        if existing_user:
            db.close()
            return {
                "status": "error",
                "error": "Username already taken"
            }

        # Hash password
        hashed_password = bcrypt.hashpw(
            request.password.encode('utf-8'),
            bcrypt.gensalt()
        ).decode('utf-8')

        # Create user (minimal - no AI generation, no profile image)
        user_id = str(uuid.uuid4())
        new_user = User(
            id=user_id,
            username=request.username,
            email=request.email,
            name=request.name,
            password=hashed_password,
            gender=request.gender,
            ethnicity=request.ethnicity,
            occupation=request.occupation,
            created_at=datetime.utcnow()
        )

        db.add(new_user)
        db.commit()
        db.refresh(new_user)

        logger.info(f"✅ Created user {user_id} (@{request.username})")

        # Generate JWT tokens
        access_token = create_access_token(user_id)
        refresh_token = create_refresh_token(user_id)

        db.close()

        # Return minimal response - just user_id and tokens
        logger.info(f"✅ Signup complete for {user_id} (@{request.username})")

        return {
            "status": "success",
            "user_id": user_id,
            "access_token": access_token,
            "refresh_token": refresh_token
        }

    except Exception as e:
        logger.error(f"❌ Error during signup: {e}")
        if db is not None:
            db.close()
        return {
            "status": "error",
            "error": str(e)
        }


@app.get("/signup/poll/{redis_id}")
async def poll_signup_status(redis_id: str):
    """
    Poll signup status by redis_id.

    Returns:
    - If processing: {"status": "processing", "message": "..."}
    - If ready: {"status": "ready", "user_id": "...", "access_token": "...", ...}
    - If error: {"status": "error", "error": "..."}
    """
    try:
        signup_data_str = r.get(f"signup:{redis_id}")

        if not signup_data_str:
            return {
                "status": "not_found",
                "message": "Signup session not found or expired"
            }

        signup_data = json.loads(signup_data_str)
        return signup_data

    except Exception as e:
        logger.error(f"❌ Error polling signup: {e}")
        return {
            "status": "error",
            "error": str(e)
        }




@app.get("/test/prompt")
async def test_anthropic_prompt():
    """
    Test route for prompt engineering with Anthropic.
    """
    try:
        from anthropic import Anthropic

        client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

        prompt = """You generate interesting, funny, glow-coded “archetype groups” that feel like characters the user might see in their world. 
NEVER generic tech-only. NEVER repetitive. Always diverse, chaotic, and scroll-stopping.

Your universe MUST include:

1. UNIVERSAL ARCHETYPES (always relevant)
   the next hasan minhaj, the next taylor swift, brown girl CEOs killing it, black founders slaying, investment banking girlies.

2. SF ARCHETYPES (for SF users)
   berkeley kids crying over 61a, stanford kids building the next google, soma engineers, boba founders, matcha girlies, angel investors looking to invest, yc, a16z, b2b ai saas. 

3. CULTURAL ARCHETYPES (based on user ethnicity)
   shaadi season girlies, indian aunties asking with love, next zarna garg. 

4. GENDER-BASED ARCHETYPES
   female investors funding cracked female founders, girlboss founders. 

5. CAREER ARCHETYPES
   startup engineers (but not too often), consultants making decks emotionally, ibanking girlies killing it.
6. DATING ARCHETYPES
sf men / yc founders who will pay for your meal and respect your ambition (respectful only)
soft men who love to listen to ur yapping


STYLE:
- cute, aesthetic, warm, funny, chaotic-but-safe
- no burnout, no crying, no trauma
- lowercase only

FORMAT:
line 1: group description (5–10 words)
line 2: short playful tag (3–5 words)

Always return ONLY a JSON array of strings.

"""

        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=100,
            messages=[{"role": "user", "content": prompt}]
        )

        result = response.content[0].text.strip()

        return {
            "status": "success",
            "prompt": prompt,
            "response": result,
            "model": "claude-sonnet-4-20250514"
        }

    except Exception as e:
        logger.error(f"❌ Error testing prompt: {e}")
        return {
            "status": "error",
            "error": str(e)
        }








@app.get("/poll/{session_id}")
async def poll_user_id(session_id: str):
    """
    Poll endpoint for iOS to check if user_id is ready after verification.
    Returns user_id if available, or status if still processing.
    """
    try:
        redis_key = f"session:{session_id}"
        session_data_str = r.get(redis_key)

        if not session_data_str:
            return {"status": "not_found", "message": "Session not found"}

        session_data = json.loads(session_data_str)
        user_id = session_data.get("user_id")

        if user_id:
            # User ID is ready! Return user_id, name, JWT tokens, profile image, and feed
            return {
                "status": "ready",
                "user_id": user_id,
                "name": session_data.get("name"),
                "access_token": session_data.get("access_token"),
                "refresh_token": session_data.get("refresh_token"),
                "profile_image": session_data.get("profile_image"),
                "feed_ready": session_data.get("feed_ready", False),
                "first_group": session_data.get("first_group"),
                "session_id": session_id
            }
        else:
            # Still processing
            return {
                "status": "processing",
                "message": "User verification in progress"
            }

    except Exception as e:
        logger.error(f"Error polling for user_id: {str(e)}")
        return {"status": "error", "error": str(e)}

@app.delete("/cleanup/{session_id}")
async def cleanup_session(session_id: str):
    """
    Delete Redis session AND SQLite checkpoints after iOS has retrieved the user_id.
    Called by iOS after polling and getting user_id.
    """
    import sqlite3
    from pathlib import Path

    try:
        # 1. Check if Redis session exists and get metadata
        redis_key = f"session:{session_id}"
        session_data_str = r.get(redis_key)

        if not session_data_str:
            logger.warning(f"⚠️  Session {session_id} not found in Redis")
            return {"status": "not_found", "session_id": session_id}

        session_data = json.loads(session_data_str)
        conversations_saved = session_data.get('conversations_saved', False)

        # 2. Delete Redis session
        r.delete(redis_key)
        logger.info(f"🗑️  Deleted Redis session {session_id}")

        # 3. Delete SQLite checkpoints (if conversations were saved)
        if conversations_saved:
            db_path = str(Path(__file__).parent / "conversations.db")
            try:
                sqlite_conn = sqlite3.connect(db_path)
                cursor = sqlite_conn.cursor()
                cursor.execute("DELETE FROM checkpoints WHERE thread_id = ?", (session_id,))
                cursor.execute("DELETE FROM writes WHERE thread_id = ?", (session_id,))
                deleted_checkpoints = cursor.rowcount
                sqlite_conn.commit()
                sqlite_conn.close()
                logger.info(f"🗑️  Deleted {deleted_checkpoints} SQLite checkpoints for session {session_id}")
            except Exception as sqlite_error:
                logger.warning(f"Failed to delete SQLite checkpoints: {sqlite_error}")

        return {
            "status": "deleted",
            "session_id": session_id,
            "redis_deleted": True,
            "sqlite_deleted": conversations_saved
        }

    except Exception as e:
        logger.error(f"Error cleaning up session {session_id}: {e}")
        return {"status": "error", "error": str(e)}

@app.get("/health")
async def health_check():
    """Health check endpoint - verifies Redis connection."""
    try:
        redis_ok = r.ping()
        return {
            "status": "healthy" if redis_ok else "unhealthy",
            "redis": "connected" if redis_ok else "disconnected"
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "redis": "disconnected",
            "error": str(e)
        }

@app.get("/debug/latest-session")
async def get_latest_session():
    """
    Debug endpoint: Get the most recent Redis session and its contents.
    Useful for Postman testing.
    """
    try:
        # Get all session keys
        keys = r.keys("session:*")

        if not keys:
            return {
                "status": "no_sessions",
                "message": "No sessions found in Redis"
            }

        # Get the most recent one (first in list)
        latest_key = keys[0].decode() if isinstance(keys[0], bytes) else keys[0]
        session_data_str = r.get(latest_key)

        if not session_data_str:
            return {
                "status": "error",
                "message": "Session key exists but no data found"
            }

        # Parse the session data
        session_data = json.loads(session_data_str)

        return {
            "status": "success",
            "session_id": latest_key.replace("session:", ""),
            "full_key": latest_key,
            "data": session_data,
            "analyze_button_pressed": session_data.get("analyze_button_pressed", False),
            "total_sessions": len(keys)
        }

    except Exception as e:
        logger.error(f"Error fetching latest session: {e}")
        return {
            "status": "error",
            "error": str(e)
        }

@app.get("/user/{user_id}/name")
async def get_user_name(user_id: str):
    """
    Get a user's name in lowercase from Postgres.

    Args:
        user_id: The user's ID in the database

    Returns:
        User's name in lowercase
    """
    from database.db import SessionLocal
    from database.models import User

    db = SessionLocal()
    try:
        # Query user by ID
        user = db.query(User).filter(User.id == user_id).first()

        if not user:
            return {
                "status": "error",
                "message": "User not found"
            }

        return {
            "status": "success",
            "user_id": user_id,
            "name": user.name.lower() if user.name else ""
        }

    except Exception as e:
        logger.error(f"Error fetching user name for {user_id}: {e}")
        return {
            "status": "error",
            "error": str(e)
        }
    finally:
        db.close()

@app.get("/user/{user_id}/gender")
async def get_user_gender_route(user_id: str):
    """
    Get a user's gender from Postgres.

    Args:
        user_id: The user's ID in the database

    Returns:
        User's gender
    """
    from database.db import SessionLocal
    from database.models import User

    db = SessionLocal()
    try:
        # Query user by ID
        user = db.query(User).filter(User.id == user_id).first()

        if not user:
            return {
                "status": "error",
                "message": "User not found"
            }

        return {
            "status": "success",
            "user_id": user_id,
            "gender": user.gender if user.gender else ""
        }

    except Exception as e:
        logger.error(f"Error fetching user gender for {user_id}: {e}")
        return {
            "status": "error",
            "error": str(e)
        }
    finally:
        db.close()

@app.get("/user/{user_id}/profile-image")
async def get_user_profile_image(user_id: str):
    """
    Get a user's profile image URL from Postgres.

    Args:
        user_id: The user's ID in the database

    Returns:
        User's profile image URL or null if they don't have one
    """
    from database.db import SessionLocal
    from database.models import User

    db = SessionLocal()
    try:
        # Query user by ID
        user = db.query(User).filter(User.id == user_id).first()

        if not user:
            return {
                "status": "error",
                "message": "User not found"
            }

        return {
            "status": "success",
            "user_id": user_id,
            "profile_image": user.profile_image if user.profile_image else None
        }

    except Exception as e:
        logger.error(f"Error fetching profile image for {user_id}: {e}")
        return {
            "status": "error",
            "error": str(e)
        }
    finally:
        db.close()

@app.get("/user/{user_id}/bio")
async def get_user_bio(user_id: str):
    """
    Get a user's bio from the database.

    Args:
        user_id: The user's ID in the database

    Returns:
        User's bio (AI-generated Instagram-style bio)
    """
    from database.db import SessionLocal
    from database.models import User

    db = SessionLocal()
    try:
        # Query user by ID
        user = db.query(User).filter(User.id == user_id).first()

        if not user:
            return {
                "status": "error",
                "message": "User not found"
            }

        return {
            "status": "success",
            "user_id": user_id,
            "bio": user.bio if user.bio else None
        }

    except Exception as e:
        logger.error(f"Error fetching bio for {user_id}: {e}")
        return {
            "status": "error",
            "error": str(e)
        }
    finally:
        db.close()

@app.get("/user/{user_id}/introduction")
async def generate_user_introduction(user_id: str):
    """
    Generate a short, chic, third-person introduction for a user.
    Uses their name and gender from Postgres to create a personalized intro.

    Args:
        user_id: The user's ID in the database

    Returns:
        A chic third-person introduction
    """

    db = SessionLocal()
    try:
        # Query user by ID
        user = db.query(User).filter(User.id == user_id).first()

        if not user:
            return {
                "status": "error",
                "message": "User not found"
            }

        if not user.name:
            return {
                "status": "error",
                "message": "User name not available"
            }

        # Get user's name and gender
        name = user.name
        gender = user.gender if user.gender else "person"

        # Create prompt for Claude to generate introduction
        prompt = f"""Generate a short, chic, third-person introduction for a user who is a {gender} and whose name is {name}.

                Requirements:
                - Start with "introducing {name.lower()}"
                - Keep it SHORT (1 sentence max)
                - Make it chic, stylish, and entertaining
                - Third-person only
                - Lowercase letters throughout
                - Gen-z/fun vibe

                Example style: "introducing mademoiselle archita", 
                "presenting miss archita", 
                "introducing the one and only archita", 
                "presenting the divine archita"

                are a few examples for women. make it end with the name of the user (no emojis allowed). 


                Now generate one for {name} ({gender}):"""

        # Call Claude API
        from anthropic import Anthropic
        client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=150,
            messages=[{
                "role": "user",
                "content": prompt
            }]
        )

        introduction = response.content[0].text.strip()

        return {
            "status": "success",
            "user_id": user_id,
            "name": name,
            "gender": gender,
            "introduction": introduction
        }

    except Exception as e:
        logger.error(f"Error generating introduction for {user_id}: {e}")
        return {
            "status": "error",
            "error": str(e)
        }
    finally:
        db.close()

@app.get("/user/{user_id}/twoCaptions")
async def generate_user_captions(user_id: str):
    """
    Generate two strong, bold captions about the user for their profile.
    These will be the biggest/boldest text on their profile.
    Uses conversations and user data from Postgres.

    Args:
        user_id: The user's ID in the database

    Returns:
        Two short, chic, bold captions
    """

    db = SessionLocal()
    try:
        # Query user by ID
        user = db.query(User).filter(User.id == user_id).first()

        if not user:
            return {
                "status": "error",
                "message": "User not found"
            }

        # Gather all available user data
        name = user.name if user.name else ""
        gender = user.gender if user.gender else ""
        university = user.university if user.university else ""
        college_major = user.college_major if user.college_major else ""
        occupation = user.occupation if user.occupation else ""
        conversations = user.conversations if user.conversations else []

        # Create prompt for Claude to generate captions
        prompt = f"""Generate TWO strong, bold captions about this user for their profile. These will be the BIGGEST and BOLDEST text on their profile.

User Information:
- Name: {name}
- Gender: {gender}
- University: {university}
- Major: {college_major}
- Occupation: {occupation}
- Conversations: {json.dumps(conversations)}

Requirements:
- Generate EXACTLY 2 captions
- Each caption should be SHORT (3-7 words max)
- Bold, confident, attention-grabbing
- Chic and entertaining
- Based on their personality from conversations
- Lowercase preferred
- Third person.

IMPORTANT: Return ONLY the two captions, one per line. NO explanatory text, NO introductions, NO symbols like ** or bullets. Just the captions themselves.

Analyze their conversations and info to capture their vibe. Generate 2 strong captions:"""

        # Call Claude API
        from anthropic import Anthropic
        client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=150,
            messages=[{
                "role": "user",
                "content": prompt
            }]
        )

        # Parse response to extract two captions
        response_text = response.content[0].text.strip()

        # Split by newlines or numbers to get two captions
        lines = [line.strip() for line in response_text.split('\n') if line.strip()]

        # Clean up any numbering, symbols, and explanatory text
        captions = []
        for line in lines:
            # Skip lines that look like explanatory text
            lower_line = line.lower()
            if any(phrase in lower_line for phrase in ['based on', 'here are', 'these captions', 'analyzing', 'capturing']):
                continue

            # Remove numbering, quotes, asterisks, bullets, etc.
            cleaned = line.lstrip('12345678.-) ').strip('"\'*•–—')
            # Remove any remaining asterisks in the middle
            cleaned = cleaned.replace('**', '').replace('*', '')
            if cleaned and len(cleaned) > 2:  # Filter out very short fragments
                captions.append(cleaned)

        # Ensure we have exactly 2 captions
        if len(captions) < 2:
            captions = ["chic and mysterious", "living my best life"]

        caption1 = captions[0]
        caption2 = captions[1] if len(captions) > 1 else captions[0]

        return {
            "status": "success",
            "user_id": user_id,
            "caption1": caption1,
            "caption2": caption2
        }

    except Exception as e:
        logger.error(f"Error generating captions for {user_id}: {e}")
        return {
            "status": "error",
            "error": str(e)
        }
    finally:
        db.close()

@app.get("/user/{user_id}/eightCaptions")
async def generate_eight_captions(user_id: str):
    """
    Generate 8 captions to describe the user for their profile.
    Main character energy, third person.
    Uses conversations and user data from Postgres.

    Args:
        user_id: The user's ID in the database

    Returns:
        Eight captions describing the user
    """

    db = SessionLocal()
    try:
        # Query user by ID
        user = db.query(User).filter(User.id == user_id).first()

        if not user:
            return {
                "status": "error",
                "message": "User not found"
            }

        # Gather all available user data
        name = user.name if user.name else ""
        gender = user.gender if user.gender else ""
        university = user.university if user.university else ""
        college_major = user.college_major if user.college_major else ""
        occupation = user.occupation if user.occupation else ""
        sexuality = user.sexuality if user.sexuality else ""
        ethnicity = user.ethnicity if user.ethnicity else ""
        pronouns = user.pronouns if user.pronouns else ""
        conversations = user.conversations if user.conversations else []

        # Create prompt for Claude to generate 8 captions
        prompt = f"""Generate EIGHT captions to describe this user for their profile. Main character energy, third person.

User Information:
- Name: {name}
- Gender: {gender}
- Pronouns: {pronouns}
- University: {university}
- Major: {college_major}
- Occupation: {occupation}
- Sexuality: {sexuality}
- Ethnicity: {ethnicity}
- Conversations: {json.dumps(conversations)}

Requirements:
- Generate EXACTLY 8 captions, make sure they are specific to the user's personality, and capture specfic aspects of who they are.
- Each caption should be SHORT (3-8 words max)
- Third person only
- Main character energy
- Chic, fun, entertaining
- Based on their personality from conversations
- Lowercase preferred
- Capture different aspects of who they are

IMPORTANT: Return ONLY the eight captions, one per line. NO explanatory text, NO introductions, NO symbols like ** or bullets. Just the captions themselves.

Analyze their conversations and info deeply. Generate 8 captions that paint a full picture of who they are:"""

        # Call Claude API
        from anthropic import Anthropic
        client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=300,
            messages=[{
                "role": "user",
                "content": prompt
            }]
        )

        # Parse response to extract 8 captions
        response_text = response.content[0].text.strip()

        # Split by newlines to get captions
        lines = [line.strip() for line in response_text.split('\n') if line.strip()]

        # Clean up any numbering, symbols, and explanatory text
        captions = []
        for line in lines:
            # Skip lines that look like explanatory text
            lower_line = line.lower()
            if any(phrase in lower_line for phrase in ['based on', 'here are', 'these captions', 'analyzing', 'capturing', 'paint a', 'who they are']):
                continue

            # Remove numbering, quotes, asterisks, bullets, etc.
            cleaned = line.lstrip('12345678.-) ').strip('"\'*•–—')
            # Remove any remaining asterisks in the middle
            cleaned = cleaned.replace('**', '').replace('*', '')
            if cleaned and len(cleaned) > 2:  # Filter out very short fragments
                captions.append(cleaned)

        # Ensure we have exactly 8 captions
        default_captions = [
            "living their best life",
            "chic and mysterious",
            "main character energy",
            "your new favorite person",
            "vibes immaculate",
            "certified trendsetter",
            "story worth hearing",
            "effortlessly cool"
        ]

        while len(captions) < 8:
            captions.append(default_captions[len(captions)])

        # Return exactly 8 captions
        return {
            "status": "success",
            "user_id": user_id,
            "captions": captions[:8]
        }

    except Exception as e:
        logger.error(f"Error generating 8 captions for {user_id}: {e}")
        return {
            "status": "error",
            "error": str(e)
        }
    finally:
        db.close()

@app.get("/user/{user_id}/topQuestions")
async def generate_top_questions(user_id: str):
    """
    Generate the top 2 questions this user might ask based on their conversation history.
    Uses conversations from Postgres.

    Args:
        user_id: The user's ID in the database

    Returns:
        Two questions the user might ask
    """
    db = SessionLocal()
    try:
        # Query user by ID
        user = db.query(User).filter(User.id == user_id).first()

        if not user:
            return {
                "status": "error",
                "message": "User not found"
            }

        # Get user data
        name = user.name if user.name else ""
        conversations = user.conversations if user.conversations else []

        if not conversations:
            return {
                "status": "error",
                "message": "No conversations found for this user"
            }

        # Create prompt for Claude to analyze conversations and generate questions
        prompt = f"""Analyze this user's conversation history and generate the top 2 questions / things they'd they're most likely talk about / things they are most likely to ask next.

User Information:
- Name: {name}
- Conversations: {json.dumps(conversations)}

Based on their conversation patterns, interests, and personality, what are the top 2 questions they would most likely ask?

Requirements:
- Generate EXACTLY 2 questions
- Questions should feel natural and aligned with their interests/personality
- Each question should be SHORT (5-15 words)
- Based on what they've talked about in conversations
- Write questions in girly, genz, human tone. you can be humorous. 

IMPORTANT: Return ONLY the two questions, one per line. NO explanatory text, NO introductions, NO numbering, NO symbols like ** or bullets. Just the questions themselves.

Generate 2 questions:"""

        # Call Claude API
        from anthropic import Anthropic
        client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=200,
            messages=[{
                "role": "user",
                "content": prompt
            }]
        )

        # Parse response to extract two questions
        response_text = response.content[0].text.strip()

        # Split by newlines to get questions
        lines = [line.strip() for line in response_text.split('\n') if line.strip()]

        # Clean up any numbering, symbols, and explanatory text
        questions = []
        for line in lines:
            # Skip lines that look like explanatory text
            lower_line = line.lower()
            if any(phrase in lower_line for phrase in ['based on', 'here are', 'these questions', 'analyzing', 'likely to ask']):
                continue

            # Remove numbering, quotes, asterisks, bullets, etc.
            cleaned = line.lstrip('12345678.-) ').strip('"\'*•–—')
            # Remove any remaining asterisks in the middle
            cleaned = cleaned.replace('**', '').replace('*', '')
            if cleaned and len(cleaned) > 5:  # Filter out very short fragments
                questions.append(cleaned)

        # Ensure we have exactly 2 questions
        if len(questions) < 2:
            questions = [
                "what's your favorite thing to do on weekends?",
                "any fun plans coming up?"
            ]

        question1 = questions[0]
        question2 = questions[1] if len(questions) > 1 else questions[0]

        return {
            "status": "success",
            "user_id": user_id,
            "question1": question1,
            "question2": question2
        }

    except Exception as e:
        logger.error(f"Error generating questions for {user_id}: {e}")
        return {
            "status": "error",
            "error": str(e)
        }
    finally:
        db.close()

@app.get("/searchUsers")
async def search_users(query: str = Query(..., min_length=1), user_id: str = Query(...)):
    """
    Search for users by username or name.
    Returns top 5 matching results, excluding blocked users.

    Args:
        query: Search string (username or name)
        user_id: ID of user performing the search (to filter blocked users)

    Returns:
        List of up to 5 matching users with their basic info
    """
    db = SessionLocal()
    try:
        # Normalize query to lowercase for case-insensitive search
        search_term = query.lower().strip()

        if not search_term:
            return {
                "status": "error",
                "message": "Search query cannot be empty"
            }

        # Get blocked users (users you blocked + users who blocked you) to exclude from search
        blocked_by_me = db.query(Block.blocked_id).filter(Block.blocker_id == user_id).all()
        blocked_me = db.query(Block.blocker_id).filter(Block.blocked_id == user_id).all()
        blocked_user_ids = [b[0] for b in blocked_by_me] + [b[0] for b in blocked_me]

        # Query database for users matching username or name, excluding blocked users
        # Using ilike for case-insensitive partial matching
        query_filter = (
            (User.username.ilike(f"%{search_term}%")) |
            (User.name.ilike(f"%{search_term}%"))
        )

        # Exclude blocked users
        if blocked_user_ids:
            query_filter = query_filter & (~User.id.in_(blocked_user_ids))

        matching_users = db.query(User).filter(query_filter).limit(5).all()

        # Format results
        results = []
        for user in matching_users:
            results.append({
                "user_id": user.id,
                "username": user.username,
                "name": user.name,
                "university": user.university if user.university else None,
                "occupation": user.occupation if user.occupation else None
            })

        return {
            "status": "success",
            "query": query,
            "count": len(results),
            "results": results
        }

    except Exception as e:
        logger.error(f"Error searching users with query '{query}': {e}")
        return {
            "status": "error",
            "error": str(e)
        }
    finally:
        db.close()

@app.get("/user/{user_id}/currentEra")
async def get_current_era(user_id: str):
    """
    Analyze the user's conversations and return a cinematic description of their current "era".
    Very Gen-Z, very girly, very main character energy.

    Args:
        user_id: The user's ID in the database

    Returns:
        A cinematic 1-3 sentence description of what era they're in right now
    """
    db = SessionLocal()
    try:
        # Query user by ID
        user = db.query(User).filter(User.id == user_id).first()

        if not user:
            return {
                "status": "error",
                "message": "User not found"
            }

        # Get user data
        name = user.name if user.name else ""
        conversations = user.conversations if user.conversations else []

        if not conversations:
            return {
                "status": "error",
                "message": "No conversations found for this user"
            }

        # Create prompt for Claude to analyze and describe their current era
        prompt = f"""Analyze this user's recent conversations and describe what "era" they're currently in.

User Information:
- Name: {name}
- Conversations: {json.dumps(conversations)}

Based on their recent conversations, what's happening in their life right now? What era are they entering or living through?

Requirements:
- Write 1-3 sentences MAX
- Cinematic and dramatic tone
- Very Gen-Z, very girly. 
- Third person (e.g., "{name} is entering her law school era")
- Lowercase letters
- Focus on what's currently happening or about to happen in their life
- Make it feel like a movie narration
- three sentences max. 

IMPORTANT: Return ONLY the era description. NO explanatory text, NO introductions. Just the cinematic description itself.

Analyze their conversations and describe their current era:"""

        # Call Claude API
        from anthropic import Anthropic
        client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=200,
            messages=[{
                "role": "user",
                "content": prompt
            }]
        )

        era_description = response.content[0].text.strip()

        # Clean up any unwanted formatting
        era_description = era_description.replace('**', '').replace('*', '')

        return {
            "status": "success",
            "user_id": user_id,
            "era": era_description
        }

    except Exception as e:
        logger.error(f"Error generating era description for {user_id}: {e}")
        return {
            "status": "error",
            "error": str(e)
        }
    finally:
        db.close()

class EraPush(BaseModel):
    user_id: str
    era_text: str

# ===== PUSH NOTIFICATION ROUTES =====

class DeviceTokenUpdate(BaseModel):
    user_id: str
    device_token: str

@app.post("/user/device-token")
async def update_device_token(token_data: DeviceTokenUpdate):
    """
    Register or update a user's APNs device token for push notifications.

    Request body:
    {
        "user_id": "uuid-string",
        "device_token": "apns-device-token"
    }
    """
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == token_data.user_id).first()

        if not user:
            return {
                "status": "error",
                "message": "User not found"
            }

        user.device_token = token_data.device_token
        db.commit()

        logger.info(f"✅ Updated device token for user {token_data.user_id}")

        return {
            "status": "success",
            "message": "Device token updated successfully",
            "user_id": token_data.user_id
        }

    except Exception as e:
        logger.error(f"Error updating device token: {e}")
        db.rollback()
        return {
            "status": "error",
            "error": str(e)
        }
    finally:
        db.close()

# ===== FOLLOW SYSTEM ROUTES =====

# Pydantic models for follow requests
class FollowRequestCreate(BaseModel):
    requester_id: str
    requested_id: str

class FollowActionRequest(BaseModel):
    requester_id: str
    requested_id: str

def generate_relationship_sentence(user_a_name: str, user_a_bio: str, user_b_name: str, user_b_bio: str) -> str:
    """
    Generate an sentence explaining how two users might know each other.
    Based on their bios, infer the connection.

    Args:
        user_a_name: Name of the first user (person in the followers/following list)
        user_a_bio: Bio of the first user
        user_b_name: Name of the second user (owner of the list)
        user_b_bio: Bio of the second user

    Returns:
        Short sentence explaining the relationship
    """
    from anthropic import Anthropic

    logger.info(f"🤖 Generating relationship sentence between {user_a_name} and {user_b_name}...")

    try:
        prompt = f"""Generate a SHORT, unique sentence explaining how these two people might know each other.

{user_a_name}'s bio: {user_a_bio if user_a_bio else "No bio"}
{user_b_name}'s bio: {user_b_bio if user_b_bio else "No bio"}

CRITICAL: Each sentence MUST have a DIFFERENT structure. Pick ONE random pattern from below:

PATTERN 1 - direct connection style:
"knows {user_a_name} bc they went to school tg"
"went to {user_a_name}'s hs"
"from {user_a_name}'s hometown in massachusetts"

PATTERN 1 - "Both" style:
"both in tech apparently"
"both cornell grads probably"
"both building in sf"

PATTERN 3 - "Met" style:
"met thru startup events"
"met at some conference"
"met through sf tech scene"

PATTERN 4 - "Knows" style:
"knows them from twitter"
"knows them thru work"

PATTERN 6 - Casual inference:
"they're in similar tech spaces"
"overlap in the tech scene"
"running in same crowds"

RULES:
- lowercase only
- 3-6 words MAXIMUM
- Pick a RANDOM pattern from above
- Be specific if bios mention school/work/location
- Soft uncertainty is ok (probably, maybe, seems like)

Return ONE sentence, lowercase, no quotes."""

        client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=30,
            temperature=1.0,  # Maximum creativity/randomness
            messages=[{"role": "user", "content": prompt}]
        )

        sentence = response.content[0].text.strip().strip('"\'')
        logger.info(f"✨ Generated relationship: {sentence}")
        return sentence

    except Exception as e:
        logger.error(f"❌ Error generating relationship sentence: {e}")
        return "connected somehow"  # Fallback

def generate_followers_page_title(name: str, gender: str, follower_count: int) -> str:
    """
    Generate a chill, gen-z page title for someone's followers page.

    Args:
        name: The profile owner's name
        gender: Their gender
        follower_count: How many followers they have

    Returns:
        Short page title sentence
    """
    from anthropic import Anthropic

    logger.info(f"🤖 Generating followers page title for {name} ({follower_count} followers)...")

    try:
        prompt = f"""Generate a title describing {name}'s followers.

Context:
- Name: {name}
- Gender: {gender}
- Follower count: {follower_count}

RULES:
- lowercase only
- 5-7 words max
- human gen-z tone, third person. human = casual, slightly imperfect, almost throwaway, conversational.
- reference the follower count

Examples, notice how this sounds human:
"50 is such a deliberate number"
"i kind of like 1024"
“hm 1024.”
“wait 1024 lol.”
“lowkey like 1024.”
"1024 followers i like it.”
“hm 1024 followers.”
“wait why does 1024 followers feel clean.”
"oh 1024 followers"
“1024 followers lol”

Return ONE sentence, lowercase."""

        client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=40,
            messages=[{"role": "user", "content": prompt}]
        )

        sentence = response.content[0].text.strip().strip('"\'')
        logger.info(f"✨ Generated followers page title: {sentence}")
        return sentence

    except Exception as e:
        logger.error(f"❌ Error generating followers page title: {e}")
        return f"{name} has {follower_count} followers"  # Fallback

def generate_following_page_title(name: str, gender: str, following_count: int) -> str:
    """
    Generate a chill, gen-z page title for someone's following page.

    Args:
        name: The profile owner's name
        gender: Their gender
        following_count: How many people they follow

    Returns:
        Short page title sentence
    """
    from anthropic import Anthropic

    logger.info(f"🤖 Generating following page title for {name} ({following_count} following)...")

    try:
        prompt = f"""Generate a super short, chill, gen-z page title describing who {name} follows.

Context:
- Name: {name}
- Gender: {gender}
- Following count: {following_count}

RULES:
- lowercase only
- 5-8 words max
- casual, chill gen-z tone
- reference the person by name
- reference the following count
- make it feel like a page header/title

Examples:
"josh follows 30 people. building the circle"
"sarah's following 15 people. curating the feed"
"alex follows 50 people. keeping tabs on everyone"
"emma follows 5 people. selective energy only"

Return ONE sentence, lowercase."""

        client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=40,
            messages=[{"role": "user", "content": prompt}]
        )

        sentence = response.content[0].text.strip().strip('"\'')
        logger.info(f"✨ Generated following page title: {sentence}")
        return sentence

    except Exception as e:
        logger.error(f"❌ Error generating following page title: {e}")
        return f"{name} follows {following_count} people"  # Fallback

def generate_follower_sentence(gender: str, follower_count: int, following_count: int) -> str:
    """
    Generate a smart, dynamic AI sentence about a user's social stats.
    AI decides which stat is more interesting to highlight.

    Args:
        gender: User's gender for context
        follower_count: Number of people who follow this user
        following_count: Number of people this user follows

    Returns:
        Generated sentence string, or fallback if AI generation fails
    """
    from anthropic import Anthropic

    logger.info(f"🤖 Generating profile sentence - Followers: {follower_count}, Following: {following_count}...")

    try:
        prompt = f"""Generate a SHORT, funny, self-aware sentence about someone's social media stats.

Context:
- Gender: {gender}
- Followers: {follower_count}
- Following: {following_count}

RULES:
- lowercase
- self-aware/sassy/deadpan
- MAX 7 WORDS. 
- third person.
- reference the numbers directly
- BE SMART: pick which stat is more interesting/funny to highlight:
  * If following > followers: make a RESPECTFUL, uplifting joke about following more than your followers
  * If follower_count is impressive: celebrate it
  * If both are low: self-aware humor about starting out, respectfully. 

Make sure the sentence actually relates to the following / follower count directly and keep it clear. 
Examples (all 7-10 words):
"0 followers, 1 following. picture a crowd here rn"
"3 followers, 3 following. equilibrium achieved!"
"10 followers. double digits!!"
"1 follower, 8 following. low numbers but she's just early"

Return ONE sentence, lowercase."""

        client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=60,
            messages=[{"role": "user", "content": prompt}]
        )

        sentence = response.content[0].text.strip()
        logger.info(f"✨ Generated profile sentence: {sentence}")
        return sentence

    except Exception as e:
        logger.error(f"❌ Error generating profile sentence: {e}")
        # Fallback sentence
        return f"{follower_count} followers, {following_count} following. the vibes are immaculate"

@app.post("/follow/request")
async def send_follow_request(request_data: FollowRequestCreate):
    """
    User A sends a follow request to User B.
    If User B's profile is private, this creates a pending request.
    If User B's profile is public, this immediately creates a follow relationship.

    Request body:
    {
        "requester_id": "user_a_id",
        "requested_id": "user_b_id"
    }
    """
    from utils.push_notifications import send_follow_request_notification

    db = SessionLocal()
    try:
        # Check if both users exist
        requester = db.query(User).filter(User.id == request_data.requester_id).first()
        requested = db.query(User).filter(User.id == request_data.requested_id).first()

        if not requester or not requested:
            return {
                "status": "error",
                "message": "One or both users not found"
            }

        # Check if already following
        existing_follow = db.query(Follow).filter(
            Follow.follower_id == request_data.requester_id,
            Follow.following_id == request_data.requested_id
        ).first()

        if existing_follow:
            return {
                "status": "error",
                "message": "Already following this user"
            }

        # If profile is PUBLIC, immediately create follow relationship
        if not requested.is_private:
            new_follow = Follow(
                follower_id=request_data.requester_id,
                following_id=request_data.requested_id
            )
            db.add(new_follow)
            db.commit()
            db.refresh(new_follow)

            logger.info(f"✅ User {request_data.requester_id} now follows {request_data.requested_id} (public profile)")

            # Regenerate follower sentences for BOTH users and save to database
            # User A (requester) - their following count increased
            requester_follower_count = db.query(Follow).filter(Follow.following_id == request_data.requester_id).count()
            requester_following_count = db.query(Follow).filter(Follow.follower_id == request_data.requester_id).count()
            requester.follower_sentence = generate_follower_sentence(
                gender=requester.gender,
                follower_count=requester_follower_count,
                following_count=requester_following_count
            )

            # User B (requested) - their follower count increased
            requested_follower_count = db.query(Follow).filter(Follow.following_id == request_data.requested_id).count()
            requested_following_count = db.query(Follow).filter(Follow.follower_id == request_data.requested_id).count()
            requested.follower_sentence = generate_follower_sentence(
                gender=requested.gender,
                follower_count=requested_follower_count,
                following_count=requested_following_count
            )

            # Save both sentences to database
            db.commit()
            logger.info(f"✨ Updated follower sentences for both users")

            # Send in-app notification to the followed user
            requester_name = requester.name if requester.name else requester.username
            era_notification = Notification(
                user_id=request_data.requested_id,
                actor_id=request_data.requester_id,
                content=f"{requester_name} started following you"
            )
            db.add(era_notification)
            db.commit()

            # Send push notification to the followed user
            from utils.push_notifications import send_new_follower_notification
            if requested.device_token:
                await send_new_follower_notification(
                    device_token=requested.device_token,
                    follower_name=requester_name,
                    follower_id=requester.id,
                    follower_username=requester.username
                )
            else:
                logger.info(f"⚠️  No device token for user {request_data.requested_id}, skipping push notification")

            return {
                "status": "success",
                "message": "Now following (public profile)",
                "follow_id": new_follow.id
            }

        # If profile is PRIVATE, create a follow request
        # Check if request already exists (IDEMPOTENCY)
        existing_request = db.query(FollowRequest).filter(
            FollowRequest.requester_id == request_data.requester_id,
            FollowRequest.requested_id == request_data.requested_id
        ).first()

        if existing_request:
            # Request already exists - return success (idempotent)
            logger.info(f"⚠️  Follow request from {request_data.requester_id} to {request_data.requested_id} already exists")
            return {
                "status": "success",
                "message": "Follow request already sent"
            }

        # Create new follow request
        new_request = FollowRequest(
            requester_id=request_data.requester_id,
            requested_id=request_data.requested_id
        )

        db.add(new_request)
        db.commit()
        db.refresh(new_request)

        logger.info(f"✅ User {request_data.requester_id} sent follow request to {request_data.requested_id}")

        # Check if notification already exists (prevent duplicates)
        requester_name = requester.name if requester.name else requester.username
        existing_notification = db.query(Notification).filter(
            Notification.user_id == request_data.requested_id,
            Notification.actor_id == request_data.requester_id,
            Notification.content.like(f"%{requester_name} wants to follow you%")
        ).first()

        if not existing_notification:
            # Only create notification if it doesn't exist
            era_notification = Notification(
                user_id=request_data.requested_id,  # Notification belongs to User B
                actor_id=request_data.requester_id,  # The requester is the actor
                content=f"{requester_name} wants to follow you"
            )
            db.add(era_notification)
            db.commit()
            logger.info(f"✅ Created follow request notification for {request_data.requested_id}")
        else:
            logger.info(f"⚠️  Notification already exists, skipping duplicate")

        # Send push notification to the requested user (User B)
        if requested.device_token:
            await send_follow_request_notification(
                device_token=requested.device_token,
                requester_name=requester_name,
                requester_id=requester.id,
                requester_username=requester.username
            )
        else:
            logger.info(f"⚠️  No device token for user {request_data.requested_id}, skipping push notification")

        return {
            "status": "success",
            "message": "Follow request sent",
            "request_id": new_request.id
        }

    except Exception as e:
        logger.error(f"Error sending follow request: {e}")
        db.rollback()
        return {
            "status": "error",
            "error": str(e)
        }
    finally:
        db.close()

@app.get("/follow/requests/{user_id}")
async def get_follow_requests(user_id: str):
    """
    Get all pending follow requests for a user.
    Shows who wants to follow them.

    Args:
        user_id: The user's ID

    Returns:
        List of pending follow requests with requester info
    """
    db = SessionLocal()
    try:
        # Get all pending requests for this user
        requests = db.query(FollowRequest).filter(
            FollowRequest.requested_id == user_id
        ).order_by(FollowRequest.created_at.desc()).all()

        # Format results with requester info
        results = []
        for req in requests:
            requester = db.query(User).filter(User.id == req.requester_id).first()
            if requester:
                results.append({
                    "request_id": req.id,
                    "requester_id": requester.id,
                    "username": requester.username,
                    "name": requester.name,
                    "university": requester.university,
                    "occupation": requester.occupation,
                    "created_at": req.created_at.isoformat()
                })

        return {
            "status": "success",
            "user_id": user_id,
            "count": len(results),
            "requests": results
        }

    except Exception as e:
        logger.error(f"Error fetching follow requests for {user_id}: {e}")
        return {
            "status": "error",
            "error": str(e)
        }
    finally:
        db.close()

@app.post("/follow/accept")
async def accept_follow_request(request_data: FollowActionRequest):
    """
    User B accepts User A's follow request.
    Creates the actual follow relationship and deletes the pending request.

    Request body:
    {
        "requester_id": "user_a_id",
        "requested_id": "user_b_id"
    }
    """
    from utils.push_notifications import send_follow_accepted_notification

    db = SessionLocal()
    try:
        # Find the pending request
        pending_request = db.query(FollowRequest).filter(
            FollowRequest.requester_id == request_data.requester_id,
            FollowRequest.requested_id == request_data.requested_id
        ).first()

        if not pending_request:
            return {
                "status": "error",
                "message": "Follow request not found"
            }

        # Get both users for push notification
        requester = db.query(User).filter(User.id == request_data.requester_id).first()
        accepter = db.query(User).filter(User.id == request_data.requested_id).first()

        # Create the actual follow relationship
        new_follow = Follow(
            follower_id=request_data.requester_id,
            following_id=request_data.requested_id
        )

        db.add(new_follow)

        # Delete the pending request
        db.delete(pending_request)

        # Delete the follow request notification from eras table
        follow_request_notif = db.query(Notification).filter(
            Notification.user_id == request_data.requested_id,
            Notification.actor_id == request_data.requester_id,
            Notification.content.like('%wants to follow you%')
        ).first()
        if follow_request_notif:
            db.delete(follow_request_notif)
            logger.info(f"🗑️  Deleted follow request notification for {request_data.requested_id}")

        db.commit()

        logger.info(f"✅ User {request_data.requested_id} accepted follow from {request_data.requester_id}")

        # Regenerate follower sentences for BOTH users and save to database
        # User A (requester) - their following count increased
        requester_follower_count = db.query(Follow).filter(Follow.following_id == request_data.requester_id).count()
        requester_following_count = db.query(Follow).filter(Follow.follower_id == request_data.requester_id).count()
        requester.follower_sentence = generate_follower_sentence(
            gender=requester.gender,
            follower_count=requester_follower_count,
            following_count=requester_following_count
        )

        # User B (accepter) - their follower count increased
        accepter_follower_count = db.query(Follow).filter(Follow.following_id == request_data.requested_id).count()
        accepter_following_count = db.query(Follow).filter(Follow.follower_id == request_data.requested_id).count()
        accepter.follower_sentence = generate_follower_sentence(
            gender=accepter.gender,
            follower_count=accepter_follower_count,
            following_count=accepter_following_count
        )

        # Save both sentences to database
        db.commit()
        logger.info(f"✨ Updated follower sentences for both users")

        # Generate AI message for era notification
        accepter_name = accepter.name if accepter.name else accepter.username
        accepter_conversations = accepter.conversations if accepter.conversations else []

        # Generate personalized acceptance message with Claude
        notification_message = f"{accepter_name} accepted your follow request"
        if accepter_conversations and len(accepter_conversations) > 0:
            try:
                from anthropic import Anthropic
                client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

                prompt = f"""Generate a fun notification for when someone accepts a follow request.

User who accepted: {accepter_name}
Their conversations: {json.dumps(accepter_conversations)}

Write: "{accepter_name} accepted your follow request, gear up theyre entering [describe their current era/vibe]"

Requirements:
- ONE sentence
- 15-25 words
- Lowercase, casual, gen-z
- No emojis
- Based on their conversations, what era are they in?

Example: "sarah accepted your follow request, gear up she's entering her law school and travel planning era"

Return ONLY the text, no quotes."""

                response = client.messages.create(
                    model="claude-sonnet-4-20250514",
                    max_tokens=100,
                    messages=[{"role": "user", "content": prompt}]
                )

                notification_message = response.content[0].text.strip().strip('"\'')
            except Exception as e:
                logger.error(f"Error generating AI message: {e}")

        # Create era notification for User A (the requester)
        era_notification = Notification(
            user_id=request_data.requester_id,  # Notification belongs to User A
            actor_id=request_data.requested_id,  # The accepter is the actor
            content=notification_message
        )
        db.add(era_notification)
        db.commit()

        # Send push notification to the requester (User A) that their request was accepted
        if requester and requester.device_token:
            await send_follow_accepted_notification(
                device_token=requester.device_token,
                accepter_name=accepter_name,
                accepter_conversations=accepter_conversations,
                accepter_id=accepter.id,
                accepter_username=accepter.username
            )
        else:
            logger.info(f"⚠️  No device token for user {request_data.requester_id}, skipping push notification")

        return {
            "status": "success",
            "message": "Follow request accepted"
        }

    except Exception as e:
        logger.error(f"Error accepting follow request: {e}")
        db.rollback()
        return {
            "status": "error",
            "error": str(e)
        }
    finally:
        db.close()

@app.post("/follow/decline")
async def decline_follow_request(request_data: FollowActionRequest):
    """
    User B declines User A's follow request.
    Simply deletes the pending request.

    Request body:
    {
        "requester_id": "user_a_id",
        "requested_id": "user_b_id"
    }
    """
    db = SessionLocal()
    try:
        # Find the pending request
        pending_request = db.query(FollowRequest).filter(
            FollowRequest.requester_id == request_data.requester_id,
            FollowRequest.requested_id == request_data.requested_id
        ).first()

        if not pending_request:
            return {
                "status": "error",
                "message": "Follow request not found"
            }

        # Delete the pending request
        db.delete(pending_request)

        # Delete the follow request notification from eras table
        follow_request_notif = db.query(Notification).filter(
            Notification.user_id == request_data.requested_id,
            Notification.actor_id == request_data.requester_id,
            Notification.content.like('%wants to follow you%')
        ).first()
        if follow_request_notif:
            db.delete(follow_request_notif)
            logger.info(f"🗑️  Deleted follow request notification for {request_data.requested_id}")

        db.commit()

        logger.info(f"❌ User {request_data.requested_id} declined follow from {request_data.requester_id}")

        return {
            "status": "success",
            "message": "Follow request declined"
        }

    except Exception as e:
        logger.error(f"Error declining follow request: {e}")
        db.rollback()
        return {
            "status": "error",
            "error": str(e)
        }
    finally:
        db.close()

@app.post("/follow/cancel")
async def cancel_follow_request(request_data: FollowActionRequest):
    """
    User A cancels their own follow request to User B.
    This happens when user clicks "Requested" button again to unrequest.

    Request body:
    {
        "requester_id": "user_a_id",  // Your ID (the one who sent the request)
        "requested_id": "user_b_id"   // The person you sent request to
    }
    """
    db = SessionLocal()
    try:
        # Find the pending request
        pending_request = db.query(FollowRequest).filter(
            FollowRequest.requester_id == request_data.requester_id,
            FollowRequest.requested_id == request_data.requested_id
        ).first()

        if not pending_request:
            return {
                "status": "error",
                "message": "Follow request not found"
            }

        # Delete the pending request
        db.delete(pending_request)
        db.commit()

        logger.info(f"🔙 User {request_data.requester_id} cancelled follow request to {request_data.requested_id}")

        return {
            "status": "success",
            "message": "Follow request cancelled"
        }

    except Exception as e:
        logger.error(f"Error cancelling follow request: {e}")
        db.rollback()
        return {
            "status": "error",
            "error": str(e)
        }
    finally:
        db.close()

@app.get("/user/{user_id}/followers")
async def get_followers(user_id: str, limit: int = 5, offset: int = 0):
    """
    Get users who follow this user (User B's followers) with pagination.
    Includes AI-generated relationship sentence for each follower.

    Args:
        user_id: The user's ID
        limit: Number of followers to return (default 5, max 100)
        offset: Number of followers to skip (default 0)

    Returns:
        Paginated list of followers with their info and relationship sentences
    """
    db = SessionLocal()
    try:
        # Validate pagination params
        limit = min(limit, 100)  # Max 100 per page
        offset = max(offset, 0)  # No negative offsets

        # Get the profile owner (User B)
        profile_owner = db.query(User).filter(User.id == user_id).first()
        if not profile_owner:
            return {
                "status": "error",
                "message": "User not found"
            }

        # Get total count of followers
        total_count = db.query(Follow).filter(
            Follow.following_id == user_id
        ).count()

        # Get paginated follows where this user is being followed
        follows = db.query(Follow).filter(
            Follow.following_id == user_id
        ).order_by(Follow.created_at.desc()).limit(limit).offset(offset).all()

        # Get follower info with relationship sentences
        results = []
        for follow in follows:
            follower = db.query(User).filter(User.id == follow.follower_id).first()
            if follower:
                # Generate relationship sentence
                relationship_sentence = generate_relationship_sentence(
                    user_a_name=follower.name,
                    user_a_bio=follower.bio if follower.bio else "",
                    user_b_name=profile_owner.name,
                    user_b_bio=profile_owner.bio if profile_owner.bio else ""
                )

                results.append({
                    "user_id": follower.id,
                    "username": follower.username,
                    "name": follower.name,
                    "university": follower.university,
                    "occupation": follower.occupation,
                    "followed_at": follow.created_at.isoformat(),
                    "relationship_sentence": relationship_sentence
                })

        # Generate page title for followers page
        page_title = generate_followers_page_title(
            name=profile_owner.name,
            gender=profile_owner.gender if profile_owner.gender else "person",
            follower_count=total_count
        )

        return {
            "status": "success",
            "user_id": user_id,
            "page_title": page_title,
            "total_count": total_count,
            "count": len(results),
            "limit": limit,
            "offset": offset,
            "has_more": (offset + len(results)) < total_count,
            "followers": results
        }

    except Exception as e:
        logger.error(f"Error fetching followers for {user_id}: {e}")
        return {
            "status": "error",
            "error": str(e)
        }
    finally:
        db.close()

@app.get("/user/{user_id}/following")
async def get_following(user_id: str, limit: int = 5, offset: int = 0):
    """
    Get users that this user follows (who User B is following) with pagination.
    Includes AI-generated relationship sentence for each person they follow.

    Args:
        user_id: The user's ID
        limit: Number of following to return (default 5, max 100)
        offset: Number of following to skip (default 0)

    Returns:
        Paginated list of users they're following with their info and relationship sentences
    """
    db = SessionLocal()
    try:
        # Validate pagination params
        limit = min(limit, 100)  # Max 100 per page
        offset = max(offset, 0)  # No negative offsets

        # Get the profile owner (User B)
        profile_owner = db.query(User).filter(User.id == user_id).first()
        if not profile_owner:
            return {
                "status": "error",
                "message": "User not found"
            }

        # Get total count of following
        total_count = db.query(Follow).filter(
            Follow.follower_id == user_id
        ).count()

        # Get paginated follows where this user is the follower
        follows = db.query(Follow).filter(
            Follow.follower_id == user_id
        ).order_by(Follow.created_at.desc()).limit(limit).offset(offset).all()

        # Get following info with relationship sentences
        results = []
        for follow in follows:
            following = db.query(User).filter(User.id == follow.following_id).first()
            if following:
                # Generate relationship sentence
                relationship_sentence = generate_relationship_sentence(
                    user_a_name=following.name,
                    user_a_bio=following.bio if following.bio else "",
                    user_b_name=profile_owner.name,
                    user_b_bio=profile_owner.bio if profile_owner.bio else ""
                )

                results.append({
                    "user_id": following.id,
                    "username": following.username,
                    "name": following.name,
                    "university": following.university,
                    "occupation": following.occupation,
                    "followed_at": follow.created_at.isoformat(),
                    "relationship_sentence": relationship_sentence
                })

        # Generate page title for following page
        page_title = generate_following_page_title(
            name=profile_owner.name,
            gender=profile_owner.gender if profile_owner.gender else "person",
            following_count=total_count
        )

        return {
            "status": "success",
            "user_id": user_id,
            "page_title": page_title,
            "total_count": total_count,
            "count": len(results),
            "limit": limit,
            "offset": offset,
            "has_more": (offset + len(results)) < total_count,
            "following": results
        }

    except Exception as e:
        logger.error(f"Error fetching following for {user_id}: {e}")
        return {
            "status": "error",
            "error": str(e)
        }
    finally:
        db.close()

@app.get("/user/{user_id}/follower-count")
async def get_follower_count(user_id: str):
    """
    Get the follower and following counts for a user.

    Args:
        user_id: The user's ID

    Returns:
        Follower count and following count
    """
    db = SessionLocal()
    try:
        # Count followers
        follower_count = db.query(Follow).filter(
            Follow.following_id == user_id
        ).count()

        # Count following
        following_count = db.query(Follow).filter(
            Follow.follower_id == user_id
        ).count()

        return {
            "status": "success",
            "user_id": user_id,
            "follower_count": follower_count,
            "following_count": following_count
        }

    except Exception as e:
        logger.error(f"Error fetching counts for {user_id}: {e}")
        return {
            "status": "error",
            "error": str(e)
        }
    finally:
        db.close()

@app.get("/user/{user_id}/follower-sentence")
async def get_follower_sentence(user_id: str):
    """
    Get the cached follower sentence for a user from the database.
    This sentence is automatically updated when:
    - User follows someone (public profile)
    - User's follow request is accepted (private profile)
    - Someone follows this user

    iOS should call this endpoint when loading any user's profile page.

    Args:
        user_id: The user's ID

    Returns:
        Cached follower sentence, follower count, and following count
    """
    db = SessionLocal()
    try:
        # Get user
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            return {
                "status": "error",
                "message": "User not found"
            }

        # Get follower count (people who follow this user)
        follower_count = db.query(Follow).filter(
            Follow.following_id == user_id
        ).count()

        # Get following count (people this user follows)
        following_count = db.query(Follow).filter(
            Follow.follower_id == user_id
        ).count()

        # Get cached sentence from database
        # If no sentence exists yet, generate one
        follower_sentence = user.follower_sentence
        if not follower_sentence:
            follower_sentence = generate_follower_sentence(
                gender=user.gender,
                follower_count=follower_count,
                following_count=following_count
            )
            user.follower_sentence = follower_sentence
            db.commit()
            logger.info(f"✨ Generated initial follower sentence for user {user_id}")

        return {
            "status": "success",
            "user_id": user_id,
            "follower_sentence": follower_sentence,
            "follower_count": follower_count,
            "following_count": following_count
        }

    except Exception as e:
        logger.error(f"Error fetching follower sentence for {user_id}: {e}")
        return {
            "status": "error",
            "error": str(e)
        }
    finally:
        db.close()

@app.delete("/user/{user_id}")
async def delete_account(user_id: str):
    """
    Delete a user's account and all associated data.

    This includes:
    - User profile
    - Follow relationships (followers and following)
    - Follow requests (sent and received)
    - Notifications (received and triggered)
    - Pinecone embeddings

    Args:
        user_id: The user's ID

    Returns:
        Success/error status
    """
    from services.profile_embeddings import index as pinecone_index

    db = SessionLocal()
    try:
        # Check if user exists
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            return {
                "status": "error",
                "message": "User not found"
            }

        logger.info(f"🗑️  Starting account deletion for user {user_id} ({user.username})")

        # 1. Delete from Pinecone
        try:
            pinecone_index.delete(ids=[user_id])
            logger.info(f"✅ Deleted Pinecone embedding for user {user_id}")
        except Exception as e:
            logger.warning(f"⚠️  Could not delete Pinecone embedding: {e}")

        # 2. Delete notifications (received and triggered)
        notifs_received = db.query(Notification).filter(Notification.user_id == user_id).delete()
        notifs_triggered = db.query(Notification).filter(Notification.actor_id == user_id).delete()
        logger.info(f"✅ Deleted {notifs_received} notifications received, {notifs_triggered} notifications triggered")

        # 3. Delete follow requests (sent and received)
        requests_sent = db.query(FollowRequest).filter(FollowRequest.requester_id == user_id).delete()
        requests_received = db.query(FollowRequest).filter(FollowRequest.requested_id == user_id).delete()
        logger.info(f"✅ Deleted {requests_sent} follow requests sent, {requests_received} follow requests received")

        # 4. Delete follow relationships (as follower and following)
        follows_as_follower = db.query(Follow).filter(Follow.follower_id == user_id).delete()
        follows_as_following = db.query(Follow).filter(Follow.following_id == user_id).delete()
        logger.info(f"✅ Deleted {follows_as_follower} follows (as follower), {follows_as_following} follows (as following)")

        # 5. Delete user
        db.delete(user)
        db.commit()

        logger.info(f"✅ Successfully deleted account for user {user_id} ({user.username})")

        return {
            "status": "success",
            "message": "Account deleted successfully",
            "deleted": {
                "notifications_received": notifs_received,
                "notifications_triggered": notifs_triggered,
                "follow_requests_sent": requests_sent,
                "follow_requests_received": requests_received,
                "follows_as_follower": follows_as_follower,
                "follows_as_following": follows_as_following
            }
        }

    except Exception as e:
        logger.error(f"❌ Error deleting account for {user_id}: {e}")
        db.rollback()
        return {
            "status": "error",
            "error": str(e)
        }
    finally:
        db.close()

class BlockRequest(BaseModel):
    blocker_id: str
    blocked_id: str

@app.post("/block/user")
async def block_user(block_data: BlockRequest):
    """
    Block a user. This will:
    - Prevent blocker from seeing blocked user's content
    - Prevent blocked user from seeing blocker's content (mutual hiding)
    - Remove any existing follow relationships
    - Remove any pending follow requests
    - Prevent future follow requests

    Request body:
    {
        "blocker_id": "user_id_doing_the_blocking",
        "blocked_id": "user_id_being_blocked"
    }

    Returns:
        Success/error status
    """
    db = SessionLocal()
    try:
        # Validate both users exist
        blocker = db.query(User).filter(User.id == block_data.blocker_id).first()
        blocked = db.query(User).filter(User.id == block_data.blocked_id).first()

        if not blocker or not blocked:
            return {
                "status": "error",
                "message": "One or both users not found"
            }

        # Can't block yourself
        if block_data.blocker_id == block_data.blocked_id:
            return {
                "status": "error",
                "message": "Cannot block yourself"
            }

        # Check if already blocked
        existing_block = db.query(Block).filter(
            Block.blocker_id == block_data.blocker_id,
            Block.blocked_id == block_data.blocked_id
        ).first()

        if existing_block:
            return {
                "status": "error",
                "message": "User already blocked"
            }

        # 1. Create block
        new_block = Block(
            blocker_id=block_data.blocker_id,
            blocked_id=block_data.blocked_id
        )
        db.add(new_block)

        # 2. Remove follow relationships (both directions)
        db.query(Follow).filter(
            ((Follow.follower_id == block_data.blocker_id) & (Follow.following_id == block_data.blocked_id)) |
            ((Follow.follower_id == block_data.blocked_id) & (Follow.following_id == block_data.blocker_id))
        ).delete(synchronize_session=False)

        # 3. Remove follow requests (both directions)
        db.query(FollowRequest).filter(
            ((FollowRequest.requester_id == block_data.blocker_id) & (FollowRequest.requested_id == block_data.blocked_id)) |
            ((FollowRequest.requester_id == block_data.blocked_id) & (FollowRequest.requested_id == block_data.blocker_id))
        ).delete(synchronize_session=False)

        db.commit()
        db.refresh(new_block)

        logger.info(f"🚫 User {block_data.blocker_id} blocked user {block_data.blocked_id}")

        return {
            "status": "success",
            "message": "User blocked successfully",
            "block_id": new_block.id
        }

    except Exception as e:
        logger.error(f"❌ Error blocking user: {e}")
        db.rollback()
        return {
            "status": "error",
            "error": str(e)
        }
    finally:
        db.close()

@app.get("/profile/{viewer_id}/{profile_id}")
async def get_profile(viewer_id: str, profile_id: str):
    """
    Get a user's profile with follow status and design (if following).

    Returns one of three states:
    1. not_following - Show private/locked profile
    2. pending - Follow request sent, waiting for acceptance
    3. following - Show full profile with latest design

    Args:
        viewer_id: The user viewing the profile (current user)
        profile_id: The profile being viewed

    Returns:
        Profile data with follow status and design (if applicable)
    """
    db = SessionLocal()
    try:
        # Get the profile user
        profile_user = db.query(User).filter(User.id == profile_id).first()

        if not profile_user:
            return {
                "status": "error",
                "message": "User not found"
            }

        # Check if viewing own profile
        if viewer_id == profile_id:
            # Return own profile
            return {
                "status": "success",
                "follow_status": "own_profile",
                "user": {
                    "id": profile_user.id,
                    "username": profile_user.username,
                    "name": profile_user.name,
                    "university": profile_user.university,
                    "occupation": profile_user.occupation
                }
            }

        # Check if profile is PUBLIC
        if not profile_user.is_private:
            # Public profile - show full profile regardless of follow status
            # Check if following to determine follow_status
            follow = db.query(Follow).filter(
                Follow.follower_id == viewer_id,
                Follow.following_id == profile_id
            ).first()

            return {
                "status": "success",
                "follow_status": "following" if follow else "not_following",
                "is_public": True,
                "user": {
                    "id": profile_user.id,
                    "username": profile_user.username,
                    "name": profile_user.name,
                    "university": profile_user.university,
                    "occupation": profile_user.occupation
                }
            }

        # Profile is PRIVATE - check follow/request status
        # Check if viewer follows this profile
        follow = db.query(Follow).filter(
            Follow.follower_id == viewer_id,
            Follow.following_id == profile_id
        ).first()

        # Check if there's a pending follow request
        pending_request = db.query(FollowRequest).filter(
            FollowRequest.requester_id == viewer_id,
            FollowRequest.requested_id == profile_id
        ).first()

        # Determine follow status
        if follow:
            # Viewer follows this profile - show full profile
            return {
                "status": "success",
                "follow_status": "following",
                "is_public": False,
                "user": {
                    "id": profile_user.id,
                    "username": profile_user.username,
                    "name": profile_user.name,
                    "university": profile_user.university,
                    "occupation": profile_user.occupation
                }
            }

        elif pending_request:
            # Request pending - show limited info
            return {
                "status": "success",
                "follow_status": "pending",
                "is_public": False,
                "user": {
                    "id": profile_user.id,
                    "username": profile_user.username,
                    "name": profile_user.name,
                    "university": profile_user.university,
                    "occupation": profile_user.occupation
                },
                "message": "Follow request pending"
            }

        else:
            # Not following - show private profile
            return {
                "status": "success",
                "follow_status": "not_following",
                "is_public": False,
                "user": {
                    "id": profile_user.id,
                    "username": profile_user.username,
                    "name": profile_user.name,
                    "university": profile_user.university,
                    "occupation": profile_user.occupation
                },
                "message": "This profile is private"
            }

    except Exception as e:
        logger.error(f"Error fetching profile: {e}")
        return {
            "status": "error",
            "error": str(e)
        }
    finally:
        db.close()

@app.post("/profile/{user_id}/privacy")
async def toggle_privacy(user_id: str, is_private: bool):
    """
    Toggle a user's profile privacy setting.

    Args:
        user_id: The user's ID
        is_private: True for private profile, False for public profile

    Request body:
    {
        "is_private": true or false
    }

    Returns:
        Success message with updated privacy status
    """
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()

        if not user:
            return {
                "status": "error",
                "message": "User not found"
            }

        user.is_private = is_private
        db.commit()

        logger.info(f"✅ User {user_id} profile privacy set to {'private' if is_private else 'public'}")

        return {
            "status": "success",
            "message": f"Profile is now {'private' if is_private else 'public'}",
            "is_private": is_private
        }

    except Exception as e:
        db.rollback()
        logger.error(f"Error updating privacy setting: {e}")
        return {
            "status": "error",
            "message": str(e)
        }
    finally:
        db.close()

@app.get("/notifications/{user_id}")
async def get_notifications(user_id: str):
    """
    Get notifications for a user: follow requests and follow accepts ONLY.

    NO eras/status updates - only actionable notifications.

    Args:
        user_id: User's ID

    Returns:
        List of follow request and follow accept notifications, sorted oldest to newest
    """
    db = SessionLocal()
    try:
        # Get user's own notifications (follow requests and accepts ONLY)
        feed_items = []
        user_notifications = db.query(Notification).filter(
            Notification.user_id == user_id
        ).order_by(Notification.created_at.asc()).all()

        for notif in user_notifications:
            # Determine notification type based on content
            if "wants to follow you" in notif.content:
                notif_type = "follow_request"
            elif "accepted your follow request" in notif.content:
                notif_type = "follow_accept"
            elif "started following you" in notif.content:
                notif_type = "new_follower"
            elif "posted" in notif.content:
                notif_type = "new_post"
            else:
                # Skip anything that's not a recognized notification type
                continue

            # Build notification item - always include base fields
            notification_item = {
                "id": notif.id,
                "type": notif_type,
                "user_id": notif.user_id,
                "content": notif.content,
                "created_at": notif.created_at.isoformat()
            }

            # ALWAYS get and add actor details if actor_id exists
            if notif.actor_id:
                actor = db.query(User).filter(User.id == notif.actor_id).first()
                if actor:
                    # Add actor fields directly to notification_item
                    notification_item["actor_id"] = actor.id
                    notification_item["actor_username"] = actor.username
                    notification_item["actor_name"] = actor.name
                    notification_item["actor_profile_image"] = actor.profile_image
                    logger.info(f"✅ Added actor info for notification {notif.id}: {actor.username}")
                else:
                    logger.warning(f"⚠️  Actor not found for actor_id: {notif.actor_id}")
            else:
                logger.warning(f"⚠️  Notification {notif.id} has no actor_id in database")

            feed_items.append(notification_item)

        # Sort all items by created_at (oldest to newest - bottom is newest)
        feed_items.sort(key=lambda x: x["created_at"])

        return {
            "status": "success",
            "user_id": user_id,
            "count": len(feed_items),
            "notifications": feed_items  # Changed from "feed" to "notifications"
        }

    except Exception as e:
        logger.error(f"Error fetching feed for {user_id}: {e}")
        return {
            "status": "error",
            "error": str(e)
        }
    finally:
        db.close()


@app.get("/caption/stream")
async def caption_generation_stream(q: str = Query(""), session_id: str = Query(...)):
    """
    SSE streaming endpoint for AI-assisted caption generation.

    Query params:
    - q: user message
    - session_id: unique session identifier (required)

    The AI will chat with the user to understand what they want to post,
    then generate 2 captions and a
     location. When ready, sends conversation_complete event.
    """
    async def event_gen():
        import json
        from utils.redis_client import r
        from anthropic import Anthropic

        # Get or initialize caption session in Redis
        redis_key = f"caption_session:{session_id}"
        session_data_str = r.get(redis_key)

        if session_data_str:
            session_data = json.loads(session_data_str)
        else:
            # Initialize new caption session
            session_data = {
                "messages": [],
                "caption_data": {}
            }

        # Add user message to conversation history
        if q:
            session_data["messages"].append({"role": "user", "content": q})

        # Build conversation for Anthropic
        conversation_messages = session_data["messages"].copy()

        # System prompt
        system_prompt = """You are a creative assistant helping users craft the perfect social media post.

Your job:
1. Chat with the user to understand what they want to post about
2. Ask follow-up questions if needed to get the vibe/theme
3. When you have enough info, generate 2 caption options and a location
4. Detect when the user is ready to post

Conversation style:
- Be casual, friendly, lowercase gen-z vibes
- Ask clarifying questions if needed (e.g., "ooh what's the vibe? girlboss? cozy? party mode?")
- Keep responses short (1-2 sentences)
- Match their energy and vibe

When the user says they're ready or you have enough info:
1. Say: "ok on it! ready to post! 🎨"
2. Then immediately generate the content

To generate content, respond with EXACTLY this JSON format (no other text):
{
  "READY_TO_POST": true,
  "caption1": "first caption option here with emojis",
  "caption2": "second caption option here with emojis",
  "location": "location name or empty string if not applicable"
}

Caption requirements:
- 15-30 words each
- Lowercase, casual, gen-z style
- Include emojis
- Match the vibe/theme the user described (girlboss, cozy, party, etc.)

Examples of when to generate:
- User: "i went to the beach today, sunset vibes" → generate beach sunset captions
- User: "yeah i'm ready to post!" → generate with info you collected
- User: "girlboss energy post about my new job" → generate empowering career captions"""

        try:
            # Call Anthropic API
            client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

            # Build messages for Claude
            messages_for_claude = []
            for msg in conversation_messages:
                messages_for_claude.append({
                    "role": msg["role"],
                    "content": msg["content"]
                })

            response = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=500,
                system=system_prompt,
                messages=messages_for_claude,
                stream=True
            )

            assistant_response = ""
            ready_to_post = False

            # Stream the response
            for chunk in response:
                if chunk.type == "content_block_delta":
                    if hasattr(chunk.delta, "text"):
                        text = chunk.delta.text
                        assistant_response += text

                        # Stream token to frontend
                        yield f"event: token\ndata: {json.dumps({'content': text})}\n\n"

            # Save assistant response to conversation history
            session_data["messages"].append({
                "role": "assistant",
                "content": assistant_response
            })

            # Check if response contains the READY_TO_POST JSON
            if "READY_TO_POST" in assistant_response:
                try:
                    # Extract JSON from response
                    json_start = assistant_response.find("{")
                    json_end = assistant_response.rfind("}") + 1
                    json_str = assistant_response[json_start:json_end]

                    caption_data = json.loads(json_str)

                    if caption_data.get("READY_TO_POST"):
                        # Store generated content in Redis
                        session_data["caption_data"] = {
                            "caption1": caption_data.get("caption1", ""),
                            "caption2": caption_data.get("caption2", ""),
                            "location": caption_data.get("location", "")
                        }

                        ready_to_post = True
                        logger.info(f"✅ Generated captions for session {session_id}")

                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse caption JSON: {e}")

            # Save session back to Redis
            r.set(redis_key, json.dumps(session_data))

            # If ready to post, send conversation_complete event
            if ready_to_post:
                logger.info(f"✅ Sending conversation_complete to iOS for session {session_id}")
                yield f"event: conversation_complete\ndata: {json.dumps({'session_id': session_id})}\n\n"

        except Exception as e:
            logger.error(f"Error in caption generation: {e}")
            yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"

        yield "event: done\ndata: {}\n\n"

    headers = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    return StreamingResponse(event_gen(), media_type="text/event-stream", headers=headers)


@app.get("/caption/poll/{session_id}")
async def poll_caption_data(session_id: str):
    """
    Poll endpoint for iOS to retrieve generated caption data.

    Returns:
    {
        "status": "ready",
        "caption1": "first caption...",
        "caption2": "second caption...",
        "location": "beach"
    }
    """
    try:
        redis_key = f"caption_session:{session_id}"
        session_data_str = r.get(redis_key)

        if not session_data_str:
            return {"status": "not_found", "message": "Session not found"}

        session_data = json.loads(session_data_str)
        caption_data = session_data.get("caption_data", {})

        if caption_data and caption_data.get("caption1"):
            return {
                "status": "ready",
                "caption1": caption_data.get("caption1", ""),
                "caption2": caption_data.get("caption2", ""),
                "location": caption_data.get("location", ""),
                "session_id": session_id
            }
        else:
            return {
                "status": "processing",
                "message": "Captions not ready yet"
            }

    except Exception as e:
        logger.error(f"Error polling caption data: {e}")
        return {"status": "error", "error": str(e)}


# ==========================================
# Fashion endpoints removed - all CV processing now handled by separate CV service


# ==========================================
# Outfit Feed Endpoints for iOS
# ==========================================

from api.outfit_endpoints import get_outfit_by_id, get_all_outfits, get_next_outfit


@app.get("/outfits/all")
async def get_all_outfits_endpoint():
    """
    Get list of all outfits

    iOS calls this on app open to get all outfit IDs
    Then manages scroll position locally
    """
    return await get_all_outfits()


@app.get("/outfits/next")
async def get_next_outfit_endpoint(
    user_id: str,
    count: int = 10,
    background_tasks: BackgroundTasks = None
):
    """
    Get the next N outfits for this user (Instagram-style batch)

    Returns multiple outfits at once for smooth infinite scrolling.
    iOS can cache them and display instantly as user swipes.

    Query params:
        user_id: User ID from auth token
        count: Number of outfits to return (default 10)

    Returns:
        List of outfits: [
            {
                "outfit_id": "uuid",
                "title": "1999 celeb caught by paparazzi, $99",
                "image_url": "https://...",
                "gender": "women",
                "products": [...]
            },
            ...
        ]

    Example:
        GET /outfits/next?user_id=123&count=10
        → Returns 10 outfits

        GET /outfits/next?user_id=123&count=1
        → Returns 1 outfit (backward compatible)
    """
    return await get_next_outfit(user_id, count, background_tasks)


@app.get("/outfits/{outfit_id}")
async def get_outfit_endpoint(outfit_id: str, background_tasks: BackgroundTasks):
    """
    Get specific outfit by ID

    iOS calls this when user views an outfit

    Backend:
    1. Returns outfit with products
    2. Calculates total price using LLM
    3. Prefetches next 3 outfits in background

    Returns title with price: "1999 celeb caught by paparazzi, $99"
    """
    return await get_outfit_by_id(outfit_id, background_tasks)


class TryOnSignupRequest(BaseModel):
    user_id: str


@app.post("/outfits/tryon/signup")
async def outfit_tryon_signup(request: TryOnSignupRequest):
    """
    Sign up user for outfit try-on feature

    Takes user_id, gets their email, and adds to signup list
    """
    db = SessionLocal()
    try:
        # Get user by ID
        user = db.query(User).filter(User.id == request.user_id).first()

        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        # Check if already signed up
        existing = db.query(OutfitTryOnSignup).filter(
            OutfitTryOnSignup.user_id == request.user_id
        ).first()

        if existing:
            return {
                "success": True,
                "message": "Already signed up",
                "already_signed_up": True
            }

        # Create signup entry
        signup = OutfitTryOnSignup(
            user_id=request.user_id,
            email=user.email
        )
        db.add(signup)
        db.commit()

        logger.info(f"✅ User {user.email} signed up for outfit try-on")

        return {
            "success": True,
            "message": "Successfully signed up for outfit try-on",
            "already_signed_up": False
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Error signing up user for try-on: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


class SaveOutfitRequest(BaseModel):
    user_id: str
    outfit_id: str


def generate_outfit_caption(user: User, outfit: Outfit, outfit_count: int) -> str:
    """
    Generate personalized caption for user's outfit using LLM

    Args:
        user: User object with profile data
        outfit: Outfit object
        outfit_count: How many outfits user has saved (for variety)

    Returns:
        Personalized caption string
    """
    from anthropic import Anthropic
    import os

    # Build user context
    user_context = f"Name: {user.name or 'user'}"
    if user.gender:
        user_context += f", Gender: {user.gender}"
    if user.occupation:
        user_context += f", Occupation: {user.occupation}"
    if user.university:
        user_context += f", University: {user.university}"
    if user.college_major:
        user_context += f", Major: {user.college_major}"
    if user.city:
        user_context += f", City: {user.city}"
    if user.ethnicity:
        user_context += f", Ethnicity: {user.ethnicity}"

    # Themes to vary captions (cycle through them)
    themes = [
        "walking into class/campus",
        "going out with friends",
        "running errands around the city",
        "date night",
        "job interview or internship",
        "coffee shop studying",
        "late night adventure",
        "brunch on the weekend",
        "networking event",
        "casual day at work"
    ]
    theme = themes[outfit_count % len(themes)]

    prompt = f"""Generate a caption (7-10 words max) for this outfit that a user saved: name the moment. 
    Think like a vogue editorialist. You are coming up with a short caption to name the moment based on the outfit and the context you know about this person. 

timestamped snapshot:
“her fit at 7:18am, philz in hand, code still compiling.”

third-person observation (editorial)
“this is what a successful woman female startup founder wears.” (if the person is a female, and is a startup founder)

"the fit she pulls off when she's about to close a big deal."

"her sf marina girls night fit" 

make sure to not always output the same starter of the caption. 

notice how it is
1) clear + literal (not vague / poetry)
2) ✅ names the moment
3) ✅ ties to who you are (female, startup founder, big deal energy)


User info: {user_context}
Outfit vibe: {outfit.base_title}
Theme for this caption: {theme}

keep the text lowercase.

Return ONLY the caption, no quotes or extra text."""

    try:
        anthropic_client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        response = anthropic_client.messages.create(
            model="claude-3-haiku-20240307",
            max_tokens=50,
            messages=[{"role": "user", "content": prompt}]
        )

        caption = response.content[0].text.strip()
        return caption

    except Exception as e:
        logger.error(f"Error generating caption: {e}")
        # Fallback caption
        pronoun = "she" if user.gender == "women" else "he"
        return f"the fit {pronoun} wears to feel unstoppable"


@app.post("/outfits/save")
async def save_outfit(request: SaveOutfitRequest):
    """
    Save/buy an outfit for a user

    When user clicks "buy this fit", iOS sends this request
    Generates a personalized AI caption for the outfit
    """
    db = SessionLocal()
    try:
        # Check if user exists
        user = db.query(User).filter(User.id == request.user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        # Check if outfit exists
        outfit = db.query(Outfit).filter(Outfit.id == request.outfit_id).first()
        if not outfit:
            raise HTTPException(status_code=404, detail="Outfit not found")

        # Check if already saved
        existing = db.query(UserOutfit).filter(
            UserOutfit.user_id == request.user_id,
            UserOutfit.outfit_id == request.outfit_id
        ).first()

        if existing:
            return {
                "success": True,
                "message": "Outfit already saved",
                "already_saved": True,
                "saved_at": existing.saved_at.isoformat(),
                "caption": existing.caption
            }

        # Count user's existing outfits (for caption variety)
        outfit_count = db.query(UserOutfit).filter(
            UserOutfit.user_id == request.user_id
        ).count()

        # Generate personalized caption
        caption = generate_outfit_caption(user, outfit, outfit_count)

        # Save outfit with caption
        user_outfit = UserOutfit(
            user_id=request.user_id,
            outfit_id=request.outfit_id,
            caption=caption
        )
        db.add(user_outfit)
        db.commit()

        logger.info(f"✅ User {request.user_id} saved outfit {request.outfit_id}")
        logger.info(f"   Caption: {caption}")

        return {
            "success": True,
            "message": "Outfit saved successfully",
            "already_saved": False,
            "saved_at": user_outfit.saved_at.isoformat(),
            "caption": caption
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Error saving outfit: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


@app.post("/outfits/tryon")
async def try_on_outfit():
    """
    Virtual try-on using Google Gemini Nano Banana Pro

    Hardcoded images for now:
    - Person image: woman's photo
    - Outfit image: silver crystal dress

    Returns generated image where person is wearing the outfit
    """
    import base64

    try:
        from google import genai
        from google.genai import types

        # Initialize Gemini client
        google_api_key = os.getenv("GOOGLE_API_KEY")
        if not google_api_key:
            raise HTTPException(status_code=500, detail="GOOGLE_API_KEY not configured")

        client = genai.Client(api_key=google_api_key)

        PRO_MODEL_ID = "gemini-3-pro-image-preview"

        # Hardcoded image URLs for testing
        person_image_url = "https://firebasestorage.googleapis.com/v0/b/glow-55f19.firebasestorage.app/o/Screenshot%202026-01-31%20at%203.46.27%E2%80%AFPM.png?alt=media&token=bdfd0e55-1d86-416d-bf35-a7f8d8966d94"
        outfit_image_url = "https://firebasestorage.googleapis.com/v0/b/glow-55f19.firebasestorage.app/o/IMG_7284.jpg?alt=media&token=7710dfab-bb94-461e-b864-11eb83d63080"

        # Download images
        person_response = requests.get(person_image_url, timeout=10)
        outfit_response = requests.get(outfit_image_url, timeout=10)

        person_image_data = base64.b64encode(person_response.content).decode('utf-8')
        outfit_image_data = base64.b64encode(outfit_response.content).decode('utf-8')

        # Create the prompt with both images
        prompt = """make the person in image 1 try on the clothes of the person in image 2. it must be the exact outfit shown in Image 2. the woman in image 1 should be wearing the same outfit. Keep the woman's face, facial features, expression, skin tone, hairstyle, and identity from Image 1 completely unchanged—do not alter her face in any way.

IMPORTANT: Adhere strictly to the body mass index and skeletal proportions of the person in Image 1. Do not lengthen limbs or alter the torso-to-leg ratio. The fabric must drape according to the specific curves and physical frame shown in the reference image. Ensure realistic lighting, natural shadows, accurate body proportions, and seamless fabric fitting.

Image quality: make sure the image quality looks like it's being taken by a digital camera. """

        logger.info(f"🎨 Generating virtual try-on with Gemini...")

        # Generate the image with both input images
        response = client.models.generate_content(
            model=PRO_MODEL_ID,
            contents=[
                types.Content(
                    parts=[
                        types.Part(text=prompt),
                        types.Part(
                            inline_data=types.Blob(
                                mime_type="image/jpeg",
                                data=base64.b64decode(person_image_data)
                            )
                        ),
                        types.Part(
                            inline_data=types.Blob(
                                mime_type="image/jpeg",
                                data=base64.b64decode(outfit_image_data)
                            )
                        )
                    ]
                )
            ],
            config=types.GenerateContentConfig(
                response_modalities=['IMAGE'],
                image_config=types.ImageConfig(
                    aspect_ratio="9:16"  # Portrait mode for full body outfit
                )
            )
        )

        # Extract generated image
        for part in response.parts:
            if part.inline_data:
                generated_image_data = base64.b64encode(part.inline_data.data).decode('utf-8')

                logger.info(f"✅ Virtual try-on generated successfully")

                return {
                    "success": True,
                    "generated_image": f"data:image/png;base64,{generated_image_data}",
                    "message": "Virtual try-on completed"
                }

        # If no image was generated
        raise HTTPException(status_code=500, detail="No image generated")

    except Exception as e:
        logger.error(f"❌ Error in virtual try-on: {e}")
        raise HTTPException(status_code=500, detail=f"Virtual try-on failed: {str(e)}")


@app.get("/users/{user_id}/outfits")
async def get_user_outfits(user_id: str):
    """
    Get all outfits saved by a user (their wardrobe)

    Use this to show:
    - User's own profile: their saved fits
    - Other user's profile: their saved fits
    """
    db = SessionLocal()
    try:
        # Check if user exists
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        # Get user's saved outfits
        user_outfits = db.query(UserOutfit, Outfit).join(
            Outfit, UserOutfit.outfit_id == Outfit.id
        ).filter(
            UserOutfit.user_id == user_id
        ).order_by(
            UserOutfit.saved_at.desc()
        ).all()

        # Get user's brands
        user_brand_relationships = db.query(UserBrand, Brand).join(
            Brand, UserBrand.brand_id == Brand.id
        ).filter(
            UserBrand.user_id == user_id
        ).all()
        brands_list = [brand.name for _, brand in user_brand_relationships]

        # Build response
        outfits = []
        for user_outfit, outfit in user_outfits:
            # Get products for this outfit
            products = db.query(OutfitProduct).filter(
                OutfitProduct.outfit_id == outfit.id
            ).order_by(OutfitProduct.rank).all()

            # Calculate total price
            from api.outfit_endpoints import calculate_total_price_with_llm
            total_price = calculate_total_price_with_llm(products) if products else "$0"

            outfits.append({
                "outfit_id": outfit.id,
                "title": f"{outfit.base_title}, {total_price}",
                "caption": user_outfit.caption,  # Stored caption (not regenerated)
                "image_url": outfit.image_url,
                "gender": outfit.gender,
                "saved_at": user_outfit.saved_at.isoformat(),
                "products": [
                    {
                        "name": p.product_name,
                        "brand": p.brand,
                        "retailer": p.retailer,
                        "price": p.price_display,
                        "image_url": p.product_image_url,
                        "product_url": p.product_url,
                        "rank": int(p.rank)
                    }
                    for p in products
                ]
            })

        logger.info(f"📦 Retrieved {len(outfits)} saved outfits for user {user_id}")

        return {
            "user_id": user_id,
            "username": user.username,
            "total_outfits": len(outfits),
            "brands": brands_list,  # User's brands from database
            "outfits": outfits
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error getting user outfits: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


@app.post("/users/{user_id}/regenerate-profile")
async def regenerate_user_profile(user_id: str):
    """
    Regenerate both outfit captions AND brands for a user
    Uses generate_outfit_caption() and Claude to pick brands
    """
    db = SessionLocal()
    try:
        # Check if user exists
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        # ===== REGENERATE BRANDS =====
        # Get all available brands from database
        all_brands = db.query(Brand).all()
        if not all_brands:
            raise HTTPException(status_code=400, detail="No brands available in database. Run seed_brands.py first.")

        # Build user context
        user_context = f"Name: {user.name or 'user'}"
        if user.gender:
            user_context += f", Gender: {user.gender}"
        if user.occupation:
            user_context += f", Occupation: {user.occupation}"
        if user.university:
            user_context += f", University: {user.university}"
        if user.college_major:
            user_context += f", Major: {user.college_major}"
        if user.city:
            user_context += f", City: {user.city}"
        if user.ethnicity:
            user_context += f", Ethnicity: {user.ethnicity}"
        if user.sexuality:
            user_context += f", Sexuality: {user.sexuality}"
        if user.bio:
            user_context += f", Bio: {user.bio}"

        # Format brands for prompt
        brands_options = []
        for brand in all_brands:
            tags = ", ".join(brand.style_tags) if brand.style_tags else "N/A"
            brands_options.append(f"{brand.name} ({brand.price_range}, {tags})")

        brands_list_text = "\n".join(brands_options)

        # Prompt Claude to recommend brands
        from anthropic import Anthropic
        import os

        prompt = f"""Based on this user's profile, recommend 3-4 fashion brands that match their vibe and personality.

User profile: {user_context}

Available brands to choose from:
{brands_list_text}

Consider their lifestyle, location, occupation, and personal style. Mix different price ranges if appropriate.

Return ONLY a comma-separated list of brand names (exact names from the list above), nothing else.

Examples:
- PRADA, Dolce & Gabbana, Miu Miu
- Zara, Reformation, Aritzia, H&M
- Rick Owens, Acne Studios, Bottega Veneta
"""

        anthropic_client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        response = anthropic_client.messages.create(
            model="claude-3-haiku-20240307",
            max_tokens=100,
            messages=[{"role": "user", "content": prompt}]
        )

        brands_text = response.content[0].text.strip()
        brands_list = [b.strip() for b in brands_text.split(',')][:4]

        # Clear existing user brands
        db.query(UserBrand).filter(UserBrand.user_id == user_id).delete()
        db.commit()

        # Get or create each brand and link to user
        brand_objects = []
        for brand_name in brands_list:
            brand = db.query(Brand).filter(Brand.name == brand_name).first()
            if not brand:
                brand = Brand(name=brand_name)
                db.add(brand)
                db.flush()

            user_brand = UserBrand(user_id=user_id, brand_id=brand.id)
            db.add(user_brand)
            brand_objects.append(brand_name)

        db.commit()

        # ===== REGENERATE CAPTIONS =====
        user_outfits = db.query(UserOutfit, Outfit).join(
            Outfit, UserOutfit.outfit_id == Outfit.id
        ).filter(
            UserOutfit.user_id == user_id
        ).order_by(
            UserOutfit.saved_at.desc()
        ).all()

        regenerated_captions = []
        for idx, (user_outfit, outfit) in enumerate(user_outfits):
            new_caption = generate_outfit_caption(user, outfit, idx)
            user_outfit.caption = new_caption
            regenerated_captions.append({
                "outfit_id": outfit.id,
                "title": outfit.base_title,
                "new_caption": new_caption
            })

        db.commit()

        logger.info(f"♻️  Regenerated brands and {len(regenerated_captions)} captions for user {user_id}")

        return {
            "user_id": user_id,
            "message": "Successfully regenerated brands and outfit captions",
            "brands": brand_objects,
            "regenerated_captions_count": len(regenerated_captions),
            "captions": regenerated_captions
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error regenerating profile: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("stream:app", host="0.0.0.0", port=8000, reload=True)

