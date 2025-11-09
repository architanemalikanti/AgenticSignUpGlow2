# Glow Backend Setup Guide

## ✅ Changes Made

### 1. **Updated User Model** (`database/models.py`)
- ✅ Changed `name` → `first_name` (matches Redis)
- ✅ Changed `major` → `college_major` (matches Redis)
- ✅ Added `occupation` field (matches Redis)
- ✅ Added `session_id` field (tracks Redis session)
- ✅ Added `created_at` and `updated_at` timestamps
- ✅ Made optional fields nullable (gender, sexuality, etc.)

### 2. **Fixed Conversation Persistence** (`stream.py`)
- ✅ Changed from `:memory:` to `sqlite:///conversations.db`
- ✅ Conversations now persist across server restarts

### 3. **Created Table Setup Script** (`create_tables.py`)
- ✅ Run this to create database tables from your models

---

## 🚀 Setup Steps

### 1. Start Services
```bash
# Start Redis
brew services start redis

# Verify Redis is running
redis-cli ping
# Should return: PONG

# Start Postgres (if not already running)
brew services start postgresql
```

### 2. Update Your `.env` File
Make sure your `.env` has these values:
```bash
# OpenAI
OPENAI_API_KEY=sk-your-key-here

# Tavily
TAVILY_API_KEY=tvly-your-key-here

# Redis
REDIS_HOST=localhost
REDIS_PORT=6379

# Postgres (update with your actual password)
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=glowdb
POSTGRES_USER=postgres
POSTGRES_PASSWORD=pi624rok.A11
```

### 3. Create Database Tables
```bash
cd /Users/architanemalikanti/Stream
python create_tables.py
```

### 4. Verify Tables Were Created
```bash
psql glowdb
\dt
# Should show: users, conversations

\d users
# Should show all your columns including first_name, college_major, occupation, session_id

\q
```

### 5. Run the Server
```bash
cd /Users/architanemalikanti/Stream
python stream.py
```

### 6. Test Endpoints
```bash
# Health check
curl http://localhost:8000/health

# Create session
curl http://localhost:8000/createRedisKey

# Test chat stream (replace YOUR_SESSION_ID)
curl -N "http://localhost:8000/chat/stream?q=hi&session_id=YOUR_SESSION_ID"
```

---

## 📦 Field Name Mapping (Redis ↔ Postgres)

| Redis Field            | User Model Field    |
|------------------------|---------------------|
| `session_id`           | `session_id`        |
| `first_name`           | `first_name` ✅     |
| `username`             | `username`          |
| `password`             | `password`          |
| `email`                | `email`             |
| `birthday`             | `birthday`          |
| `gender`               | `gender`            |
| `sexuality`            | `sexuality`         |
| `ethnicity`            | `ethnicity`         |
| `pronouns`             | `pronouns`          |
| `university`           | `university`        |
| `college_major`        | `college_major` ✅  |
| `occupation`           | `occupation` ✅     |

---

## 🗂️ Where Data Lives

### Redis (`onboarding:{session_id}`)
- Temporary user data during signup
- Expires after 24 hours (can be extended)
- Key example: `onboarding:abc-123-def-456`

### SQLite (`conversations.db`)
- Conversation history (messages between user and LLM)
- Persists across server restarts
- Indexed by `session_id` as `thread_id`

### Postgres (`glowdb` database)
- **`users` table:** Final user records after signup complete
- **`conversations` table:** Long-term conversation storage (optional, for archival)

---

## 🔄 Data Flow

1. **Frontend** → sends `session_id` (UUID)
2. **Redis** → stores temporary signup data
3. **SQLite** → stores conversation messages
4. **Tools** → update Redis as user provides info
5. **Verification** → when code verified, data moves to Postgres
6. **Postgres** → returns `user_id` to frontend

---

## ⚠️ Troubleshooting

### Redis not connecting?
```bash
redis-cli ping
# If fails, start Redis:
brew services start redis
```

### Postgres not connecting?
```bash
psql glowdb
# If fails, check credentials in .env match database/db.py
```

### Tables not created?
```bash
python create_tables.py
# Then verify:
psql glowdb -c '\dt'
```

### Can't import modules?
```bash
pip install -r requirements.txt
# Or install individually as listed in the main README
```

---

## 📝 Next Steps

1. Create the onboarding tools that save Redis data to Postgres
2. Add the `test_verification_code` tool that:
   - Verifies the code
   - Saves Redis data to Postgres User table
   - Returns the `user_id`
   - Deletes the Redis session
3. Test the full signup flow end-to-end

