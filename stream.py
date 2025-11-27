from dotenv import load_dotenv
import os, asyncio, json, logging, uuid
from pathlib import Path
from langchain_core.messages import HumanMessage
from langchain_anthropic import ChatAnthropic
from langchain_openai import ChatOpenAI
from langchain_community.tools.tavily_search import TavilySearchResults
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from fastapi import FastAPI, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List, Optional
from database.db import SessionLocal
from database.models import User, Design, Follow, FollowRequest, Era
from agent import Agent
from prompt_manager import set_prompt
from redis_client import r
from aioapns import APNs, NotificationRequest

# Load .env from the same directory as this script
load_dotenv(Path(__file__).parent / ".env")

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

    async def event_gen():
        # Build the system prompt
        post_prompt = f"""You are a friendly assistant helping users create social media posts.
Normally when you post on Instagram, the user clicks a button to post. But in the case of Glow, the user 
will upload their images and give a short description of what they wanna post. 

Your main goal after they put a message of their images and short description is to get them to confirm they want to post it. 
"are we ready to post now?": keep confirming this after every message until they say yes. 
When the user confirms they want to post (e.g., "post it", "yes post this", "let's go", "ready to post"),
respond with EXACTLY: "posting now!"

Use lowercase, gen-z vibe."""

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
async def get_user_feed(user_id: str, limit: int = 20, offset: int = 0):
    """
    Get posts for a user's feed.
    Returns posts from users they follow, ordered by creation time (newest first).

    Query params:
    - user_id: ID of the user viewing the feed
    - limit: Number of posts to return (default 20)
    - offset: Offset for pagination (default 0)
    """
    from database.models import Post, PostMedia
    from sqlalchemy import desc

    try:
        db = SessionLocal()

        # Get list of users this user follows
        following = db.query(Follow.following_id).filter(Follow.follower_id == user_id).all()
        following_ids = [f[0] for f in following]

        # Add user's own ID to see their own posts (like Instagram)
        following_ids.append(user_id)

        # Get posts from followed users + own posts
        posts_query = db.query(Post).filter(
            Post.user_id.in_(following_ids)
        ).order_by(desc(Post.created_at)).limit(limit).offset(offset)

        posts = posts_query.all()

        # Build response with post data and media
        feed_posts = []
        for post in posts:
            # Get user info
            user = db.query(User).filter(User.id == post.user_id).first()

            # Get media for this post
            media = db.query(PostMedia).filter(PostMedia.post_id == post.id).all()
            media_urls = [m.media_url for m in media]

            feed_posts.append({
                "post_id": post.id,
                "user_id": post.user_id,
                "username": user.username if user else "unknown",
                "name": user.name if user else "Unknown",
                "title": post.title,
                "caption": post.caption,
                "location": post.location,
                "media_urls": media_urls,
                "created_at": post.created_at.isoformat() if post.created_at else None,
                # Actor is the person who created the post
                "actor_id": post.user_id,
                "actor_username": user.username if user else "unknown",
                "actor_name": user.name if user else "Unknown",
                "actor_profile_image": user.profile_image if user else None
            })

        db.close()

        logger.info(f"✅ Retrieved {len(feed_posts)} posts for user {user_id}'s feed")

        return {
            "status": "success",
            "posts": feed_posts,
            "total": len(feed_posts)
        }

    except Exception as e:
        logger.error(f"❌ Error getting feed: {e}")
        return {
            "status": "error",
            "error": str(e)
        }


@app.get("/posts/user/{user_id}")
async def get_user_posts(user_id: str, limit: int = 20, offset: int = 0):
    """
    Get all posts by a specific user.

    Query params:
    - user_id: ID of the user whose posts to retrieve
    - limit: Number of posts to return (default 20)
    - offset: Offset for pagination (default 0)
    """
    from database.models import Post, PostMedia
    from sqlalchemy import desc

    try:
        db = SessionLocal()

        # Get posts by this user
        posts_query = db.query(Post).filter(
            Post.user_id == user_id
        ).order_by(desc(Post.created_at)).limit(limit).offset(offset)

        posts = posts_query.all()

        # Get user info
        user = db.query(User).filter(User.id == user_id).first()

        # Build response with post data and media
        user_posts = []
        for post in posts:
            # Get media for this post
            media = db.query(PostMedia).filter(PostMedia.post_id == post.id).all()
            media_urls = [m.media_url for m in media]

            user_posts.append({
                "post_id": post.id,
                "caption": post.caption,
                "post_media": media_urls,  # Array of 1-10 image URLs
                "created_at": post.created_at.isoformat() if post.created_at else None,
                # Actor is the person who created the post
                "actor_id": user_id,
                "actor_username": user.username if user else "unknown",
                "actor_name": user.name if user else "Unknown",
                "actor_profile_image": user.profile_image if user else None
            })

        db.close()

        logger.info(f"✅ Retrieved {len(user_posts)} posts for user {user_id}")

        return {
            "status": "success",
            "user_id": user_id,
            "username": user.username if user else "unknown",
            "name": user.name if user else "Unknown",
            "posts": user_posts
        }

    except Exception as e:
        logger.error(f"❌ Error getting user posts: {e}")
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
            # User ID is ready! Return user_id, JWT tokens, and profile image
            return {
                "status": "ready",
                "user_id": user_id,
                "access_token": session_data.get("access_token"),
                "refresh_token": session_data.get("refresh_token"),
                "profile_image": session_data.get("profile_image"),
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
async def search_users(query: str = Query(..., min_length=1)):
    """
    Search for users by username or name.
    Returns top 5 matching results.

    Args:
        query: Search string (username or name)

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

        # Query database for users matching username or name
        # Using ilike for case-insensitive partial matching
        matching_users = db.query(User).filter(
            (User.username.ilike(f"%{search_term}%")) |
            (User.name.ilike(f"%{search_term}%"))
        ).limit(5).all()

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
        new_era = Era(
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

@app.post("/follow/request")
async def send_follow_request(request_data: FollowRequestCreate):
    """
    User A sends a follow request to User B.
    Since all profiles are private, this creates a pending request.

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

        # Check if request already exists
        existing_request = db.query(FollowRequest).filter(
            FollowRequest.requester_id == request_data.requester_id,
            FollowRequest.requested_id == request_data.requested_id
        ).first()

        if existing_request:
            return {
                "status": "error",
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

        # Create era notification for User B (the requested user)
        requester_name = requester.name if requester.name else requester.username
        era_notification = Era(
            user_id=request_data.requested_id,  # Notification belongs to User B
            actor_id=request_data.requester_id,  # The requester is the actor
            content=f"{requester_name} wants to follow you"
        )
        db.add(era_notification)
        db.commit()

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

        db.commit()

        logger.info(f"✅ User {request_data.requested_id} accepted follow from {request_data.requester_id}")

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
        era_notification = Era(
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
async def get_followers(user_id: str):
    """
    Get all users who follow this user (User B's followers).

    Args:
        user_id: The user's ID

    Returns:
        List of followers with their info
    """
    db = SessionLocal()
    try:
        # Get all follows where this user is being followed
        follows = db.query(Follow).filter(
            Follow.following_id == user_id
        ).all()

        # Get follower info
        results = []
        for follow in follows:
            follower = db.query(User).filter(User.id == follow.follower_id).first()
            if follower:
                results.append({
                    "user_id": follower.id,
                    "username": follower.username,
                    "name": follower.name,
                    "university": follower.university,
                    "occupation": follower.occupation,
                    "followed_at": follow.created_at.isoformat()
                })

        return {
            "status": "success",
            "user_id": user_id,
            "count": len(results),
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
async def get_following(user_id: str):
    """
    Get all users that this user follows (who User B is following).

    Args:
        user_id: The user's ID

    Returns:
        List of users they're following with their info
    """
    db = SessionLocal()
    try:
        # Get all follows where this user is the follower
        follows = db.query(Follow).filter(
            Follow.follower_id == user_id
        ).all()

        # Get following info
        results = []
        for follow in follows:
            following = db.query(User).filter(User.id == follow.following_id).first()
            if following:
                results.append({
                    "user_id": following.id,
                    "username": following.username,
                    "name": following.name,
                    "university": following.university,
                    "occupation": following.occupation,
                    "followed_at": follow.created_at.isoformat()
                })

        return {
            "status": "success",
            "user_id": user_id,
            "count": len(results),
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

@app.get("/eras/{user_id}")
@app.get("/notifications/{user_id}")  # Alias for iOS compatibility
async def get_feed(user_id: str):
    """
    Get eras feed for a user: eras from people they follow + their own notifications.

    Flow:
    1. Find who user follows
    2. Get all eras from followed users (ordered by time)
    3. Get user's own notifications (follow requests, follow accepts)
    4. Combine and sort by time (newest at bottom for scrolling)

    Args:
        user_id: Alice's user ID

    Returns:
        Combined feed of eras and notifications, sorted oldest to newest
    """
    db = SessionLocal()
    try:
        # 1. Find who this user follows
        follows = db.query(Follow).filter(
            Follow.follower_id == user_id
        ).all()

        followed_user_ids = [f.following_id for f in follows]

        # 2. Get all eras from followed users (their era posts)
        feed_items = []

        if followed_user_ids:
            eras_from_followed = db.query(Era).filter(
                Era.user_id.in_(followed_user_ids)
            ).order_by(Era.created_at.asc()).all()

            for era in eras_from_followed:
                poster = db.query(User).filter(User.id == era.user_id).first()

                era_item = {
                    "type": "era",
                    "id": era.id,
                    "user_id": era.user_id,
                    "username": poster.username if poster else "unknown",
                    "name": poster.name if poster else "Unknown",
                    "content": era.content,
                    "created_at": era.created_at.isoformat()
                }

                # Add actor_id - for eras from followed users, the actor is the poster
                # Use actor_id from database if it exists, otherwise use user_id (self-posted era)
                actor_id = era.actor_id if era.actor_id else era.user_id
                if poster:
                    era_item["actor_id"] = actor_id
                    era_item["actor_username"] = poster.username
                    era_item["actor_name"] = poster.name
                    era_item["actor_profile_image"] = poster.profile_image

                feed_items.append(era_item)

        # 3. Get user's own notifications (follow requests and accepts)
        user_notifications = db.query(Era).filter(
            Era.user_id == user_id
        ).order_by(Era.created_at.asc()).all()

        for notif in user_notifications:
            # Determine notification type based on content
            if "wants to follow you" in notif.content:
                notif_type = "follow_request"
            elif "accepted your follow request" in notif.content:
                notif_type = "follow_accept"
            else:
                notif_type = "notification"

            # Get actor details if actor_id exists
            actor_info = None
            if notif.actor_id:
                actor = db.query(User).filter(User.id == notif.actor_id).first()
                if actor:
                    actor_info = {
                        "actor_id": actor.id,
                        "actor_username": actor.username,
                        "actor_name": actor.name,
                        "actor_profile_image": actor.profile_image
                    }

            notification_item = {
                "id": notif.id,
                "type": notif_type,
                "user_id": notif.user_id,
                "content": notif.content,
                "created_at": notif.created_at.isoformat()
            }

            # Add actor info if available
            if actor_info:
                notification_item.update(actor_info)

            feed_items.append(notification_item)

        # 4. Sort all items by created_at (oldest to newest - bottom is newest)
        feed_items.sort(key=lambda x: x["created_at"])

        return {
            "status": "success",
            "user_id": user_id,
            "count": len(feed_items),
            "feed": feed_items
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

