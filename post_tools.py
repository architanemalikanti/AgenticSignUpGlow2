"""
Tools for creating and managing posts.
"""

from langchain_core.tools import tool
from database.db import SessionLocal
from database.models import Post, PostMedia, User, Follow
from datetime import datetime
import json
import logging
import os
import uuid
import asyncio
from anthropic import Anthropic
from dotenv import load_dotenv
from redis_client import r

load_dotenv()

logger = logging.getLogger(__name__)


@tool
def generate_post_captions(conversation_history: str) -> str:
    """
    Generate title, caption, and location for a post based on the conversation.

    Args:
        conversation_history: The full conversation text about what the user wants to post

    Returns:
        JSON string with title, caption, and location
    """
    try:
        client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

        prompt = f"""Based on this conversation about a post, generate an iconic social media post:

Conversation:
{conversation_history}

Generate a JSON response with:
1. "title": A short, catchy, iconic title (2-4 words, capitalize each word)
2. "caption": A fun, casual caption in lowercase gen-z style (15-30 words, can use emojis)
3. "location": Extract or infer the location mentioned (single word or short phrase, lowercase). If no location mentioned, set to null.

Requirements:
- Title should be memorable and aesthetic
- Caption should feel authentic and casual
- Location should be concise (or null if not mentioned)
- Return ONLY valid JSON, no other text

Example output format:
{{
  "title": "Summer Nights",
  "caption": "living for these warm evenings with good vibes and even better company 🌙✨",
  "location": "rooftop"
}}"""

        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}]
        )

        response_text = response.content[0].text.strip()

        # Remove markdown code blocks if present
        if response_text.startswith("```"):
            response_text = response_text.split("```")[1]
            if response_text.startswith("json"):
                response_text = response_text[4:]

        # Parse and validate JSON
        result = json.loads(response_text.strip())

        if not all(key in result for key in ["title", "caption"]):
            return json.dumps({"error": "Missing required fields (title, caption)"})

        logger.info(f"✅ Generated post captions: {result}")

        return json.dumps(result)

    except Exception as e:
        logger.error(f"❌ Error generating post captions: {e}")
        return json.dumps({"error": str(e)})


async def create_post_from_conversation(redis_id: str, user_id: str, thread_id: str, media_urls: str, db_path: str):
    """
    Background task to generate captions from conversation, create post, and notify followers.
    """
    try:
        # Get conversation history
        from langchain_core.messages import trim_messages
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
        thread = {"configurable": {"thread_id": thread_id}}

        # Open checkpointer to get conversation history
        async with AsyncSqliteSaver.from_conn_string(db_path) as checkpointer:
            # Get state from checkpointer
            state = await checkpointer.aget(thread)

            if not state:
                raise Exception("No conversation history found - state is None")

            # State contains channel_values which has the messages
            if 'channel_values' not in state:
                raise Exception(f"No channel_values in state. Keys: {list(state.keys())}")

            channel_values = state['channel_values']

            if 'messages' not in channel_values:
                raise Exception(f"No messages in channel_values. Keys: {list(channel_values.keys())}")

            conversation_messages = channel_values["messages"]
            logger.info(f"✅ Got {len(conversation_messages)} messages from conversation")

        # Don't trim - just use all messages (or limit to last N if needed)
        # trim_messages requires token_counter which is complex to set up
        # For now, just use the last 10 messages to avoid token issues
        trimmed_messages = conversation_messages[-10:] if len(conversation_messages) > 10 else conversation_messages

        # Generate captions from conversation
        from langchain_anthropic import ChatAnthropic
        import os
        caption_model = ChatAnthropic(model="claude-sonnet-4-5-20250929", api_key=os.getenv("ANTHROPIC_API_KEY"))

        prompt = """Based on this conversation about a social media post, generate:
1. A short title (3-5 words)
2. A caption (1-2 sentences, casual gen-z vibe)
3. A location (if mentioned, otherwise null)

Return ONLY valid JSON with no other text: {"title": "...", "caption": "...", "location": "..." or null}"""

        result = caption_model.invoke([{"role": "user", "content": f"{prompt}\n\nConversation:\n{trimmed_messages}"}])

        # Extract JSON from response (in case AI adds extra text)
        content = result.content
        logger.info(f"🔍 AI response: {content}")

        # Try to find JSON in the response
        try:
            # If content is a list (tool use), get text
            if isinstance(content, list):
                content = content[0].get("text", "") if content else ""

            # Find JSON block
            if "{" in content:
                start = content.find("{")
                end = content.rfind("}") + 1
                json_str = content[start:end]
                captions = json.loads(json_str)
            else:
                raise ValueError("No JSON found in response")
        except Exception as e:
            logger.error(f"❌ Failed to parse captions: {e}, Content: {content}")
            # Fallback to simple caption
            captions = {
                "title": "New Post",
                "caption": "Check out my latest post!",
                "location": None
            }

        logger.info(f"✅ Generated captions: {captions}")

        # Now create the post
        await create_post_in_background(
            redis_id, user_id,
            captions.get("title", ""),
            captions.get("caption", ""),
            captions.get("location"),
            media_urls
        )

    except Exception as e:
        logger.error(f"❌ Error in create_post_from_conversation: {e}")
        r.set(f"post_status:{redis_id}", json.dumps({
            "status": "error",
            "message": str(e)
        }), ex=300)


async def create_post_in_background(redis_id: str, user_id: str, title: str, caption: str, location: str, media_urls: str):
    """
    Background task to create post, save media, and notify followers.
    Updates Redis with status as it progresses.
    """
    try:
        # Keep status as processing while we work
        # (No need to update repeatedly)

        db = SessionLocal()

        # Create the post
        new_post = Post(
            user_id=user_id,
            title=title,
            caption=caption,
            location=location if location and location.lower() != "null" else None,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )

        db.add(new_post)
        db.commit()
        db.refresh(new_post)

        post_id = new_post.id
        logger.info(f"✅ Created post {post_id} for user {user_id}")

        # Add media if provided
        if media_urls:
            try:
                urls_list = json.loads(media_urls) if isinstance(media_urls, str) else media_urls

                for media_url in urls_list:
                    post_media = PostMedia(
                        post_id=post_id,
                        media_url=media_url,
                        created_at=datetime.utcnow()
                    )
                    db.add(post_media)

                db.commit()
                logger.info(f"✅ Added {len(urls_list)} media items to post {post_id}")

            except Exception as media_error:
                logger.error(f"⚠️ Error adding media: {media_error}")

        # Still processing (notifying followers)
        # Will update to "posted" when completely done

        # Notify followers about the new post
        try:
            followers = db.query(Follow).filter(Follow.following_id == user_id).all()
            follower_ids = [f.follower_id for f in followers]

            poster = db.query(User).filter(User.id == user_id).first()
            poster_name = poster.name if poster else "Someone"

            if follower_ids:
                from push_notifications import send_push_notification

                for follower_id in follower_ids:
                    follower = db.query(User).filter(User.id == follower_id).first()
                    if follower and follower.device_token:
                        try:
                            await send_push_notification(
                                device_token=follower.device_token,
                                title=f"{poster_name} posted",
                                body=title or caption[:50] + "..." if len(caption) > 50 else caption,
                                badge=1,
                                data={
                                    "type": "new_post",
                                    "post_id": post_id,
                                    "user_id": user_id,
                                    "username": poster.username
                                }
                            )
                        except Exception as notif_error:
                            logger.warning(f"⚠️ Failed to notify follower {follower_id}: {notif_error}")

                logger.info(f"✅ Sent notifications to {len(follower_ids)} followers")

        except Exception as notif_error:
            logger.warning(f"⚠️ Error notifying followers: {notif_error}")

        db.close()

        # Update status: POSTED!
        r.set(f"post_status:{redis_id}", json.dumps({
            "status": "posted",
            "message": "post is live!",
            "post_id": post_id
        }), ex=3600)  # Keep for 1 hour

        logger.info(f"🎉 Post {post_id} fully completed!")

    except Exception as e:
        logger.error(f"❌ Error in background post creation: {e}")
        # Update status to error
        r.set(f"post_status:{redis_id}", json.dumps({
            "status": "error",
            "message": str(e)
        }), ex=300)


@tool
def save_post(user_id: str, title: str, caption: str, location: str = None, media_urls: str = None) -> str:
    """
    Initiate post creation in the background.
    Returns immediately with a redis_id that iOS can poll for status.

    Args:
        user_id: The ID of the user creating the post
        title: Post title
        caption: Post caption
        location: Optional location (can be null/empty)
        media_urls: JSON string of media URLs (base64 encoded images)

    Returns:
        JSON string with redis_id for polling
    """
    try:
        # Generate unique redis_id
        redis_id = str(uuid.uuid4())

        # Set initial status in Redis
        r.set(f"post_status:{redis_id}", json.dumps({
            "status": "processing",
            "message": "starting post creation..."
        }), ex=300)  # 5 min expiry

        # Start background task
        asyncio.create_task(
            create_post_in_background(redis_id, user_id, title, caption, location, media_urls)
        )

        logger.info(f"✅ Started background post creation with redis_id: {redis_id}")

        return json.dumps({
            "success": True,
            "redis_id": redis_id,
            "message": "Post creation started!"
        })

    except Exception as e:
        logger.error(f"❌ Error initiating post creation: {e}")
        return json.dumps({
            "success": False,
            "error": str(e)
        })
