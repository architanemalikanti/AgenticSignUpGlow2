from dotenv import load_dotenv
import os, asyncio, json, logging, uuid
from pathlib import Path
from langchain_core.messages import HumanMessage
from langchain_anthropic import ChatAnthropic
from langchain_openai import ChatOpenAI
from langchain_community.tools.tavily_search import TavilySearchResults
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from fastapi import FastAPI, Query, BackgroundTasks
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List, Optional
from database.db import SessionLocal
from database.models import User, Design, Follow, FollowRequest, Notification, Like, Post, Report, Block, Comment
from agent import Agent
from prompt_manager import set_prompt
from redis_client import r
from aioapns import APNs, NotificationRequest

# Load .env from the same directory as this script
load_dotenv(Path(__file__).parent / ".env")

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s:     %(message)s'
)
logger = logging.getLogger(__name__)

# Get absolute path to conversations database
DB_PATH = str(Path(__file__).parent / "conversations.db")

# --- Tools ---
from tools import (
    create_redis_session,
    set_username,
    set_password,
    confirm_password,
    get_email,
    get_user_birthday,
    get_user_gender,
    get_user_sexuality,
    get_user_ethnicity,
    get_user_pronouns,
    get_user_first_name,
    get_user_university,
    get_user_occupation,
    get_user_college_major,
    generate_verification_code,
    resend_verification_code,
    log_in_user,
    # Login tools
    switch_to_login_mode,
    get_login_username,
    get_login_password,
    verify_login_credentials,
    finalize_login
)
# Use the finalize_user version for background tasks
from finalize_user import test_verification_code

tool = TavilySearchResults(max_results=2)

# Collect all tools
all_tools = [
    tool,
    create_redis_session,
    set_username,
    set_password,
    confirm_password,
    get_email,
    get_user_birthday,
    get_user_gender,
    get_user_sexuality,
    get_user_ethnicity,
    get_user_pronouns,
    get_user_first_name,
    get_user_university,
    get_user_occupation,
    get_user_college_major,
    generate_verification_code,
    resend_verification_code,
    test_verification_code,  # From finalize_user - returns "verified"/"incorrect"
    log_in_user,
    # Login tools
    switch_to_login_mode,
    get_login_username,
    get_login_password,
    verify_login_credentials,
    finalize_login
]

# --- Model ---
# Debug: Check if API keys are loaded
anthropic_key = os.getenv("ANTHROPIC_API_KEY")
openai_key = os.getenv("OPENAI_API_KEY")

if anthropic_key:
    print(f"✅ ANTHROPIC_API_KEY loaded: {anthropic_key[:20]}...")
else:
    print("❌ WARNING: ANTHROPIC_API_KEY not found in environment!")

if openai_key:
    print(f"✅ OPENAI_API_KEY loaded: {openai_key[:20]}...")
else:
    print("⚠️  OPENAI_API_KEY not found - no fallback available")

# Primary model: Claude
model = ChatAnthropic(model="claude-sonnet-4-20250514")

# Fallback model: GPT-4o (only if OpenAI key exists)
fallback_model = ChatOpenAI(model="gpt-4o", temperature=1) if openai_key else None

# Global flag to track if we should use OpenAI as primary
use_openai_primary = False


# # --- Instantiate agent (sync) ---
# with SqliteSaver.from_conn_string(":memory:") as memory:
#     abot = Agent(model, [tool], system=prompt, checkpointer=memory)

#     messages = [HumanMessage(content="What's the weather in San Francisco?")]
#     thread = {"configurable": {"thread_id": "sync-1"}}

#     for event in abot.graph.stream({"messages": messages}, thread):
#         for v in event.values(): 
#             print(v["messages"])

# --- FastAPI app + SSE streaming endpoint ---
app = FastAPI()


apns = APNs(
      key='/home/ec2-user/keys/AuthKey_2JXWNB9AAR.p8',
      key_id='2JXWNB9AAR',  # This is from your filename
      team_id='FRR7RJ635S',  # Get this from Apple Developer Portal → Membership
      topic='com.test.GlowProject',  # Your bundle identifier from Xcode
      use_sandbox=True
  )

@app.get("/chat/stream") 
async def chat_stream(q: str = Query(""), session_id: str = Query(...)):
    """
    SSE streaming endpoint for chat. 
    Query params:
    - q: user message
    - session_id: unique session identifier (required)
    """
    async def event_gen():
        import threading
        import time
        from finalize_user import finalize_user_background
        
        # Generate dynamic prompt based on current Redis state
        dynamic_prompt = set_prompt(session_id)
        
        messages = [HumanMessage(content=q)]
        thread = {"configurable": {"thread_id": session_id}}
        
        verification_succeeded = False
        login_succeeded = False
        background_task_started = False

        async with AsyncSqliteSaver.from_conn_string(DB_PATH) as async_memory:
            # Use OpenAI if global flag is set, otherwise use Anthropic
            global use_openai_primary
            primary_model = fallback_model if (use_openai_primary and fallback_model) else model

            try:
                async_abot = Agent(primary_model, all_tools, system=dynamic_prompt, checkpointer=async_memory, fallback_model=fallback_model)
                async for ev in async_abot.graph.astream_events({"messages": messages}, thread, version="v1"):
                    # Check if verification tool was called and succeeded
                    if ev["event"] == "on_tool_end":
                        tool_name = ev.get("name", "")
                        tool_output = ev.get("data", {}).get("output", "")

                        # Signup verification
                        if tool_name == "test_verification_code" and tool_output == "verified":
                            verification_succeeded = True
                            # Start background task immediately
                            if not background_task_started:
                                threading.Thread(
                                    target=finalize_user_background,
                                    args=(session_id,),
                                    daemon=True
                                ).start()
                                background_task_started = True
                                logger.info(f"🚀 Started background finalization for {session_id}")

                        # Login verification
                        if tool_name == "finalize_login" and tool_output == "verified":
                            login_succeeded = True
                            logger.info(f"🚀 Login completed for {session_id}")

                    # Stream LLM tokens
                    if ev["event"] == "on_chat_model_stream":
                        content = ev["data"]["chunk"].content
                        if content:
                            yield f"event: token\ndata: {json.dumps({'content': content})}\n\n"

            except Exception as e:
                # Check if Anthropic is overloaded
                error_str = str(e)
                is_overload = "overloaded_error" in error_str or "Overloaded" in error_str or "529" in error_str

                if is_overload and fallback_model and not use_openai_primary:
                    logger.info(f"⚠️ Anthropic overloaded! Switching to OpenAI for future requests...")
                    # Set global flag to use OpenAI going forward
                    use_openai_primary = True
                    # Retry THIS request with OpenAI
                    async_abot = Agent(fallback_model, all_tools, system=dynamic_prompt, checkpointer=async_memory, fallback_model=None)
                    async for ev in async_abot.graph.astream_events({"messages": messages}, thread, version="v1"):
                        # Check if verification tool was called and succeeded
                        if ev["event"] == "on_tool_end":
                            tool_name = ev.get("name", "")
                            tool_output = ev.get("data", {}).get("output", "")

                            # Signup verification
                            if tool_name == "test_verification_code" and tool_output == "verified":
                                verification_succeeded = True
                                # Start background task immediately
                                if not background_task_started:
                                    threading.Thread(
                                        target=finalize_user_background,
                                        args=(session_id,),
                                        daemon=True
                                    ).start()
                                    background_task_started = True
                                    logger.info(f"🚀 Started background finalization for {session_id}")

                            # Login verification
                            if tool_name == "finalize_login" and tool_output == "verified":
                                login_succeeded = True
                                logger.info(f"🚀 Login completed for {session_id}")

                        # Stream LLM tokens
                        if ev["event"] == "on_chat_model_stream":
                            content = ev["data"]["chunk"].content
                            if content:
                                yield f"event: token\ndata: {json.dumps({'content': content})}\n\n"
                else:
                    # Not an overload or already using OpenAI, re-raise
                    raise

        # If verification succeeded, send onboarding_complete immediately
        if verification_succeeded:
            logger.info(f"✅ Sending onboarding_complete to iOS for session {session_id}")
            # Send onboarding complete signal with session_id
            # iOS will poll Redis for user_id using this session_id
            yield f"event: onboarding_complete\ndata: {json.dumps({'session_id': session_id})}\n\n"
            logger.info(f"✅ Sent onboarding_complete with session_id to iOS")

        # If login succeeded, send onboarding_complete (same event as signup)
        if login_succeeded:
            logger.info(f"✅ Sending onboarding_complete to iOS for session {session_id}")
            yield f"event: onboarding_complete\ndata: {json.dumps({'session_id': session_id})}\n\n"
            logger.info(f"✅ Sent onboarding_complete with session_id to iOS")

        yield "event: done\ndata: {}\n\n"

    headers = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    return StreamingResponse(event_gen(), media_type="text/event-stream", headers=headers)



@app.get("/createRedisKey")
async def create_redis_key():
    """Generate a new unique session_id."""
    import uuid
    session_id = str(uuid.uuid4())
    return {"session_id": session_id}

@app.get("/simple/stream")
async def simple_onboarding_stream(q: str = Query(""), session_id: str = Query(...)):
    """
    Simple SSE streaming endpoint for streamlined onboarding.
    Collects: name, username, email, password, confirm password, email verification code,
    favorite color, city, occupation, gender

    Query params:
    - q: user message
    - session_id: unique session identifier (required)
    """
    async def event_gen():
        from simple_onboarding_tools import (
            set_simple_name,
            set_simple_username,
            set_simple_password,
            confirm_simple_password,
            set_ethnicity,
            set_city,
            set_simple_occupation,
            finalize_simple_signup
        )
        from tools import (
            get_user_gender,
            get_email,
            generate_verification_code,
            switch_to_login_mode,
            get_login_username,
            get_login_password,
            verify_login_credentials,
            finalize_login
        )
        from finalize_user import test_verification_code
        import json
        from redis_client import r

        # Get current session status from Redis
        redis_key = f"session:{session_id}"
        session_data_str = r.get(redis_key)

        if session_data_str:
            session_data = json.loads(session_data_str)
            signup_data = session_data.get('signup_data', {})
        else:
            # Initialize empty session
            signup_data = {}
            session_data = {"messages": [], "signup_data": {}}
            r.set(redis_key, json.dumps(session_data))

        # Build dynamic status for each field
        name_status = f"✅ Name: {signup_data.get('name')}" if signup_data.get('name') else "❌ Name not collected yet"
        username_status = f"✅ Username: {signup_data.get('username')}" if signup_data.get('username') else "❌ Username not collected yet"
        email_status = f"✅ Email: {signup_data.get('email')}" if signup_data.get('email') else "❌ Email not collected yet"
        password_status = "✅ Password set" if signup_data.get('password') else "❌ Password not set yet"

        # Check verification status
        verification_code_sent = bool(signup_data.get('verificationCodeGenerated'))
        email_verified = session_data.get('verified')

        if email_verified:
            verification_status = "✅ Email verified successfully"
        elif verification_code_sent:
            verification_status = "⏳ Verification code sent - WAITING for user to provide the code"
        else:
            verification_status = "❌ Verification code not sent yet"

        color_status = f"✅ Favorite color: {signup_data.get('favorite_color')}" if signup_data.get('favorite_color') else "❌ Favorite color not collected yet"
        city_status = f"✅ City: {signup_data.get('city')}" if signup_data.get('city') else "❌ City not collected yet"
        occupation_status = f"✅ Occupation: {signup_data.get('occupation')}" if signup_data.get('occupation') else "❌ Occupation not collected yet"
        gender_status = f"✅ Gender: {signup_data.get('gender')}" if signup_data.get('gender') else "❌ Gender not collected yet"

        # Check if user is in login mode
        is_login_mode = session_data.get("is_login")

        # Build dynamic prompt
        if is_login_mode:
            # Login mode prompt
            login_data = session_data.get("login_data", {})
            has_username = bool(login_data.get("username"))
            has_password = bool(login_data.get("password"))
            login_verified = session_data.get("login_verified", False)

            simple_prompt = f"""You are a friendly assistant helping users log in.

IMPORTANT: The session_id for all tools is: {session_id}
You MUST use this exact session_id when calling any tools.

📊 Current Login Status:

{"✅ Username/email saved" if has_username else "❌ Username/email not provided yet"}
{"✅ Password saved" if has_password else "❌ Password not provided yet"}
{"✅ Credentials verified" if login_verified else "❌ Credentials not verified yet"}

---

Your job is to help the user log in:

1. If username ❌: Ask for their username or email - use get_login_username tool
2. If password ❌: Ask for their password - use get_login_password tool
3. If credentials not verified ❌: Call verify_login_credentials tool
4. If verified ✅: Call finalize_login tool

Be casual, friendly, lowercase gen-z vibes. Keep responses short (1-2 sentences max).

When verify_login_credentials returns "verified", immediately call finalize_login.
When finalize_login returns "verified", say "welcome back! 🌸" and the user is logged in."""

        else:
            # Signup mode prompt
            simple_prompt = f"""You are a friendly onboarding assistant helping new users sign up or log in.

IMPORTANT: The session_id for all tools is: {session_id}
You MUST use this exact session_id when calling any tools.

📊 Current Signup Status:

{name_status}
{username_status}
{email_status}
{password_status}
{verification_status}
{color_status}
{city_status}
{occupation_status}
{gender_status}

---

FIRST: Ask if the user wants to SIGN UP or LOG IN.
- If they want to log in, call switch_to_login_mode tool first, then proceed with login flow.
- If they want to sign up, continue with signup flow below.

Your job is to collect these pieces of information in order (ONLY ask for ❌ missing fields):

1. Name (first name) - use set_simple_name tool
2. Username (no @ symbol) - use set_simple_username tool
3. Email address - use get_email tool
4. Password - use set_simple_password tool
5. Confirm password (must match) - use confirm_simple_password tool
6. Send verification code to email - use generate_verification_code tool (ONLY after password confirmed)
7. **ASK for the verification code they received in their email** - be explicit! say "check your email for the code"
8. Verify the code - use test_verification_code tool with the code they provide
9. Ethnicity - use set_ethnicity tool (ONLY after email verified)
10. City they live in - use set_city tool
11. Occupation - use set_simple_occupation tool
12. Gender - use get_user_gender tool

Be casual, friendly, and conversational. Keep responses short (1-2 sentences max).
Use lowercase, gen-z vibe. Be warm and genuine.

IMPORTANT FLOW:
- SKIP any fields that show ✅ - never ask again!
- After collecting name, username, and email, ask for password
- After password is confirmed, immediately call generate_verification_code
- **CRITICAL: After calling generate_verification_code, you MUST ask them to check their email and provide the 6-digit code**
  Example: "just sent a code to your email! check your inbox and drop the 6-digit code here when you get it"
- If verification status shows ⏳ (code sent, waiting), ASK for the code: "what's the verification code from your email?"
- When they provide the code, call test_verification_code with that code
- If test_verification_code returns "incorrect", ask them to try again
- Only after email is verified (test_verification_code returns "verified"), continue with favorite color, city, occupation, and gender
- After collecting all info AND email is verified, call finalize_simple_signup to create their account

**SPECIAL CASE - If verification status is ⏳:**
This means a code was sent but user hasn't provided it yet.
YOU MUST ask: "hey! what's the verification code from your email? it should be 6 digits"

When test_verification_code returns "verified", say something like "yay! let's keep going" and move to favorite color.
When all info is collected AND email verified, call finalize_simple_signup."""

        # Add dynamic reminder based on verification status
        if verification_code_sent and not email_verified:
            simple_prompt += """

🚨 URGENT REMINDER:
The verification status shows ⏳ which means a code was already sent to the user's email.
Your NEXT message MUST ask them for the verification code!
Say something like: "hey! what's the verification code from your email? it should be 6 digits ✨"
DO NOT proceed with any other questions until they provide the code!"""

        messages = [HumanMessage(content=q)]
        thread = {"configurable": {"thread_id": session_id}}

        signup_complete = False
        login_complete = False

        # Simple tools for this flow
        simple_tools = [
            set_simple_name,
            set_simple_username,
            get_email,
            set_simple_password,
            confirm_simple_password,
            generate_verification_code,
            test_verification_code,
            set_ethnicity,
            set_city,
            set_simple_occupation,
            get_user_gender,
            finalize_simple_signup,
            # Login tools
            switch_to_login_mode,
            get_login_username,
            get_login_password,
            verify_login_credentials,
            finalize_login
        ]

        async with AsyncSqliteSaver.from_conn_string(DB_PATH) as async_memory:
            # Use OpenAI if global flag is set, otherwise use Anthropic
            global use_openai_primary
            primary_model = fallback_model if (use_openai_primary and fallback_model) else model

            try:
                async_abot = Agent(primary_model, simple_tools, system=simple_prompt, checkpointer=async_memory, fallback_model=fallback_model)
                async for ev in async_abot.graph.astream_events({"messages": messages}, thread, version="v1"):
                    # Check if signup or login is complete
                    if ev["event"] == "on_tool_end":
                        tool_name = ev.get("name", "")
                        tool_output = ev.get("data", {}).get("output", "")

                        if tool_name == "finalize_simple_signup" and tool_output == "verified":
                            signup_complete = True
                            logger.info(f"✅ Simple signup completed for session {session_id}")

                        if tool_name == "finalize_login" and tool_output == "verified":
                            login_complete = True
                            logger.info(f"✅ Simple login completed for session {session_id}")

                    # Stream LLM tokens
                    if ev["event"] == "on_chat_model_stream":
                        content = ev["data"]["chunk"].content
                        if content:
                            yield f"event: token\ndata: {json.dumps({'content': content})}\n\n"

            except Exception as e:
                # Check if Anthropic is overloaded
                error_str = str(e)
                is_overload = "overloaded_error" in error_str or "Overloaded" in error_str or "529" in error_str

                if is_overload and fallback_model and not use_openai_primary:
                    logger.info(f"⚠️ Anthropic overloaded! Switching to OpenAI for future requests...")
                    use_openai_primary = True
                    # Retry THIS request with OpenAI
                    async_abot = Agent(fallback_model, simple_tools, system=simple_prompt, checkpointer=async_memory, fallback_model=None)
                    async for ev in async_abot.graph.astream_events({"messages": messages}, thread, version="v1"):
                        if ev["event"] == "on_tool_end":
                            tool_name = ev.get("name", "")
                            tool_output = ev.get("data", {}).get("output", "")

                            if tool_name == "finalize_simple_signup" and tool_output == "verified":
                                signup_complete = True
                                logger.info(f"✅ Simple signup completed for session {session_id}")

                            if tool_name == "finalize_login" and tool_output == "verified":
                                login_complete = True
                                logger.info(f"✅ Simple login completed for session {session_id}")

                        if ev["event"] == "on_chat_model_stream":
                            content = ev["data"]["chunk"].content
                            if content:
                                yield f"event: token\ndata: {json.dumps({'content': content})}\n\n"
                else:
                    raise

        # If signup succeeded, send completion event
        if signup_complete:
            logger.info(f"✅ Sending onboarding_complete to iOS for session {session_id}")
            yield f"event: onboarding_complete\ndata: {json.dumps({'session_id': session_id})}\n\n"

        # If login succeeded, send completion event
        if login_complete:
            logger.info(f"✅ Sending onboarding_complete to iOS for session {session_id}")
            yield f"event: onboarding_complete\ndata: {json.dumps({'session_id': session_id})}\n\n"

        yield "event: done\ndata: {}\n\n"

    headers = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    return StreamingResponse(event_gen(), media_type="text/event-stream", headers=headers)


class PostStreamRequest(BaseModel):
    q: str
    user_id: str
    thread_id: str
    media_urls: Optional[List[str]] = None


@app.post("/post/stream")
async def post_stream(
    q: str = Query(..., description="User's message"),
    user_id: str = Query(..., description="ID of the user creating the post"),
    thread_id: str = Query(..., description="Unique ID for this post conversation"),
    media_urls: Optional[str] = Query(None, description="JSON string of media URLs")
):
    """
    Streaming endpoint for post creation conversations.
    User talks about what they want to post, and when they confirm,
    the system generates captions and saves the post.

    Query params:
    - q: User's message
    - user_id: ID of the user creating the post
    - thread_id: Unique ID for this post conversation (for memory)
    - media_urls: Optional JSON string of base64 encoded images
    """

    # Log media_urls received
    logger.info(f"📸 /post/stream received media_urls: {media_urls}")
    logger.info(f"📸 media_urls type: {type(media_urls)}, length: {len(media_urls) if media_urls else 0}")

    async def event_gen():
        # Check if images were uploaded
        has_images = media_urls and media_urls != "null" and media_urls != "[]"
        images_context = "The user has already uploaded their images." if has_images else "The user hasn't uploaded images yet."

        logger.info(f"📸 has_images: {has_images}, images_context: {images_context}")

        # Build the system prompt
        vision_instruction = ""
        if has_images:
            vision_instruction = "\n\n🎨 VISION MODE: You can see the images! Use what you see to suggest creative titles and captions. Reference specific details - the setting, mood, colors, outfits, activities, people, vibe. Be descriptive and fun!"

        post_prompt = f"""You are a creative assistant helping users create social media posts based on their images.

IMPORTANT: {images_context}{vision_instruction}

Your job:
1. Look at the images they uploaded
2. Suggest a catchy title and caption ideas based on what you see
3. Ask about their vibe preference (aesthetic? party mode? cozy era? girlboss energy?)
4. Refine based on their feedback
5. Get confirmation to post

When suggesting captions:
- Reference what you actually see in the images (location, outfits, activities, mood, colors, setting)
- Match the vibe they describe (if they say "party girl era", make it fun and energetic)
- Keep it lowercase, gen-z style
- KEEP IT SHORT: 3-8 words max
- Include emojis that match the vibe

Examples of how to suggest:
- Beach sunset pics → "ooh stunning sunset vibes! title: 'golden hour therapy', caption: 'sunset state of mind ☀️' sound good?"
- Coffee shop pic → "cozy cafe aesthetic! title: 'main character energy', caption: 'latte in hand ☕️✨' vibe?"
- Night out pics → "party mode activated! title: 'that kind of night', caption: 'night hits different 💫' ready to post?"

Flow:
1. First message: Suggest title + caption based on what you see
2. Ask if they want adjustments or if they're ready
3. When they confirm (e.g., "yes", "post it", "let's go", "perfect"), respond EXACTLY: "posting now!"

Keep responses short (1-2 sentences), lowercase, friendly gen-z vibes.
If they just upload images without text, analyze the images and suggest title/caption immediately."""

        # Parse media_urls and format for Claude vision
        # Only use multimodal format if images are present
        if has_images:
            message_content = []

            # Add user's text
            message_content.append({
                "type": "text",
                "text": q
            })

            # Add images
            try:
                # Debug logging to see what we're receiving
                logger.info(f"🔍 DEBUG - Raw media_urls received: {repr(media_urls)}")
                logger.info(f"🔍 DEBUG - media_urls type: {type(media_urls)}")
                logger.info(f"🔍 DEBUG - media_urls length: {len(media_urls)}")

                # Parse JSON string into list
                parsed_media = json.loads(media_urls)
                logger.info(f"📸 Parsed {len(parsed_media)} images for Claude vision")
                logger.info(f"🔍 DEBUG - parsed_media type: {type(parsed_media)}")

                # Validate that it's a list
                if not isinstance(parsed_media, list):
                    raise ValueError(f"Expected list, got {type(parsed_media)}")

                # Log each item in parsed_media
                for idx, item in enumerate(parsed_media):
                    item_preview = repr(item[:100]) if isinstance(item, str) and len(item) > 100 else repr(item)
                    logger.info(f"🔍 DEBUG - Item {idx}: type={type(item).__name__}, len={len(item) if hasattr(item, '__len__') else 'N/A'}, value={item_preview}")

                    # Validate each item is a string
                    if not isinstance(item, str):
                        raise ValueError(f"Expected string URL at index {idx}, got {type(item)}")

                for img_url in parsed_media:
                    # Ensure img_url is a plain string, not a JSON-encoded string
                    if not isinstance(img_url, str):
                        logger.error(f"❌ Skipping non-string URL: {type(img_url)}")
                        continue
                    # Check if it's a URL (Firebase Storage, http/https)
                    if img_url.startswith('http://') or img_url.startswith('https://'):
                        # Clean up URL - remove explicit port :443 (Claude doesn't like it)
                        clean_url = img_url.replace(':443/', '/')

                        # Fix Firebase Storage URL encoding - the path component needs proper encoding
                        if 'firebasestorage.googleapis.com' in clean_url:
                            from urllib.parse import urlparse, quote, urlunparse
                            parsed = urlparse(clean_url)
                            # Re-encode the path component (especially /o/posts/file.jpg -> /o/posts%2Ffile.jpg)
                            path_parts = parsed.path.split('/o/')
                            if len(path_parts) == 2:
                                # Encode everything after /o/ (the storage path)
                                # Use safe='%' to preserve already-encoded characters (avoid double-encoding)
                                encoded_storage_path = quote(path_parts[1], safe='%')
                                # Keep the part before /o/ (e.g., /v0/b/bucket-name.firebasestorage.app)
                                clean_url = urlunparse((
                                    parsed.scheme,
                                    parsed.netloc,
                                    f'{path_parts[0]}/o/{encoded_storage_path}',
                                    parsed.params,
                                    parsed.query,
                                    parsed.fragment
                                ))
                                logger.info(f"🔍 Fixed Firebase URL encoding: {clean_url[:150]}")

                        # Validate it's a plain string URL (not JSON-encoded)
                        logger.info(f"🔍 DEBUG - clean_url type: {type(clean_url)}, value: {repr(clean_url[:150])}")

                        # Use URL format for Claude vision
                        image_block = {
                            "type": "image",
                            "source": {
                                "type": "url",
                                "url": clean_url
                            }
                        }
                        message_content.append(image_block)
                        logger.info(f"📸 Added image from URL: {clean_url[:100]}...")
                        logger.info(f"🔍 DEBUG - Image block added to message_content: {image_block}")

                    # Check if it's a data URI (data:image/jpeg;base64,...)
                    elif img_url.startswith('data:image'):
                        # Format: data:image/jpeg;base64,/9j/4AAQSkZJRg...
                        parts = img_url.split(',', 1)
                        if len(parts) == 2:
                            base64_data = parts[1]
                            # Detect media type from prefix
                            media_type = "image/jpeg"  # default
                            if "image/png" in parts[0]:
                                media_type = "image/png"
                            elif "image/webp" in parts[0]:
                                media_type = "image/webp"
                            elif "image/gif" in parts[0]:
                                media_type = "image/gif"
                        else:
                            base64_data = img_url
                            media_type = "image/jpeg"

                        message_content.append({
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": base64_data
                            }
                        })
                        logger.info(f"📸 Added image from data URI (media_type: {media_type})")

                    else:
                        # Assume raw base64 data
                        message_content.append({
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/jpeg",
                                "data": img_url
                            }
                        })
                        logger.info(f"📸 Added image from raw base64 data")

                messages = [HumanMessage(content=message_content)]

                # Log final message structure
                logger.info(f"🔍 DEBUG - Final message_content structure: {len(message_content)} items")
                for idx, item in enumerate(message_content):
                    if item.get("type") == "image":
                        url_preview = item["source"]["url"][:100] if len(item["source"]["url"]) > 100 else item["source"]["url"]
                        logger.info(f"🔍 DEBUG - Content[{idx}]: type=image, url={repr(url_preview)}")
                    else:
                        logger.info(f"🔍 DEBUG - Content[{idx}]: type={item.get('type')}")

            except Exception as e:
                logger.error(f"❌ Error parsing media_urls for vision: {e}")
                logger.error(f"🔍 DEBUG - Exception details: {type(e).__name__}: {str(e)}")
                # Fallback to text only
                messages = [HumanMessage(content=q)]
                logger.info("📝 Falling back to text-only mode due to error")
        else:
            # No images - use simple text format (backwards compatible)
            messages = [HumanMessage(content=q)]
        thread = {"configurable": {"thread_id": thread_id}}

        post_initiated = False
        redis_id = None
        full_response = ""

        async with AsyncSqliteSaver.from_conn_string(DB_PATH) as async_memory:
            global use_openai_primary
            primary_model = fallback_model if (use_openai_primary and fallback_model) else model

            try:
                async_abot = Agent(primary_model, [], system=post_prompt, checkpointer=async_memory, fallback_model=fallback_model)
                async for ev in async_abot.graph.astream_events({"messages": messages}, thread, version="v1"):
                    # Stream LLM tokens
                    if ev["event"] == "on_chat_model_stream":
                        content = ev["data"]["chunk"].content
                        logger.info(f"🔍 Raw content from AI: {content} (type: {type(content)})")
                        if content:
                            # Handle both string and list content
                            if isinstance(content, str):
                                content_str = content
                            elif isinstance(content, list) and len(content) > 0:
                                # Extract text from list format [{"text": "...", "type": "text"}]
                                content_str = content[0].get("text", "") if isinstance(content[0], dict) else str(content[0])
                            else:
                                content_str = ""

                            if content_str:  # Only process if we have actual text
                                full_response += content_str

                                # Format content for iOS (Anthropic format)
                                content_block = {
                                    "content": [{
                                        "text": content_str,
                                        "type": "text",
                                        "index": 0
                                    }]
                                }
                                yield f"event: token\ndata: {json.dumps(content_block)}\n\n"

                            # Check if AI is confirming post
                            if "posting now" in full_response.lower() and not post_initiated:
                                post_initiated = True
                                redis_id = str(uuid.uuid4())

                                # Set initial Redis status
                                r.set(f"post_status:{redis_id}", json.dumps({
                                    "status": "processing",
                                    "message": "starting post creation..."
                                }), ex=300)

                                logger.info(f"✅ Post confirmation detected! Created redis_id: {redis_id}")

                                # Start background task
                                from post_tools import create_post_from_conversation
                                asyncio.create_task(
                                    create_post_from_conversation(redis_id, user_id, thread_id, media_urls, DB_PATH)
                                )

            except Exception as e:
                error_str = str(e)
                is_overload = "overloaded_error" in error_str or "Overloaded" in error_str or "529" in error_str

                if is_overload and fallback_model and not use_openai_primary:
                    logger.info(f"⚠️ Anthropic overloaded! Switching to OpenAI...")
                    use_openai_primary = True
                    async_abot = Agent(fallback_model, [], system=post_prompt, checkpointer=async_memory, fallback_model=None)
                    async for ev in async_abot.graph.astream_events({"messages": messages}, thread, version="v1"):
                        if ev["event"] == "on_chat_model_stream":
                            content = ev["data"]["chunk"].content
                            if content:
                                # Handle both string and list content
                                if isinstance(content, str):
                                    content_str = content
                                elif isinstance(content, list) and len(content) > 0:
                                    # Extract text from list format [{"text": "...", "type": "text"}]
                                    content_str = content[0].get("text", "") if isinstance(content[0], dict) else str(content[0])
                                else:
                                    content_str = ""

                                if content_str:  # Only process if we have actual text
                                    full_response += content_str

                                    # Format content for iOS (Anthropic format)
                                    content_block = {
                                        "content": [{
                                            "text": content_str,
                                            "type": "text",
                                            "index": 0
                                        }]
                                    }
                                    yield f"event: token\ndata: {json.dumps(content_block)}\n\n"

                                # Check if AI is confirming post
                                if "posting now" in full_response.lower() and not post_initiated:
                                    post_initiated = True
                                    redis_id = str(uuid.uuid4())

                                    # Set initial Redis status
                                    r.set(f"post_status:{redis_id}", json.dumps({
                                        "status": "processing",
                                        "message": "starting post creation..."
                                    }), ex=300)

                                    logger.info(f"✅ [FALLBACK] Post confirmation detected! Created redis_id: {redis_id}")

                                    # Start background task
                                    from post_tools import create_post_from_conversation
                                    asyncio.create_task(
                                        create_post_from_conversation(redis_id, user_id, thread_id, media_urls, DB_PATH)
                                    )
                else:
                    raise

        yield "event: done\ndata: {}\n\n"

        # If post was initiated, send redis_id for polling AFTER done
        if post_initiated and redis_id:
            logger.info(f"✅ Sending post_initiated event with redis_id: {redis_id}")
            yield f"event: post_initiated\ndata: {json.dumps({'user_id': user_id, 'redis_id': redis_id})}\n\n"

    headers = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    return StreamingResponse(event_gen(), media_type="text/event-stream", headers=headers)


@app.get("/feed/{user_id}")
async def get_user_feed(user_id: str, limit: int = 5, offset: int = 0):
    """
    Get posts for a user's feed.
    Returns posts from users they follow, ordered by creation time (newest first).
    Uses eager loading to fetch all data in ONE query instead of N+1 queries.

    Query params:
    - user_id: ID of the user viewing the feed
    - limit: Number of posts to return (default 5, max 20)
    - offset: Offset for pagination (default 0)
    """
    from database.models import Post, PostMedia
    from sqlalchemy import desc
    from sqlalchemy.orm import joinedload

    try:
        db = SessionLocal()

        # Limit max to 20 posts per request
        limit = min(limit, 20)

        # Get list of users this user follows
        following = db.query(Follow.following_id).filter(Follow.follower_id == user_id).all()
        following_ids = [f[0] for f in following]

        # Add user's own ID to see their own posts (like Instagram)
        following_ids.append(user_id)

        # Get users that the current user has reported (to exclude ALL their posts)
        reported_user_ids = db.query(Report.reported_user_id).filter(Report.reporter_id == user_id).distinct().all()
        reported_user_ids = [r[0] for r in reported_user_ids]

        # Get blocked users (users you blocked + users who blocked you)
        blocked_by_me = db.query(Block.blocked_id).filter(Block.blocker_id == user_id).all()
        blocked_me = db.query(Block.blocker_id).filter(Block.blocked_id == user_id).all()
        blocked_user_ids = [b[0] for b in blocked_by_me] + [b[0] for b in blocked_me]

        # Combine reported and blocked users
        excluded_user_ids = list(set(reported_user_ids + blocked_user_ids))

        # Get posts from followed users + own posts, excluding reported and blocked users
        # Use eager loading to fetch user and media in ONE query (not 11 queries!)
        query = db.query(Post).filter(Post.user_id.in_(following_ids))
        if excluded_user_ids:
            query = query.filter(~Post.user_id.in_(excluded_user_ids))

        posts = query.options(
            joinedload(Post.user),
            joinedload(Post.media)
        ).order_by(desc(Post.created_at)).limit(limit).offset(offset).all()

        # Build response with post data and media
        feed_posts = []
        for post in posts:
            # User and media already loaded via joinedload (no extra queries!)
            user = post.user
            media_urls = [m.media_url for m in post.media]

            feed_posts.append({
                "post_id": post.id,
                "user_id": post.user_id,
                "username": user.username if user else "unknown",
                "name": user.name if user else "Unknown",
                "title": post.title,
                "caption": post.caption,
                "location": post.location,
                "ai_sentence": post.ai_sentence,  # AI-generated announcement
                "media_urls": media_urls,
                "created_at": post.created_at.isoformat() if post.created_at else None,
                # Actor is the person who created the post
                "actor_id": post.user_id,
                "actor_username": user.username if user else "unknown",
                "actor_name": user.name if user else "Unknown",
                "actor_profile_image": user.profile_image if user else None
            })

        db.close()

        logger.info(f"✅ Retrieved {len(feed_posts)} posts for user {user_id}'s feed (offset: {offset})")

        return {
            "status": "success",
            "posts": feed_posts,
            "total": len(feed_posts),
            "offset": offset,
            "limit": limit
        }

    except Exception as e:
        logger.error(f"❌ Error getting feed: {e}")
        return {
            "status": "error",
            "error": str(e)
        }


@app.get("/feed/mixed/{user_id}")
async def get_mixed_feed(user_id: str, offset: int = 0, limit: int = 20):
    """
    Get mixed feed with friend posts + AI recommendation groups.

    Logic:
    - Returns friend posts (from people you follow) mixed with AI groups
    - Every 4 friend posts, inserts 1 AI group
    - When friend posts run out, continues with infinite AI groups
    - Posts ordered by recency (newest first)

    Query params:
    - user_id: ID of the user viewing the feed
    - offset: Pagination offset (default 0)
    - limit: Max friend posts to fetch (default 20)

    Returns:
        {
            "status": "success",
            "feed": [
                {"type": "post", "data": {...}},
                {"type": "ai_group", "data": {...}},
                ...
            ]
        }
    """
    from database.models import Post, PostMedia
    from sqlalchemy import desc
    from sqlalchemy.orm import joinedload

    try:
        db = SessionLocal()

        # Step 1: Get friend posts (people you follow, NOT your own posts)
        following = db.query(Follow.following_id).filter(Follow.follower_id == user_id).all()
        following_ids = [f[0] for f in following]
        # Don't include your own posts - iOS will handle showing them temporarily after posting

        # Get users that the current user has reported (to exclude ALL their posts)
        reported_user_ids = db.query(Report.reported_user_id).filter(Report.reporter_id == user_id).distinct().all()
        reported_user_ids = [r[0] for r in reported_user_ids]

        # Get blocked users (users you blocked + users who blocked you)
        blocked_by_me = db.query(Block.blocked_id).filter(Block.blocker_id == user_id).all()
        blocked_me = db.query(Block.blocker_id).filter(Block.blocked_id == user_id).all()
        blocked_user_ids = [b[0] for b in blocked_by_me] + [b[0] for b in blocked_me]

        # Combine reported and blocked users
        excluded_user_ids = list(set(reported_user_ids + blocked_user_ids))

        # Build query to exclude posts from reported and blocked users
        query = db.query(Post).filter(Post.user_id.in_(following_ids))
        if excluded_user_ids:
            query = query.filter(~Post.user_id.in_(excluded_user_ids))

        friend_posts = query.options(
            joinedload(Post.user),
            joinedload(Post.media)
        ).order_by(desc(Post.created_at)).limit(limit).offset(offset).all()

        # Build friend posts data
        friend_posts_data = []
        for post in friend_posts:
            user = post.user
            media_urls = [m.media_url for m in post.media]

            friend_posts_data.append({
                "post_id": post.id,
                "user_id": post.user_id,
                "username": user.username if user else "unknown",
                "name": user.name if user else "Unknown",
                "title": post.title,
                "caption": post.caption,
                "location": post.location,
                "ai_sentence": post.ai_sentence,
                "media_urls": media_urls,
                "created_at": post.created_at.isoformat() if post.created_at else None,
                "actor_id": post.user_id,
                "actor_username": user.username if user else "unknown",
                "actor_name": user.name if user else "Unknown",
                "actor_profile_image": user.profile_image if user else None
            })

        db.close()

        # Step 2: Generate 1 AI group
        from profile_embeddings import generate_ai_groups, find_users_from_ai_description

        logger.info(f"🤖 Generating 1 AI group for mixed feed")

        ai_descriptions = generate_ai_groups(user_id, count=1)  # Generate only 1 group
        ai_groups_data = []

        if ai_descriptions and len(ai_descriptions) > 0:
            matched_users = find_users_from_ai_description(ai_descriptions[0], top_k=5)

            # Filter out reported and blocked users from AI recommendations
            if excluded_user_ids:
                matched_users = [user for user in matched_users if user['user_id'] not in excluded_user_ids]

            # Only add the group if there are users to show
            if matched_users:
                ai_groups_data.append({
                    "description": ai_descriptions[0],
                    "users": matched_users
                })

        # Step 3: Mix friend posts + AI groups
        mixed_feed = []
        ai_group_index = 0

        for i, post in enumerate(friend_posts_data):
            # Add friend post
            mixed_feed.append({
                "type": "post",
                "data": post
            })

            # Insert AI group every 4 posts
            if (i + 1) % 4 == 0 and ai_group_index < len(ai_groups_data):
                mixed_feed.append({
                    "type": "ai_group",
                    "data": ai_groups_data[ai_group_index]
                })
                ai_group_index += 1

        # If friend posts ran out, add remaining AI groups for infinite scroll
        while ai_group_index < len(ai_groups_data):
            mixed_feed.append({
                "type": "ai_group",
                "data": ai_groups_data[ai_group_index]
            })
            ai_group_index += 1

        logger.info(f"✅ Generated mixed feed: {len(friend_posts_data)} posts + {ai_group_index} AI groups = {len(mixed_feed)} total items")

        return {
            "status": "success",
            "feed": mixed_feed,
            "offset": offset,
            "limit": limit
        }

    except Exception as e:
        logger.error(f"❌ Error generating mixed feed: {e}")
        return {
            "status": "error",
            "error": str(e)
        }


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
        from jwt_utils import create_access_token, create_refresh_token
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


@app.post("/signup/simple")
async def simple_signup(request: SimpleSignupRequest):
    """
    Simple signup endpoint - returns redis_id immediately, creates user in background.
    Generates an AI bio based on user's Instagram bio input.

    Request body:
    {
        "username": "architavn",
        "email": "archita@example.com",
        "password": "password123",
        "name": "Archita",
        "instagram_bio": "cs @ berkeley | building cool stuff | coffee enthusiast",
        "gender": "female",
        "ethnicity": "south asian"
    }

    Returns:
    {
        "status": "success",
        "redis_id": "abc-123"
    }

    iOS should poll: GET /poll/{redis_id} to get user data when ready
    """
    import bcrypt
    from database.db import SessionLocal
    from database.models import User
    import uuid
    import asyncio

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

        db.close()

        # Generate redis_id
        redis_id = str(uuid.uuid4())

        # Set initial status in Redis
        r.set(f"signup:{redis_id}", json.dumps({
            "status": "processing",
            "message": "Creating your account..."
        }), ex=600)  # 10 min expiry

        # Start background task to create user
        async def create_user_background():
            try:
                from datetime import datetime

                db = SessionLocal()

                # Hash password
                hashed_password = bcrypt.hashpw(
                    request.password.encode('utf-8'),
                    bcrypt.gensalt()
                ).decode('utf-8')

                # Generate AI bio from Instagram bio
                logger.info(f"🤖 Generating AI bio from: {request.instagram_bio[:50]}...")
                generated_bio = None
                try:
                    from anthropic import Anthropic
                    client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

                    prompt = f"""Make this bio SHORT AF with sassy personality: "{request.instagram_bio}"

RULES:
- SUPER SHORT (3-5 words max)
- all lowercase
- include city/school if mentioned
- gen z slang + sassy personalitys

Examples:
- her location is sf but she’s an east coast girly from cornell
- he goes to cornell law. what, like it's hard?
- she's a baddie and she knows she's a ten. harvard class of 26 💅

be confident, slightly sassy, and human in all the bio generations. 

Return SHORT bio, lowercase, and EMPHASIS ON SPECIFICITY related to the user."""

                    response = client.messages.create(
                        model="claude-sonnet-4-20250514",
                        max_tokens=150,
                        messages=[{"role": "user", "content": prompt}]
                    )

                    generated_bio = response.content[0].text.strip()
                    logger.info(f"✨ Generated bio: {generated_bio}")

                except Exception as bio_error:
                    logger.error(f"❌ Error generating bio: {bio_error}")
                    generated_bio = request.instagram_bio  # Fallback to original

                # Generate zero followers sentence for UI
                logger.info(f"🤖 Generating zero followers sentence...")
                followers_sentence = None
                try:
                    followers_prompt = f"""Generate a SHORT, funny, self-aware sentence about having 0 followers and following 0 people.

Context:
- Gender: {request.gender}

RULES:
- lowercase
- gen z humor
- self-aware/sassy
- one sentence max and SHORT. 
- acknowledge they're brand new (0 followers, 0 following). express as numbers "0" instead of string "zero".

Examples:
"0 followers and 0 following. please clap!!"
"0 followers + 0 following. she just got here hehe"
"0 followers, 0 following. this feels illegal with no followers"
"0 followers. 0 following. pls imagine a crowd here"


Return ONE sentence, lowercase."""

                    followers_response = client.messages.create(
                        model="claude-sonnet-4-20250514",
                        max_tokens=50,
                        messages=[{"role": "user", "content": followers_prompt}]
                    )

                    followers_sentence = followers_response.content[0].text.strip()
                    logger.info(f"✨ Generated followers sentence: {followers_sentence}")

                except Exception as followers_error:
                    logger.error(f"❌ Error generating followers sentence: {followers_error}")
                    followers_sentence = "starting from zero but the vibe is immaculate"  # Fallback

                # Get cartoon avatar for females
                profile_image_url = None
                if request.gender.lower() == 'female':
                    from avatar_helper import get_cartoon_avatar
                    profile_image_url = get_cartoon_avatar(request.gender, request.ethnicity)
                    logger.info(f"🎨 Selected avatar: {profile_image_url}")

                # Create user
                user_id = str(uuid.uuid4())
                new_user = User(
                    id=user_id,
                    username=request.username,
                    email=request.email,
                    name=request.name,
                    password=hashed_password,
                    gender=request.gender,
                    ethnicity=request.ethnicity,
                    bio=generated_bio,  # Store AI-generated bio
                    profile_image=profile_image_url,
                    created_at=datetime.utcnow()
                )

                db.add(new_user)
                db.commit()
                db.refresh(new_user)

                logger.info(f"✅ Created user {user_id} (@{request.username})")

                # Create profile embedding
                from profile_embeddings import create_user_profile_embedding
                embedding_result = create_user_profile_embedding(new_user)
                logger.info(f"📊 Embedding creation: {embedding_result}")

                # Generate JWT tokens
                from jwt_utils import create_access_token, create_refresh_token
                access_token = create_access_token(user_id)
                refresh_token = create_refresh_token(user_id)

                # Generate first feed group (only 1 group)
                logger.info(f"🔄 Generating first feed for user {user_id}")
                from profile_embeddings import generate_ai_groups, find_users_from_ai_description

                first_group = None
                feed_ready = False

                try:
                    groups = generate_ai_groups(user_id, count=1)  # Generate only 1 group
                    if groups and len(groups) > 0:
                        first_description = groups[0]
                        matched_users = find_users_from_ai_description(first_description, top_k=5)

                        first_group = {
                            "description": first_description,
                            "users": matched_users
                        }
                        feed_ready = True
                        logger.info(f"✅ First feed group generated")
                except Exception as feed_error:
                    logger.error(f"❌ Error generating feed: {feed_error}")

                db.close()

                # Update Redis with completed data
                r.set(f"signup:{redis_id}", json.dumps({
                    "status": "ready",
                    "user_id": user_id,
                    "name": new_user.name,
                    "username": new_user.username,
                    "bio": generated_bio,  # AI-generated bio
                    "followers_sentence": followers_sentence,  # Zero followers UI sentence (not in DB)
                    "access_token": access_token,
                    "refresh_token": refresh_token,
                    "profile_image": profile_image_url,
                    "feed_ready": feed_ready,
                    "first_group": first_group
                }), ex=600)

                logger.info(f"✅ Signup complete for {user_id}, stored in Redis")

            except Exception as e:
                logger.error(f"❌ Error in background signup: {e}")
                r.set(f"signup:{redis_id}", json.dumps({
                    "status": "error",
                    "error": str(e)
                }), ex=600)
                if 'db' in locals():
                    db.close()

        # Start background task
        asyncio.create_task(create_user_background())

        logger.info(f"✅ Signup initiated with redis_id: {redis_id}")

        return {
            "status": "success",
            "redis_id": redis_id
        }

    except Exception as e:
        logger.error(f"❌ Error initiating signup: {e}")
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


@app.get("/feed/recommendations/{user_id}/stream")
async def stream_ai_recommendations(user_id: str):
    """
    Stream AI-generated recommendations one group at a time.
    Returns Server-Sent Events (SSE) for progressive loading.

    Events:
    - group_start: AI sentence generated
    - user: Each user found
    - group_complete: Group finished
    """
    async def event_generator():
        try:
            from profile_embeddings import find_users_from_ai_description
            from anthropic import Anthropic
            from database.db import SessionLocal
            from database.models import User
            import json
            import asyncio
            import os

            # Get user profile for personalization
            db = SessionLocal()
            user = db.query(User).filter(User.id == user_id).first()
            db.close()

            if not user:
                user_city = "the city"
                user_occupation = "students"
                user_gender = "people"
            else:
                user_city = user.city or "the city"
                user_occupation = user.occupation or "students"
                user_gender = user.gender or "people"

            # Stream AI sentence generation
            client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

            prompt = f"""Generate 5 diverse, funny group descriptions for finding similar people.

The user is: {user_gender}, lives in {user_city}, occupation: {user_occupation}.

CRITICAL: Each description must have a DIFFERENT vibe. Assign each one a specific tone:
1. CHAOTIC energy
2. BITCHY-CUTE
3. UNHINGED
4. DRY HUMOR
5. VILLAIN ARC

FORMAT - always two lines:
- Line 1: main description (5-10 words)
- Line 2: shorter (3-5 words) - can be (parenthetical) or just continue

Return ONLY a JSON array of 5 strings, no other text."""

            # Stream the AI response
            full_response = ""
            async with client.messages.stream(
                model="claude-sonnet-4-20250514",
                max_tokens=300,
                messages=[{"role": "user", "content": prompt}]
            ) as stream:
                async for text in stream.text_stream:
                    full_response += text
                    # Stream chunks as they arrive
                    yield f"event: ai_chunk\ndata: {json.dumps({'text': text})}\n\n"

            # Parse the complete response
            if "[" in full_response:
                start = full_response.find("[")
                end = full_response.rfind("]") + 1
                json_str = full_response[start:end]
                descriptions = json.loads(json_str)
                description = descriptions[0]
            else:
                description = "other people in your city"

            # Signal AI sentence is complete
            yield f"event: group_start\ndata: {json.dumps({'description': description})}\n\n"

            # Now find and stream users
            logger.info(f"🔍 Finding users for: {description}")
            matched_users = find_users_from_ai_description(description, top_k=5)

            for user_data in matched_users:
                yield f"event: user\ndata: {json.dumps(user_data)}\n\n"

            yield f"event: group_complete\ndata: {json.dumps({'description': description})}\n\n"

        except Exception as e:
            logger.error(f"❌ Error streaming recommendations: {e}")
            yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.get("/feed/recommendations/{user_id}")
async def get_ai_recommendations(user_id: str, count: int = 1):
    """
    Get AI-generated user recommendations based on semantic similarity.
    Returns one group at a time for infinite scroll.

    Query params:
    - count: Number of groups to return (default 1)

    Workflow:
    1. Generate AI group descriptions (e.g., "college students in NYC into fashion")
    2. For each description, find top 5 similar users from Pinecone
    3. Return groups with their matched users

    Returns:
        {
            "status": "success",
            "groups": [
                {
                    "description": "college students in NYC into fashion",
                    "users": [
                        {"user_id": "...", "name": "...", "username": "...", ...},
                        ...
                    ]
                }
            ]
        }
    """
    try:
        from profile_embeddings import generate_ai_groups, find_users_from_ai_description

        # Limit count to max 5
        count = min(count, 5)

        # Step 1: Generate AI group descriptions
        logger.info(f"🤖 Generating {count} AI group(s) for user {user_id}")
        all_descriptions = generate_ai_groups(user_id)

        # Take only the requested number of groups
        group_descriptions = all_descriptions[:count]

        # Step 2: For each description, find matching users
        groups = []
        for description in group_descriptions:
            logger.info(f"🔍 Finding users for: {description}")
            matched_users = find_users_from_ai_description(description, top_k=5)

            groups.append({
                "description": description,
                "users": matched_users
            })

        logger.info(f"✅ Generated {len(groups)} recommendation group(s) for user {user_id}")

        return {
            "status": "success",
            "groups": groups
        }

    except Exception as e:
        logger.error(f"❌ Error generating recommendations: {e}")
        return {
            "status": "error",
            "error": str(e)
        }


@app.post("/feed/prefetch/{user_id}")
async def prefetch_feed(user_id: str):
    """
    Generate next feed group when user closes the app.
    Returns the feed immediately so iOS can cache it locally.

    Called by iOS when app goes to background.

    Returns:
        {
            "status": "success",
            "group": {
                "description": "...",
                "users": [...]
            }
        }
    """
    try:
        from profile_embeddings import generate_ai_groups, find_users_from_ai_description

        logger.info(f"🔄 Generating feed for user {user_id} (app closing)")

        # Generate AI group
        groups = generate_ai_groups(user_id)
        if not groups or len(groups) == 0:
            logger.error(f"❌ No groups generated for user {user_id}")
            return {
                "status": "error",
                "error": "No groups generated"
            }

        next_description = groups[0]  # This is a string

        # Find matching users
        matched_users = find_users_from_ai_description(
            next_description,
            top_k=5
        )

        # Build the group object
        next_group = {
            "description": next_description,
            "users": matched_users
        }

        logger.info(f"✅ Feed generated for user {user_id}, returning to iOS for caching")

        return {
            "status": "success",
            "group": next_group
        }

    except Exception as e:
        logger.error(f"❌ Error generating feed for user {user_id}: {e}")
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


class LikeRequest(BaseModel):
    user_id: str


@app.post("/posts/{post_id}/like")
async def like_post(post_id: str, request: LikeRequest):
    """
    Like a post.

    Request body:
    {
        "user_id": "user-id-here"
    }

    Returns:
        Success status and like count
    """
    from database.models import Post, Like

    user_id = request.user_id
    db = SessionLocal()
    try:
        # Check if post exists
        post = db.query(Post).filter(Post.id == post_id).first()
        if not post:
            return {
                "status": "error",
                "message": "Post not found"
            }

        # Check if already liked
        existing_like = db.query(Like).filter(
            Like.user_id == user_id,
            Like.post_id == post_id
        ).first()

        if existing_like:
            return {
                "status": "error",
                "message": "Post already liked"
            }

        # Create like
        new_like = Like(
            user_id=user_id,
            post_id=post_id
        )
        db.add(new_like)
        db.commit()

        # Get like count
        like_count = db.query(Like).filter(Like.post_id == post_id).count()

        logger.info(f"✅ User {user_id} liked post {post_id}")

        # Send notification to post owner
        post_owner = db.query(User).filter(User.id == post.user_id).first()
        liker = db.query(User).filter(User.id == user_id).first()

        if post_owner and post_owner.device_token and liker and post_owner.id != user_id:
            # Check follow relationship
            i_follow_them = db.query(Follow).filter(
                Follow.follower_id == post.user_id,
                Follow.following_id == user_id
            ).first() is not None

            they_follow_me = db.query(Follow).filter(
                Follow.follower_id == user_id,
                Follow.following_id == post.user_id
            ).first() is not None

            # Generate notification message
            from push_notifications import send_like_notification
            await send_like_notification(
                device_token=post_owner.device_token,
                liker_name=liker.name,
                liker_username=liker.username,
                liker_id=liker.id,
                liker_city=liker.city,
                liker_occupation=liker.occupation,
                post_id=post_id,
                post_title=post.title,
                i_follow_them=i_follow_them,
                they_follow_me=they_follow_me
            )

        return {
            "status": "success",
            "message": "Post liked",
            "like_count": like_count
        }

    except Exception as e:
        db.rollback()
        logger.error(f"❌ Error liking post: {e}")
        return {
            "status": "error",
            "error": str(e)
        }
    finally:
        db.close()


@app.delete("/posts/{post_id}/unlike")
async def unlike_post(post_id: str, user_id: str):
    """
    Unlike a post.

    Query params:
    - user_id: ID of the user unliking

    Returns:
        Success status and like count
    """
    from database.models import Like

    db = SessionLocal()
    try:
        # Find and delete the like
        like = db.query(Like).filter(
            Like.user_id == user_id,
            Like.post_id == post_id
        ).first()

        if not like:
            return {
                "status": "error",
                "message": "Like not found"
            }

        db.delete(like)
        db.commit()

        # Get updated like count
        like_count = db.query(Like).filter(Like.post_id == post_id).count()

        logger.info(f"✅ User {user_id} unliked post {post_id}")

        return {
            "status": "success",
            "message": "Post unliked",
            "like_count": like_count
        }

    except Exception as e:
        db.rollback()
        logger.error(f"❌ Error unliking post: {e}")
        return {
            "status": "error",
            "error": str(e)
        }
    finally:
        db.close()


@app.get("/posts/{post_id}/likes")
async def get_post_likes(post_id: str, user_id: Optional[str] = None):
    """
    Get like count for a post and optionally check if a user has liked it.

    Query params:
    - user_id (optional): Check if this user has liked the post

    Returns:
        Like count and liked status
    """
    from database.models import Like

    db = SessionLocal()
    try:
        # Get like count
        like_count = db.query(Like).filter(Like.post_id == post_id).count()

        # Check if user has liked (if user_id provided)
        liked_by_user = False
        if user_id:
            liked_by_user = db.query(Like).filter(
                Like.user_id == user_id,
                Like.post_id == post_id
            ).first() is not None

        return {
            "status": "success",
            "post_id": post_id,
            "like_count": like_count,
            "liked_by_user": liked_by_user
        }

    except Exception as e:
        logger.error(f"❌ Error getting likes: {e}")
        return {
            "status": "error",
            "error": str(e)
        }
    finally:
        db.close()


@app.get("/posts/user/{user_id}")
async def get_user_posts(user_id: str, limit: int = 2, offset: int = 0):
    """
    Get all posts by a specific user.
    Uses eager loading to fetch all data in ONE query instead of N+1 queries.

    Query params:
    - user_id: ID of the user whose posts to retrieve
    - limit: Number of posts to return (default 2, max 20)
    - offset: Offset for pagination (default 0)
    """
    from database.models import Post, PostMedia
    from sqlalchemy import desc
    from sqlalchemy.orm import joinedload

    try:
        db = SessionLocal()

        # Limit max to 20 posts per request
        limit = min(limit, 20)

        # Get user info once
        user = db.query(User).filter(User.id == user_id).first()

        # Get posts by this user with eager loading for media
        posts = db.query(Post).filter(
            Post.user_id == user_id
        ).options(
            joinedload(Post.media)  # ← Fetch media in same query
        ).order_by(desc(Post.created_at)).limit(limit).offset(offset).all()

        # Build response with post data and media
        user_posts = []
        for post in posts:
            # Media already loaded via joinedload (no extra queries!)
            media_urls = [m.media_url for m in post.media]

            user_posts.append({
                "post_id": post.id,
                "title": post.title,
                "caption": post.caption,
                "ai_sentence": post.ai_sentence,  # AI-generated announcement
                "post_media": media_urls,  # Array of 1-10 image URLs
                "created_at": post.created_at.isoformat() if post.created_at else None,
                # Actor is the person who created the post
                "actor_id": user_id,
                "actor_username": user.username if user else "unknown",
                "actor_name": user.name if user else "Unknown",
                "actor_profile_image": user.profile_image if user else None
            })

        db.close()

        logger.info(f"✅ Retrieved {len(user_posts)} posts for user {user_id} (offset: {offset})")

        return {
            "status": "success",
            "user_id": user_id,
            "username": user.username if user else "unknown",
            "name": user.name if user else "Unknown",
            "posts": user_posts,
            "total": len(user_posts),
            "offset": offset,
            "limit": limit
        }

    except Exception as e:
        logger.error(f"❌ Error getting user posts: {e}")
        return {
            "status": "error",
            "error": str(e)
        }


@app.get("/post/{post_id}")
async def get_post_by_id(post_id: str, user_id: Optional[str] = None):
    """
    Get detailed information for a specific post by post_id.

    Path params:
    - post_id: ID of the post to retrieve

    Query params:
    - user_id (optional): If provided, returns whether this user has liked the post

    Returns:
    - Complete post information including user details, media, engagement stats
    """
    from database.models import Post, PostMedia, Like, Comment
    from sqlalchemy.orm import joinedload

    try:
        db = SessionLocal()

        # Get post with eager loading for user and media
        post = db.query(Post).filter(
            Post.id == post_id
        ).options(
            joinedload(Post.user),
            joinedload(Post.media)
        ).first()

        if not post:
            db.close()
            return {
                "status": "error",
                "error": "Post not found"
            }

        # Get user info
        user = post.user

        # Get media URLs
        media_urls = [m.media_url for m in post.media]

        # Get engagement stats
        like_count = db.query(Like).filter(Like.post_id == post_id).count()
        comment_count = db.query(Comment).filter(Comment.post_id == post_id).count()

        # Check if user has liked this post (if user_id provided)
        liked_by_user = False
        if user_id:
            liked = db.query(Like).filter(
                Like.post_id == post_id,
                Like.user_id == user_id
            ).first()
            liked_by_user = liked is not None

        # Build response
        post_data = {
            "status": "success",
            "post_id": post.id,
            "user_id": post.user_id,
            "username": user.username if user else "unknown",
            "name": user.name if user else "Unknown",
            "profile_image": user.profile_image if user else None,
            "title": post.title,
            "caption": post.caption,
            "location": post.location,
            "ai_sentence": post.ai_sentence,
            "media_urls": media_urls,
            "created_at": post.created_at.isoformat() if post.created_at else None,
            # Actor info (same as user for posts)
            "actor_id": post.user_id,
            "actor_username": user.username if user else "unknown",
            "actor_name": user.name if user else "Unknown",
            "actor_profile_image": user.profile_image if user else None,
            # Engagement
            "like_count": like_count,
            "comment_count": comment_count,
            "liked_by_user": liked_by_user
        }

        db.close()

        logger.info(f"✅ Retrieved post {post_id}")

        return post_data

    except Exception as e:
        logger.error(f"❌ Error getting post {post_id}: {e}")
        return {
            "status": "error",
            "error": str(e)
        }


@app.get("/images/batch")
async def get_images_batch(offset: int = 0, limit: int = 5):
    """
    Fetch a batch of unique post images from Firebase Storage.
    Returns Firebase Storage URLs for iOS to load images progressively.

    Query params:
    - offset: Starting position (default 0)
    - limit: Number of images to return (default 5, max 20)

    Returns:
    - Array of unique image URLs from post_media table
    """
    from database.models import PostMedia
    from sqlalchemy import desc

    try:
        db = SessionLocal()

        # Limit max to 20 images per request
        limit = min(limit, 20)

        # Get unique images from post_media, ordered by creation time (newest first)
        images = db.query(PostMedia.media_url, PostMedia.id, PostMedia.created_at).order_by(
            desc(PostMedia.created_at)
        ).limit(limit).offset(offset).all()

        # Build response
        image_list = []
        for img in images:
            image_list.append({
                "id": img.id,
                "url": img.media_url,  # Firebase Storage URL
                "created_at": img.created_at.isoformat() if img.created_at else None
            })

        db.close()

        logger.info(f"✅ Fetched {len(image_list)} images (offset: {offset}, limit: {limit})")

        return {
            "status": "success",
            "images": image_list,
            "count": len(image_list),
            "offset": offset,
            "limit": limit
        }

    except Exception as e:
        logger.error(f"❌ Error fetching images batch: {e}")
        return {
            "status": "error",
            "error": str(e)
        }


@app.get("/post/status/{redis_id}")
async def poll_post_status(redis_id: str):
    """
    Poll endpoint for iOS to check post creation status.

    Returns:
    - status: "processing" | "saving" | "notifying" | "posted" | "error"
    - message: Human readable status message
    - post_id: Available when status = "posted"
    """
    try:
        status_key = f"post_status:{redis_id}"
        status_data_str = r.get(status_key)

        if not status_data_str:
            return {
                "status": "not_found",
                "message": "Post status not found or expired"
            }

        status_data = json.loads(status_data_str)

        logger.info(f"📊 Post status poll: {status_data}")

        return status_data

    except Exception as e:
        logger.error(f"Error polling post status: {str(e)}")
        return {
            "status": "error",
            "message": str(e)
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

# Pydantic model for design creation request
class DesignCreate(BaseModel):
    user_id: str
    two_captions: List[str]
    intro_caption: str
    eight_captions: List[str]
    design_name: str
    song: str

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

@app.post("/user/pushEra")
async def push_era(era_data: EraPush):
    """
    Post a new era to the eras table (feed/notifications table).
    Called when user clicks "Push This Era" in iOS.

    Request body:
    {
        "user_id": "uuid-string",
        "era_text": "archita is entering her law school era..."
    }

    Returns:
        Success status and era post
    """
    db = SessionLocal()
    try:
        # Find the user
        user = db.query(User).filter(User.id == era_data.user_id).first()

        if not user:
            return {
                "status": "error",
                "message": "User not found"
            }

        # Create new era post in eras table
        new_era = Notification(
            user_id=era_data.user_id,
            content=era_data.era_text
        )

        db.add(new_era)
        db.commit()
        db.refresh(new_era)

        logger.info(f"✅ Posted era for user {era_data.user_id}: {era_data.era_text[:50]}...")

        # Send push notifications to all followers
        from push_notifications import send_era_notification

        # Get all followers of this user
        followers = db.query(Follow).filter(Follow.following_id == era_data.user_id).all()

        logger.info(f"📢 Notifying {len(followers)} followers about new era")

        for follow in followers:
            # Get the follower's info
            follower = db.query(User).filter(User.id == follow.follower_id).first()

            if follower and follower.device_token:
                try:
                    await send_era_notification(
                        device_token=follower.device_token,
                        poster_name=user.name,
                        era_content=era_data.era_text
                    )
                    logger.info(f"✅ Sent era notification to {follower.name}")
                except Exception as e:
                    logger.error(f"❌ Failed to send era notification to {follower.name}: {e}")
            else:
                logger.debug(f"⚠️  Skipping notification for {follower.name if follower else 'unknown'} (no device token)")

        return {
            "status": "success",
            "era_id": new_era.id,
            "user_id": era_data.user_id,
            "content": era_data.era_text,
            "created_at": new_era.created_at.isoformat(),
            "message": "Era posted successfully",
            "notifications_sent": sum(1 for f in followers if db.query(User).filter(User.id == f.follower_id).first() and db.query(User).filter(User.id == f.follower_id).first().device_token)
        }

    except Exception as e:
        logger.error(f"Error posting era for user {era_data.user_id}: {e}")
        db.rollback()
        return {
            "status": "error",
            "error": str(e)
        }
    finally:
        db.close()

@app.post("/design/create")
async def create_design(design_data: DesignCreate):
    """
    Create a new design for a user and save it to the designs table.

    Request body:
    {
        "user_id": "uuid-string",
        "two_captions": ["caption1", "caption2"],
        "intro_caption": "introducing mademoiselle archita 🌸",
        "eight_captions": ["caption1", "caption2", ..., "caption8"],
        "design_name": "design name",
        "song": "song name or URL"
    }

    Returns:
        Design ID and success status
    """
    db = SessionLocal()
    try:
        # Verify user exists
        user = db.query(User).filter(User.id == design_data.user_id).first()
        if not user:
            return {
                "status": "error",
                "message": f"User with ID {design_data.user_id} not found"
            }

        # Create new design
        new_design = Design(
            user_id=design_data.user_id,
            two_captions=design_data.two_captions,
            intro_caption=design_data.intro_caption,
            eight_captions=design_data.eight_captions,
            design_name=design_data.design_name,
            song=design_data.song
        )

        db.add(new_design)
        db.commit()
        db.refresh(new_design)

        logger.info(f"✅ Created design {new_design.id} for user {design_data.user_id}")

        return {
            "status": "success",
            "design_id": new_design.id,
            "user_id": design_data.user_id,
            "message": "Design created successfully"
        }

    except Exception as e:
        logger.error(f"Error creating design: {e}")
        db.rollback()
        return {
            "status": "error",
            "error": str(e)
        }
    finally:
        db.close()

@app.get("/design/{user_id}")
async def get_user_designs(user_id: str):
    """
    Get all designs for a user, ordered by most recent first.

    Args:
        user_id: The user's ID

    Returns:
        List of all designs for this user
    """
    db = SessionLocal()
    try:
        # Get all designs for this user
        designs = db.query(Design).filter(
            Design.user_id == user_id
        ).order_by(Design.created_at.desc()).all()

        designs_list = []
        for design in designs:
            designs_list.append({
                "id": design.id,
                "two_captions": design.two_captions,
                "intro_caption": design.intro_caption,
                "eight_captions": design.eight_captions,
                "design_name": design.design_name,
                "song": design.song,
                "created_at": design.created_at.isoformat()
            })

        return {
            "status": "success",
            "user_id": user_id,
            "count": len(designs_list),
            "designs": designs_list
        }

    except Exception as e:
        logger.error(f"Error fetching designs for {user_id}: {e}")
        return {
            "status": "error",
            "error": str(e)
        }
    finally:
        db.close()

@app.get("/debug/all-sessions")
async def get_all_sessions():
    """
    Debug endpoint: Get ALL Redis session keys and their contents.
    Returns a list of all sessions with their data.
    """
    try:
        # Get all session keys
        keys = r.keys("session:*")

        if not keys:
            return {
                "status": "no_sessions",
                "message": "No sessions found in Redis",
                "total": 0,
                "sessions": []
            }

        # Get data for all sessions
        all_sessions = []
        for key in keys:
            key_str = key.decode() if isinstance(key, bytes) else key
            session_data_str = r.get(key_str)

            if session_data_str:
                try:
                    session_data = json.loads(session_data_str)
                    all_sessions.append({
                        "session_id": key_str.replace("session:", ""),
                        "full_key": key_str,
                        "analyze_button_pressed": session_data.get("analyze_button_pressed", False),
                        "has_user_id": "user_id" in session_data,
                        "signup_data": session_data.get("signup_data", {}),
                        "full_data": session_data
                    })
                except json.JSONDecodeError:
                    all_sessions.append({
                        "session_id": key_str.replace("session:", ""),
                        "full_key": key_str,
                        "error": "Failed to parse JSON"
                    })

        return {
            "status": "success",
            "total": len(all_sessions),
            "sessions": all_sessions
        }

    except Exception as e:
        logger.error(f"Error fetching all sessions: {e}")
        return {
            "status": "error",
            "error": str(e)
        }

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
        prompt = f"""Generate a SHORT sentence explaining how these two people might know each other based on their bios.

{user_a_name}'s bio: {user_a_bio if user_a_bio else "No bio"}
{user_b_name}'s bio: {user_b_bio if user_b_bio else "No bio"}

RULES:
- lowercase only
- SHORT (3-8 words max)
- casual, gen-z tone
- infer connection by saying "probably", "might" through: school, work, hobbies, location, interests.
- if they share a school, mention it (e.g., "both at cornell", "met thru stanford")
- if no clear connection, 
 

Examples:
"knows {user_a_name} thru cornell"
"also another cornellian #gobigred"
"her brother lmao"
"met {user_a_name} through design twitter"
"knows {user_a_name} because of stanford cs majors unite"
"knows {user_a_name} thru the nyc creative scene"

Return ONE short sentence, lowercase, no quotes."""

        client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=30,
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
    from push_notifications import send_follow_request_notification

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
            from push_notifications import send_new_follower_notification
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
    from push_notifications import send_follow_accepted_notification

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
    - All posts and media
    - Designs
    - Follow relationships (followers and following)
    - Follow requests (sent and received)
    - Notifications (received and triggered)
    - Likes
    - Pinecone embeddings

    Args:
        user_id: The user's ID

    Returns:
        Success/error status
    """
    from profile_embeddings import index as pinecone_index

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

        # 2. Delete likes by this user
        likes_count = db.query(Like).filter(Like.user_id == user_id).delete()
        logger.info(f"✅ Deleted {likes_count} likes")

        # 3. Delete notifications (received and triggered)
        notifs_received = db.query(Notification).filter(Notification.user_id == user_id).delete()
        notifs_triggered = db.query(Notification).filter(Notification.actor_id == user_id).delete()
        logger.info(f"✅ Deleted {notifs_received} notifications received, {notifs_triggered} notifications triggered")

        # 4. Delete follow requests (sent and received)
        requests_sent = db.query(FollowRequest).filter(FollowRequest.requester_id == user_id).delete()
        requests_received = db.query(FollowRequest).filter(FollowRequest.requested_id == user_id).delete()
        logger.info(f"✅ Deleted {requests_sent} follow requests sent, {requests_received} follow requests received")

        # 5. Delete follow relationships (as follower and following)
        follows_as_follower = db.query(Follow).filter(Follow.follower_id == user_id).delete()
        follows_as_following = db.query(Follow).filter(Follow.following_id == user_id).delete()
        logger.info(f"✅ Deleted {follows_as_follower} follows (as follower), {follows_as_following} follows (as following)")

        # 6. Delete designs
        designs_count = db.query(Design).filter(Design.user_id == user_id).delete()
        logger.info(f"✅ Deleted {designs_count} designs")

        # 7. Delete posts (PostMedia will cascade delete automatically)
        posts_count = db.query(Post).filter(Post.user_id == user_id).delete()
        logger.info(f"✅ Deleted {posts_count} posts (and associated media)")

        # 8. Delete user
        db.delete(user)
        db.commit()

        logger.info(f"✅ Successfully deleted account for user {user_id} ({user.username})")

        return {
            "status": "success",
            "message": "Account deleted successfully",
            "deleted": {
                "likes": likes_count,
                "notifications_received": notifs_received,
                "notifications_triggered": notifs_triggered,
                "follow_requests_sent": requests_sent,
                "follow_requests_received": requests_received,
                "follows_as_follower": follows_as_follower,
                "follows_as_following": follows_as_following,
                "designs": designs_count,
                "posts": posts_count
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

class ReportRequest(BaseModel):
    post_id: str
    reporter_id: str
    reason: str

@app.post("/report/post")
async def report_post(report_data: ReportRequest):
    """
    Report a post for objectionable content.

    Request body:
    {
        "post_id": "post_id",
        "reporter_id": "user_id_who_is_reporting",
        "reason": "Why this content is inappropriate"
    }

    Returns:
        Success/error status
    """
    db = SessionLocal()
    try:
        # Check if post exists
        post = db.query(Post).filter(Post.id == report_data.post_id).first()
        if not post:
            return {
                "status": "error",
                "message": "Post not found"
            }

        # Check if reporter exists
        reporter = db.query(User).filter(User.id == report_data.reporter_id).first()
        if not reporter:
            return {
                "status": "error",
                "message": "Reporter user not found"
            }

        # Check if already reported by this user
        existing_report = db.query(Report).filter(
            Report.post_id == report_data.post_id,
            Report.reporter_id == report_data.reporter_id
        ).first()

        if existing_report:
            return {
                "status": "error",
                "message": "You have already reported this post"
            }

        # Create report
        new_report = Report(
            post_id=report_data.post_id,
            reported_user_id=post.user_id,  # User who created the post
            reporter_id=report_data.reporter_id,
            reason=report_data.reason
        )

        db.add(new_report)
        db.commit()
        db.refresh(new_report)

        logger.info(f"🚨 Post {report_data.post_id} reported by user {report_data.reporter_id}. Reason: {report_data.reason}")

        return {
            "status": "success",
            "message": "Report submitted successfully",
            "report_id": new_report.id
        }

    except Exception as e:
        logger.error(f"❌ Error reporting post: {e}")
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

class CommentCreate(BaseModel):
    user_id: str
    content: str

@app.post("/post/{post_id}/comment")
async def create_comment(post_id: str, comment_data: CommentCreate):
    """
    Add a comment to a post.

    Request body:
    {
        "user_id": "user_id_commenting",
        "content": "This is a comment"
    }

    Returns:
        Success/error status with comment details
    """
    db = SessionLocal()
    try:
        # Check if post exists
        post = db.query(Post).filter(Post.id == post_id).first()
        if not post:
            return {
                "status": "error",
                "message": "Post not found"
            }

        # Check if user exists
        user = db.query(User).filter(User.id == comment_data.user_id).first()
        if not user:
            return {
                "status": "error",
                "message": "User not found"
            }

        # Create comment
        new_comment = Comment(
            post_id=post_id,
            user_id=comment_data.user_id,
            content=comment_data.content
        )

        db.add(new_comment)
        db.commit()
        db.refresh(new_comment)

        logger.info(f"💬 User {comment_data.user_id} commented on post {post_id}")

        return {
            "status": "success",
            "message": "Comment added successfully",
            "comment": {
                "comment_id": new_comment.id,
                "post_id": post_id,
                "user_id": new_comment.user_id,
                "username": user.username,
                "name": user.name,
                "profile_image": user.profile_image,
                "content": new_comment.content,
                "created_at": new_comment.created_at.isoformat()
            }
        }

    except Exception as e:
        logger.error(f"❌ Error creating comment: {e}")
        db.rollback()
        return {
            "status": "error",
            "error": str(e)
        }
    finally:
        db.close()

@app.get("/post/{post_id}/comments")
async def get_comments(post_id: str, limit: int = 50, offset: int = 0):
    """
    Get all comments for a post.

    Query params:
    - post_id: ID of the post
    - limit: Max comments to return (default 50)
    - offset: Pagination offset (default 0)

    Returns:
        List of comments with user info
    """
    db = SessionLocal()
    try:
        # Check if post exists
        post = db.query(Post).filter(Post.id == post_id).first()
        if not post:
            return {
                "status": "error",
                "message": "Post not found"
            }

        # Get comments ordered by creation time (newest first)
        comments = db.query(Comment).filter(
            Comment.post_id == post_id
        ).order_by(Comment.created_at.desc()).limit(limit).offset(offset).all()

        # Format results with user info
        results = []
        for comment in comments:
            user = db.query(User).filter(User.id == comment.user_id).first()
            results.append({
                "comment_id": comment.id,
                "user_id": comment.user_id,
                "username": user.username if user else "unknown",
                "name": user.name if user else "Unknown",
                "profile_image": user.profile_image if user else None,
                "content": comment.content,
                "created_at": comment.created_at.isoformat()
            })

        return {
            "status": "success",
            "post_id": post_id,
            "count": len(results),
            "comments": results
        }

    except Exception as e:
        logger.error(f"❌ Error getting comments: {e}")
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
            # Return own profile with latest design
            latest_design = db.query(Design).filter(
                Design.user_id == profile_id
            ).order_by(Design.created_at.desc()).first()

            return {
                "status": "success",
                "follow_status": "own_profile",
                "user": {
                    "id": profile_user.id,
                    "username": profile_user.username,
                    "name": profile_user.name,
                    "university": profile_user.university,
                    "occupation": profile_user.occupation
                },
                "design": {
                    "id": latest_design.id,
                    "two_captions": latest_design.two_captions,
                    "intro_caption": latest_design.intro_caption,
                    "eight_captions": latest_design.eight_captions,
                    "design_name": latest_design.design_name,
                    "song": latest_design.song,
                    "created_at": latest_design.created_at.isoformat()
                } if latest_design else None
            }

        # Check if profile is PUBLIC
        if not profile_user.is_private:
            # Public profile - show full profile with design regardless of follow status
            latest_design = db.query(Design).filter(
                Design.user_id == profile_id
            ).order_by(Design.created_at.desc()).first()

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
                },
                "design": {
                    "id": latest_design.id,
                    "two_captions": latest_design.two_captions,
                    "intro_caption": latest_design.intro_caption,
                    "eight_captions": latest_design.eight_captions,
                    "design_name": latest_design.design_name,
                    "song": latest_design.song,
                    "created_at": latest_design.created_at.isoformat()
                } if latest_design else None
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
            # Viewer follows this profile - show full profile with design
            latest_design = db.query(Design).filter(
                Design.user_id == profile_id
            ).order_by(Design.created_at.desc()).first()

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
                },
                "design": {
                    "id": latest_design.id,
                    "two_captions": latest_design.two_captions,
                    "intro_caption": latest_design.intro_caption,
                    "eight_captions": latest_design.eight_captions,
                    "design_name": latest_design.design_name,
                    "song": latest_design.song,
                    "created_at": latest_design.created_at.isoformat()
                } if latest_design else None
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
        from redis_client import r
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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("stream:app", host="0.0.0.0", port=8000, reload=True)

