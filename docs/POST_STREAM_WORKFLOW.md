# `/post/stream` Workflow Documentation

## Overview
The `/post/stream` endpoint handles a conversational post creation flow where users talk with an AI about their post, then the AI generates captions and creates the post.

---

## Request Structure

### HTTP Request
```
POST /post/stream?q={message}&user_id={id}&thread_id={id}&media_urls={json}
```

### Parameters
```python
q: str                    # User's message text
user_id: str             # UUID of user creating post
thread_id: str           # UUID for conversation memory (persists across messages)
media_urls: Optional[str] # JSON array of Firebase Storage URLs
```

### Example Request
```
POST /post/stream?q=party+vibes+tonight&user_id=abc123&thread_id=xyz789&media_urls=["https://firebase.com/img1.jpg","https://firebase.com/img2.jpg"]
```

---

## Phase 1: AI Conversation (Streaming)

### Step 1: Initialize Agent
```python
# stream.py:601
async_abot = Agent(
    model=primary_model,           # ChatAnthropic (claude-sonnet-4-5)
    tools=[],                       # EMPTY - no tools available
    system=post_prompt,             # System prompt defining behavior
    checkpointer=async_memory,      # SQLite memory for conversation
    fallback_model=fallback_model   # Optional OpenAI fallback
)
```

### Step 2: Create Message Object
```python
# stream.py:589
messages = [HumanMessage(content=q)]  # Just text, NO images sent to AI

# HumanMessage structure:
{
    "type": "human",
    "content": "party vibes tonight"  # User's text from query param
}
```

### Step 3: Thread Configuration
```python
# stream.py:590
thread = {"configurable": {"thread_id": thread_id}}

# This tells LangGraph to:
# - Load previous messages from SQLite checkpointer
# - Save new messages to same thread_id
# - Maintain conversation context across requests
```

### Step 4: Agent Graph Execution
```python
# stream.py:602
async for ev in async_abot.graph.astream_events({"messages": messages}, thread, version="v1"):
```

**Agent Graph Structure** (from `agent.py`):
```
┌─────────────┐
│   "llm"     │  ← Entry point: calls AI model
└──────┬──────┘
       │
       ▼
  ┌─────────┐
  │exists_  │  ← Checks if AI wants to call tools
  │action?  │
  └────┬────┘
       │
       ├─ True ──▶ "action" ──▶ back to "llm"  (loops for tool calls)
       │
       └─ False ─▶ END  (no tools → conversation ends)
```

**In this case**:
- No tools provided (`tools=[]`)
- `exists_action` always returns False
- Graph immediately goes: `llm` → `END`
- AI just responds conversationally

### Step 5: Stream AI Response
```python
# stream.py:604-628
if ev["event"] == "on_chat_model_stream":
    content = ev["data"]["chunk"].content

    # AI streams tokens like: "o", "k", "a", "y", " ", "a", "r", "e", ...
    full_response += content_str

    # Format for iOS (Server-Sent Events)
    content_block = {
        "content": [{
            "text": "okay are we ready to post now?",
            "type": "text",
            "index": 0
        }]
    }
    yield f"event: token\ndata: {json.dumps(content_block)}\n\n"
```

**Streaming Format** (Server-Sent Events):
```
event: token
data: {"content":[{"text":"o","type":"text","index":0}]}

event: token
data: {"content":[{"text":"k","type":"text","index":0}]}

event: token
data: {"content":[{"text":"ay","type":"text","index":0}]}

...
```

### Step 6: Detect "posting now!"
```python
# stream.py:631
if "posting now" in full_response.lower() and not post_initiated:
    post_initiated = True
    redis_id = str(uuid.uuid4())  # e.g., "a567d800-7069-4bdb-8c1e-9a5021cf550d"

    # Store status in Redis for polling
    r.set(f"post_status:{redis_id}", json.dumps({
        "status": "processing",
        "message": "starting post creation..."
    }), ex=300)  # Expires in 5 minutes
```

---

## Phase 2: Background Post Creation

### Step 7: Spawn Background Task
```python
# stream.py:643-647
from post_tools import create_post_from_conversation
asyncio.create_task(
    create_post_from_conversation(
        redis_id=redis_id,      # "a567d800-7069-4bdb-8c1e-9a5021cf550d"
        user_id=user_id,        # "abc123"
        thread_id=thread_id,    # "xyz789"
        media_urls=media_urls,  # '["https://firebase.com/img1.jpg"]'
        DB_PATH=DB_PATH         # "./checkpoints/memory.sqlite"
    )
)
```

**Important**: This runs **in parallel** with the AI finishing its response stream.

### Step 8: Retrieve Conversation History
```python
# post_tools.py:116-140
async with AsyncSqliteSaver.from_conn_string(db_path) as checkpointer:
    state = await checkpointer.aget(thread)
    conversation_messages = state['channel_values']['messages']

    # Trim to last 10 messages to avoid token limits
    trimmed_messages = conversation_messages[-10:]
```

**Message Structure in SQLite**:
```python
[
    {
        "type": "human",
        "content": "party vibes tonight"
    },
    {
        "type": "ai",
        "content": "okay are we ready to post now?"
    },
    {
        "type": "human",
        "content": "yes post it"
    },
    {
        "type": "ai",
        "content": "posting now!"
    }
]
```

### Step 9: Generate Captions with AI
```python
# post_tools.py:143-153
caption_model = ChatAnthropic(
    model="claude-sonnet-4-5-20250929",
    api_key=os.getenv("ANTHROPIC_API_KEY")
)

prompt = f"""Based on this conversation about a social media post, generate:
1. A short title (3-5 words): keep all lowercase letters, genz, third person. remember, the user's name is: {user_name}. make it like an instagram caption.
2. A instagram caption (1-2 sentences, casual gen-z vibe): keep all lowercase letters, third person. Make it sound like an instagram caption, and make it sound human...but in third person.
3. A location (if mentioned, otherwise null): keep all lowercase letters, and use acronyms if possible (nyc, sf, la, etc).
Return ONLY valid JSON with no other text: {{"title": "...", "caption": "...", "location": "..." or null}}"""

result = caption_model.invoke([{
    "role": "user",
    "content": f"{prompt}\n\nConversation:\n{trimmed_messages}"
}])
```

**AI Response**:
```json
{
    "title": "archita's city escape 🌆",
    "caption": "she said let's keep it chill in the city tonight. just vibes and good energy.",
    "location": "nyc"
}
```

### Step 10: Parse AI Response
```python
# post_tools.py:156-181
content = result.content  # Could be string or list

# Extract JSON from response
if "{" in content:
    start = content.find("{")
    end = content.rfind("}") + 1
    json_str = content[start:end]
    captions = json.loads(json_str)
else:
    # Fallback if parsing fails
    captions = {
        "title": "New Post",
        "caption": "Check out my latest post!",
        "location": None
    }
```

### Step 11: Create Post in Database
```python
# post_tools.py:185-191
await create_post_in_background(
    redis_id=redis_id,
    user_id=user_id,
    title="archita's city escape 🌆",
    caption="she said let's keep it chill in the city tonight...",
    location="nyc",
    media_urls='["https://firebase.com/img1.jpg","https://firebase.com/img2.jpg"]'
)
```

**Inside `create_post_in_background`** (post_tools.py:200-310):

#### 11a. Parse Media URLs
```python
# post_tools.py:217-221
media_list = json.loads(media_urls) if media_urls else []
# media_list = ["https://firebase.com/img1.jpg", "https://firebase.com/img2.jpg"]
```

#### 11b. Create Post Record
```python
# post_tools.py:223-232
from database.models import Post

new_post = Post(
    id=post_id,                    # UUID
    user_id=user_id,               # "abc123"
    title=title,                   # "archita's city escape 🌆"
    caption=caption,               # "she said let's keep it chill..."
    location=location,             # "nyc"
    created_at=datetime.utcnow()
)
db.add(new_post)
db.commit()
```

**Database Schema** (`database/models.py`):
```python
class Post(Base):
    __tablename__ = "posts"

    id = Column(String, primary_key=True)
    user_id = Column(String, ForeignKey("users.id"))
    title = Column(String)
    caption = Column(Text)
    location = Column(String, nullable=True)
    created_at = Column(DateTime)

    # Relationships
    user = relationship("User", back_populates="posts")
    media = relationship("PostMedia", back_populates="post")
```

#### 11c. Create Media Records
```python
# post_tools.py:234-244
from database.models import PostMedia

for media_url in media_list:
    media = PostMedia(
        id=str(uuid.uuid4()),
        post_id=post_id,
        media_url=media_url,  # "https://firebase.com/img1.jpg"
        media_type="image",
        created_at=datetime.utcnow()
    )
    db.add(media)

db.commit()
```

**Database Schema**:
```python
class PostMedia(Base):
    __tablename__ = "post_media"

    id = Column(String, primary_key=True)
    post_id = Column(String, ForeignKey("posts.id"))
    media_url = Column(String)         # Firebase Storage URL
    media_type = Column(String)        # "image" or "video"
    created_at = Column(DateTime)

    post = relationship("Post", back_populates="media")
```

### Step 12: Send Push Notifications
```python
# post_tools.py:260-310

# Get followers
follower_ids = db.query(Follow.follower_id).filter(
    Follow.following_id == user_id
).all()

for follower_id in follower_ids:
    follower = db.query(User).filter(User.id == follower_id).first()

    # Create notification record in DB
    notification = Notification(
        id=str(uuid.uuid4()),
        user_id=follower_id,
        actor_id=user_id,
        type="new_post",
        post_id=post_id,
        created_at=datetime.utcnow()
    )
    db.add(notification)

    # Send push notification if device token exists
    if follower.device_token:
        await send_push_notification(
            device_token=follower.device_token,
            title=f"{poster_name}: {title}",
            body=caption[:50] + "...",
            badge=1,
            data={
                "type": "new_post",
                "post_id": post_id,
                "user_id": user_id,
                "username": poster.username
            }
        )
```

**Notification Database Schema**:
```python
class Notification(Base):
    __tablename__ = "notifications"

    id = Column(String, primary_key=True)
    user_id = Column(String, ForeignKey("users.id"))  # Recipient
    actor_id = Column(String, ForeignKey("users.id")) # Who triggered it
    type = Column(String)         # "new_post", "follow_request", etc.
    post_id = Column(String, ForeignKey("posts.id"), nullable=True)
    created_at = Column(DateTime)
    read = Column(Boolean, default=False)
```

**APNs Payload Structure** (from `push_notifications.py`):
```python
{
    "aps": {
        "alert": {
            "title": "Archita: archita's city escape 🌆",
            "body": "she said let's keep it chill in the city tonight. ..."
        },
        "sound": "default",
        "badge": 1
    },
    "type": "new_post",
    "post_id": "f2812407-584e-4625-b0b6-a2201ffe2846",
    "user_id": "90f8a9e9-241f-4a0e-9b28-a04fa735bbca",
    "username": "archita"
}
```

**HTTP/2 Headers Sent to APNs**:
```
:method: POST
:scheme: https
:path: /3/device/7daf21cc6173c3359472...
host: api.push.apple.com
apns-id: <notification_id>
apns-topic: com.yourcompany.yourapp
apns-push-type: alert
apns-priority: 10
authorization: bearer <JWT_TOKEN>
```

### Step 13: Update Redis Status
```python
# post_tools.py:246-250
r.set(f"post_status:{redis_id}", json.dumps({
    "status": "posted",
    "message": "post is live!",
    "post_id": post_id
}), ex=300)
```

---

## Phase 3: Client Polling

### Step 14: AI Finishes Streaming
```python
# stream.py:704-709
yield "event: done\ndata: {}\n\n"

if post_initiated and redis_id:
    yield f"event: post_initiated\ndata: {json.dumps({'user_id': user_id, 'redis_id': redis_id})}\n\n"
```

**SSE Response Sequence**:
```
event: token
data: {"content":[{"text":"posting now!","type":"text","index":0}]}

event: done
data: {}

event: post_initiated
data: {"user_id":"abc123","redis_id":"a567d800-7069-4bdb-8c1e-9a5021cf550d"}
```

### Step 15: iOS App Polls Status
```swift
// iOS client receives post_initiated event
// Starts polling: GET /post/status/{redis_id}

// stream.py:925-956
@app.get("/post/status/{redis_id}")
async def get_post_status(redis_id: str):
    status_json = r.get(f"post_status:{redis_id}")
    if status_json:
        return json.loads(status_json)
    else:
        return {"status": "unknown", "message": "Status not found"}
```

**Polling Response Sequence**:
```json
// Poll 1 (0.5s after post_initiated)
{"status": "processing", "message": "starting post creation..."}

// Poll 2 (1.0s)
{"status": "processing", "message": "starting post creation..."}

// Poll 3 (1.5s)
{"status": "posted", "message": "post is live!", "post_id": "f2812407-584e..."}
```

---

## Data Flow Summary

```
┌─────────────────────────────────────────────────────────────────────┐
│ iOS App                                                             │
│                                                                     │
│ 1. User uploads images → Firebase Storage (gets URLs)              │
│ 2. User types message: "party vibes tonight"                       │
│ 3. Sends: POST /post/stream?q=...&media_urls=["https://..."]      │
└───────────────────────────┬─────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────────┐
│ FastAPI Backend: /post/stream                                       │
│                                                                     │
│ 4. Creates HumanMessage(content="party vibes tonight")             │
│    ⚠️  NO images sent to AI - only text                            │
│                                                                     │
│ 5. LangGraph Agent:                                                 │
│    • Loads conversation from SQLite (thread_id)                    │
│    • Calls Claude AI (NO tools provided)                           │
│    • AI responds: "okay are we ready to post now?"                 │
│    • Streams tokens back to iOS                                    │
│                                                                     │
│ 6. User replies: "yes post it"                                     │
│    • AI responds: "posting now!"                                   │
│    • System detects trigger phrase                                 │
│    • Generates redis_id                                            │
│    • Spawns background task                                        │
└───────────────────────────┬─────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────────┐
│ Background Task: create_post_from_conversation                      │
│                                                                     │
│ 7. Loads conversation history from SQLite                          │
│ 8. Calls Claude AI to generate captions:                           │
│    Input: conversation_messages + media_urls (just URLs)           │
│    Output: {title, caption, location}                              │
│                                                                     │
│ 9. Creates database records:                                       │
│    • Post(id, user_id, title, caption, location, created_at)      │
│    • PostMedia(id, post_id, media_url, media_type, created_at)    │
│      ▪ One record per image URL                                    │
│                                                                     │
│ 10. Gets followers from database:                                  │
│     SELECT follower_id FROM follows WHERE following_id = user_id   │
│                                                                     │
│ 11. For each follower:                                             │
│     • Creates Notification record in DB                            │
│     • Sends APNs push notification via HTTP/2                      │
│       Headers: apns-push-type=alert, apns-priority=10              │
│       Payload: {aps: {alert, sound, badge}, custom_data}          │
│                                                                     │
│ 12. Updates Redis: post_status:{redis_id} = "posted"              │
└───────────────────────────┬─────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────────┐
│ iOS App                                                             │
│                                                                     │
│ 13. Receives: event: post_initiated (with redis_id)                │
│ 14. Polls: GET /post/status/{redis_id} every 500ms                 │
│ 15. When status = "posted":                                        │
│     • Shows success message                                        │
│     • Refreshes feed                                               │
│     • Shows new post                                               │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Key Objects & Structures

### LangGraph Agent State
```python
class AgentState(TypedDict):
    messages: list[AnyMessage]  # Accumulates over conversation
```

### SQLite Checkpoint Structure
```python
{
    "channel_values": {
        "messages": [
            {"type": "human", "content": "party vibes tonight"},
            {"type": "ai", "content": "okay are we ready to post now?"},
            {"type": "human", "content": "yes post it"},
            {"type": "ai", "content": "posting now!"}
        ]
    },
    "next": [],  # Empty when graph reaches END
    "config": {"configurable": {"thread_id": "xyz789"}}
}
```

### Redis Status Objects
```python
# During processing
{
    "status": "processing",
    "message": "starting post creation..."
}

# When complete
{
    "status": "posted",
    "message": "post is live!",
    "post_id": "f2812407-584e-4625-b0b6-a2201ffe2846"
}
```

---

## Timeline of Events

```
T=0.0s   iOS: POST /post/stream (first message)
T=0.1s   Backend: Load SQLite conversation history (empty)
T=0.2s   Backend: Call Claude API
T=0.5s   Backend: Start streaming tokens "o", "k", "a", "y"...
T=1.2s   Backend: Finish streaming "are we ready to post now?"
T=1.2s   Backend: Save to SQLite checkpoint

T=2.0s   iOS: POST /post/stream (second message: "yes post it")
T=2.1s   Backend: Load SQLite history (2 messages)
T=2.2s   Backend: Call Claude API
T=2.5s   Backend: Stream "posting now!"
T=2.6s   Backend: Detect trigger → spawn background task

         ⚡ Parallel execution begins ⚡

         Thread A (API Response):        Thread B (Background Task):
T=2.6s   Send "event: done"              Load SQLite conversation
T=2.6s   Send "event: post_initiated"    Call Claude for captions
T=2.6s   Close SSE connection
                                          Parse JSON response
         Thread A ends                   Create Post in database
                                          Create PostMedia records
T=3.0s   iOS: Poll /post/status          Get followers from DB
T=3.5s   iOS: Poll /post/status          Send 3 push notifications
T=4.0s   iOS: Poll /post/status          Update Redis status
T=4.2s                                    Thread B ends

T=4.5s   iOS: Poll → status="posted"
T=4.5s   iOS: Show success, refresh feed
```

---

## Important Notes

1. **No Tools in Phase 1**: The Agent has `tools=[]`, so it never calls functions - only conversational responses

2. **Images Not Sent to AI**: The `media_urls` are Firebase URLs that stay on the backend. AI never sees the images during conversation.

3. **Two Separate AI Calls**:
   - Call 1: Conversational (streaming, with memory)
   - Call 2: Caption generation (one-shot, with conversation context)

4. **Parallel Execution**: AI finishes streaming while background task creates post

5. **Memory Persistence**: SQLite checkpoint maintains conversation state across multiple HTTP requests with same `thread_id`

6. **Push Notification Timing**: Sent ~2-3 seconds after user confirms, while iOS is still polling for status
