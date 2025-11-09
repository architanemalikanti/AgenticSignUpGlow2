# Verification Flow with Background Tasks

## 🔄 Complete Flow

```
User enters verification code
    ↓
Backend: test_verification_code() checks code
    ↓
┌─────────────────────────────────────────┐
│ If INCORRECT:                           │
│   - Tool returns "incorrect"            │
│   - LLM: "oops wrong code, try again!"  │
│   - iOS: Stays on same screen           │
│   - Prompt updates (dynamic)            │
└─────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────┐
│ If CORRECT:                             │
│   1. Tool returns "verified"            │
│   2. Backend starts background thread   │
│   3. LLM streams: "welcome to glow 🌸"  │
│   4. iOS sees message → Loading screen  │
│                                         │
│   BACKGROUND (300-500ms):               │
│   ├─ Save Redis → Postgres users       │
│   ├─ Save conversations → Postgres     │
│   ├─ Clean up Redis                    │
│   └─ Store user_id in Redis temp key   │
│                                         │
│   5. Stream polls for user_id           │
│   6. Sends user_id via SSE event        │
│   7. iOS receives user_id               │
│   8. iOS → Transitions to main app      │
└─────────────────────────────────────────┘
```

---

## 📡 SSE Events

### Event Types Your iOS App Will Receive

#### 1. **`token` Event** (Streaming LLM Response)
```json
event: token
data: {"content": "welcome"}

event: token
data: {"content": " to"}

event: token
data: {"content": " glow"}
```

#### 2. **`user_id` Event** (After Background Tasks Complete)
```json
event: user_id
data: {"user_id": 42}
```
**When:** Only sent after verification succeeds and background tasks finish (300-500ms after welcome message)

#### 3. **`error` Event** (If Timeout)
```json
event: error
data: {"error": "timeout"}
```
**When:** If background tasks take > 10 seconds (shouldn't happen)

#### 4. **`done` Event** (Stream Complete)
```json
event: done
data: {}
```
**When:** Always at the end of stream

---

## 📱 iOS Implementation

### Swift EventSource Handler

```swift
import Foundation

class OnboardingStream {
    private var eventSource: EventSource?
    
    func verifyCode(code: String, sessionId: String) {
        let url = "http://localhost:8000/chat/stream?q=\(code)&session_id=\(sessionId)"
        eventSource = EventSource(url: URL(string: url)!)
        
        // Listen for token events (LLM streaming)
        eventSource?.addEventListener("token") { [weak self] event in
            if let data = event.data?.data(using: .utf8),
               let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
               let content = json["content"] as? String {
                // Append to UI
                self?.appendMessage(content)
            }
        }
        
        // Listen for user_id event (background tasks done)
        eventSource?.addEventListener("user_id") { [weak self] event in
            if let data = event.data?.data(using: .utf8),
               let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
               let userId = json["user_id"] as? Int {
                // Save user_id and transition to main app
                UserDefaults.standard.set(userId, forKey: "userId")
                self?.transitionToMainApp(userId: userId)
            }
        }
        
        // Listen for error event
        eventSource?.addEventListener("error") { [weak self] event in
            self?.showError("Something went wrong. Please try again.")
        }
        
        // Listen for done event
        eventSource?.addEventListener("done") { [weak self] event in
            self?.eventSource?.close()
        }
        
        eventSource?.connect()
    }
    
    private func appendMessage(_ content: String) {
        DispatchQueue.main.async {
            // Update UI with streaming message
            // If first message, show loading screen
        }
    }
    
    private func transitionToMainApp(userId: Int) {
        DispatchQueue.main.async {
            // Navigate to main app with userId
            let mainVC = MainViewController(userId: userId)
            // ... navigation code
        }
    }
    
    private func showError(_ message: String) {
        DispatchQueue.main.async {
            // Show error alert
        }
    }
}
```

### User Flow States

```swift
enum VerificationState {
    case entering      // User typing code
    case verifying     // Waiting for LLM response
    case welcomeShown  // "welcome to glow 🌸" displayed, loading shown
    case complete      // user_id received, transitioning
    case failed        // Wrong code, try again
}
```

---

## ⏱️ Timing Breakdown

```
User enters code
    ↓ (instant)
Backend receives request
    ↓ (1-2ms)
Verify code in Redis
    ↓ (if correct)
Start background thread
    ↓ (instant)
LLM generates welcome message
    ↓ (500ms - 1s, streaming)
iOS shows: "welcome to glow 🌸"
iOS displays: Loading screen
    ↓
MEANWHILE (Background thread):
  ├─ 50ms:  Save user to Postgres
  ├─ 150ms: Save conversations
  └─ 1ms:   Clean up & store user_id
  Total: ~200-300ms
    ↓
Stream polls for user_id (200ms intervals)
    ↓ (finds it on 1st or 2nd poll)
Send user_id event
    ↓ (instant)
iOS receives user_id
    ↓ (instant)
iOS transitions to main app
    ↓
TOTAL USER WAIT TIME: 700ms - 1.3s
(Feels fast because of streaming + loading screen!)
```

---

## 🔧 Backend Components

### 1. **`test_verification_code` Tool** (`finalize_user.py`)
- Verifies code
- Returns `"incorrect"` or `"verified"`
- Marks verification status in Redis

### 2. **`finalize_user_background` Function** (`finalize_user.py`)
- Runs in separate thread
- Saves Redis → Postgres
- Saves conversations → Postgres
- Stores user_id in temp Redis key: `user_id:{session_id}`

### 3. **`chat_stream` Endpoint** (`stream.py`)
- Detects `on_tool_end` event with `test_verification_code` returning `"verified"`
- Starts background thread
- Continues streaming LLM response
- After LLM done, polls for user_id (max 10s)
- Sends `user_id` event when ready

---

## 🗄️ Redis Keys Used

| Key                        | Purpose                           | Lifetime     |
|----------------------------|-----------------------------------|--------------|
| `onboarding:{session_id}`  | Stores all user signup data       | Until verified, then deleted |
| `user_id:{session_id}`     | Temporary storage for user_id     | 60 seconds (then auto-expires) |

---

## 🧪 Testing

### Test Wrong Code
```bash
curl -N "http://localhost:8000/chat/stream?q=wrong%20code&session_id=test-123"
```

**Expected:**
```
event: token
data: {"content": "oops"}
...
event: token
data: {"content": "try again!"}

event: done
data: {}
```
**No `user_id` event**

### Test Correct Code
```bash
# Assuming verification code is 123456
curl -N "http://localhost:8000/chat/stream?q=123456&session_id=test-123"
```

**Expected:**
```
event: token
data: {"content": "welcome"}
...
event: token
data: {"content": " 🌸"}

event: user_id
data: {"user_id": 42}

event: done
data: {}
```

### Verify Database
```sql
-- Check user was created
SELECT * FROM users WHERE session_id = 'test-123';

-- Check conversations were saved
SELECT * FROM conversations WHERE user_id = 42;
```

---

## ⚠️ Error Handling

### Scenario 1: Background Task Fails
- **What happens:** user_id key is never created
- **Stream behavior:** Times out after 10s, sends `error` event
- **iOS behavior:** Should show retry button

### Scenario 2: Redis Connection Lost
- **What happens:** Can't read verification code
- **Tool returns:** `"incorrect"`
- **iOS behavior:** User can try again

### Scenario 3: Postgres Connection Lost
- **What happens:** `save_redis_to_postgres` returns 0
- **Background task:** Returns 0, no user_id stored
- **Stream behavior:** Times out, sends `error` event

---

## 🎯 Why This Design?

### Benefits
✅ **Fast UX** - User sees response immediately (~500ms)  
✅ **Progressive Loading** - Loading screen while data saves  
✅ **Reliable** - Data saves in background, retryable if fails  
✅ **Clean iOS Code** - Single stream handles everything  
✅ **Scalable** - Background tasks don't block LLM response  

### Trade-offs
⚠️ **Complexity** - More moving parts than synchronous  
⚠️ **Polling** - Stream must poll for user_id (but only 200ms overhead)  
⚠️ **Error Handling** - Need timeout logic  

---

## 🔄 Alternative Designs Considered

### Alternative 1: Synchronous (Simple but Slower)
```
Verify → Save (300ms) → Return user_id
User waits 800ms - 1.3s total
```
❌ Slower perceived performance

### Alternative 2: Callback/Webhook
```
Verify → Start background → Return "pending"
iOS polls /status endpoint until done
```
❌ More API calls, more complex

### Alternative 3: WebSocket
```
Maintain WebSocket connection
Send user_id when ready
```
❌ Overkill, SSE is simpler

---

## 📝 Summary

**Flow:** Verify → Background save → Stream welcome → Poll user_id → Transition

**iOS Receives:**
1. `token` events (welcome message)
2. `user_id` event (when background done)
3. `done` event (stream complete)

**Timing:** ~700ms - 1.3s total (feels instant due to streaming)

**Reliability:** Background task has 10s timeout, retryable on failure

