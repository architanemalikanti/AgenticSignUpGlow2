# Finalization Flow Documentation

## 🔄 Complete User Verification Flow

### Backend Flow
```
User enters verification code
    ↓
test_verification_code(session_id, code) tool executes:
    ↓
1. ✅ Verify code matches Redis stored code
    ↓
2. 💾 Save Redis data → Postgres users table (~50ms)
    ↓
3. 💬 Save conversations → Postgres conversations table (~100-200ms)
    ↓
4. 🗑️  Delete Redis session (cleanup)
    ↓
5. ✨ Return user_id
    ↓
Total time: ~300-500ms
```

### iOS Flow
```swift
// User enters code
let code = userInputCode

// Show loading screen
showLoadingScreen()

// Call API (waits 300-500ms while backend saves everything)
let userId = await chatStream(q: code, sessionId: sessionId)

// Check response
if userId > 0 {
    // Success! Everything is saved in Postgres
    transitionToMainApp(userId: userId)
} else {
    // Verification failed
    showError("Wrong code, try again")
}
```

---

## 📦 What Gets Saved

### 1. Redis → Postgres `users` Table
**Fields Migrated:**
- `session_id` → tracks original session
- `first_name`
- `username` (unique)
- `password` (hashed)
- `email` (unique)
- `birthday` (optional)
- `gender` (optional)
- `sexuality` (optional)
- `ethnicity` (optional)
- `pronouns` (optional)
- `university` (optional)
- `college_major` (optional)
- `occupation` (optional)
- `created_at` → auto-set to now
- `updated_at` → auto-set to now

### 2. SQLite Checkpointer → Postgres `conversations` Table
**Each Message:**
- `user_id` → links to users table
- `sender` → "user" or "assistant"
- `message` → the actual message content
- `timestamp` → when message was sent

---

## 🔧 Integration Steps

### 1. Add Tool to Your Tools List

In your onboarding tools file (or `stream.py`), import and add:

```python
from finalize_user import test_verification_code

# In your tools list:
tools = [
    tool,  # TavilySearch
    test_verification_code,  # The finalization tool
    # ... other tools
]
```

### 2. Update Agent Initialization

In `stream.py`:
```python
from finalize_user import test_verification_code
from onboarding import PersonOnboarding  # Your other tools

# Combine all tools
all_tools = [tool, test_verification_code]  # Add your other onboarding tools here

# Create agent with all tools
async_abot = Agent(model, all_tools, system=dynamic_prompt, checkpointer=async_memory)
```

### 3. Ensure Prompt Instructs to Use This Tool

Your `prompt_manager.py` should already have this instruction:
```
17. Ask the user to type the verification code they received. This is the final step. 
Verify it using:  
test_verification_code(session_id: str, user_input_verification_code: int)

If it does not match: the integer 0 is returned. 
If it DOES match: a non-zero integer will be returned (the user's ID in Postgres).
```

---

## 🧪 Testing

### Test Verification Success
```python
# In Python shell or test file:
from finalize_user import test_verification_code

# Assuming you have a session with verification code 123456
result = test_verification_code.invoke({
    "session_id": "test-session-123",
    "user_input_verification_code": 123456
})

print(f"User ID: {result}")  # Should print non-zero user_id
```

### Test Verification Failure
```python
result = test_verification_code.invoke({
    "session_id": "test-session-123",
    "user_input_verification_code": 999999  # Wrong code
})

print(f"Result: {result}")  # Should print 0
```

### Verify Database
```sql
-- Check user was created
SELECT * FROM users WHERE session_id = 'test-session-123';

-- Check conversations were saved
SELECT * FROM conversations WHERE user_id = <user_id_from_above>;
```

---

## ⚠️ TODO: Complete Conversation Migration

The `save_conversations_to_postgres()` function currently has a **placeholder** implementation. You need to:

1. Read from SQLite `conversations.db` using the `session_id` as `thread_id`
2. Parse LangChain message objects (HumanMessage, AIMessage)
3. Insert into Postgres `conversations` table

### Implementation Hint:
```python
import sqlite3
from langgraph.checkpoint.sqlite import SqliteSaver

def save_conversations_to_postgres(session_id: str, user_id: int) -> bool:
    # Connect to SQLite checkpointer db
    conn = sqlite3.connect('conversations.db')
    cursor = conn.cursor()
    
    # Query for thread_id
    cursor.execute("""
        SELECT checkpoint_ns, checkpoint_id, parent_checkpoint_id, checkpoint 
        FROM checkpoints 
        WHERE thread_id=?
    """, (session_id,))
    
    rows = cursor.fetchall()
    
    with app.app_context():
        for row in rows:
            # Parse checkpoint data (contains messages)
            # checkpoint is a pickled object with message history
            # You'll need to deserialize and extract messages
            
            # For each message:
            conversation = Conversation(
                user_id=user_id,
                sender="user" if isinstance(msg, HumanMessage) else "assistant",
                message=msg.content,
                timestamp=datetime.utcnow()
            )
            db.session.add(conversation)
        
        db.session.commit()
    
    conn.close()
    return True
```

---

## 🎯 Expected Timing

**Synchronous Save (Current Implementation):**
- Verify code: ~1-2ms
- Save Redis → Postgres: ~50ms
- Save conversations → Postgres: ~100-200ms (depends on message count)
- Delete Redis: ~1-2ms
- **Total: 150-300ms**

**User Experience:**
- iOS shows loading screen immediately
- Backend processes verification (150-300ms)
- iOS receives user_id and transitions
- **Feels instant to user** ✨

---

## 📝 Response Format

The tool returns an integer:
- `0` → Verification failed (wrong code)
- `> 0` → Success (user_id from Postgres)

iOS can check:
```swift
if userId > 0 {
    // Success!
    saveUserId(userId)
    navigateToMainApp()
} else {
    // Failed
    showError("Incorrect verification code")
}
```

---

## 🔐 Security Notes

1. **Password Hashing**: Ensure the `set_password` tool hashes passwords BEFORE storing in Redis
2. **Verification Code**: Store securely in Redis with expiration (e.g., 10 minutes)
3. **Rate Limiting**: Limit verification attempts (e.g., max 3 attempts)
4. **Cleanup**: Redis session is deleted after successful verification (no sensitive data left behind)

---

## 🐛 Troubleshooting

### User ID returns 0 but code is correct
- Check Redis has verification_code field
- Check Redis data has all required fields (first_name, username, password, email)
- Check Postgres connection (see database/db.py)

### Conversations not saving
- Check SQLite `conversations.db` file exists
- Implement the conversation migration (currently placeholder)
- Check Postgres conversations table exists (`python create_tables.py`)

### Redis session not found
- Check session_id matches between frontend and backend
- Check Redis is running (`redis-cli ping`)
- Check Redis key format: `onboarding:{session_id}`

