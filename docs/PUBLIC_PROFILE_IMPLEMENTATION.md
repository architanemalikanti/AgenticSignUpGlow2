# Public Profile Implementation Summary

## Backend Changes Complete ✅

### 1. Database Schema
- Added `is_private` column to `users` table (default: `FALSE` = public)
- All profiles are **PUBLIC by default**

### 2. Follow Logic (`stream.py`)
**Public Profiles:**
- Clicking follow → Instantly creates follow relationship
- No approval needed
- Notification: `"{name} started following you"`
- Push notification: `"{name} started following u"`

**Private Profiles:**
- Clicking follow → Creates follow request
- Requires approval
- Notification: `"{name} wants to follow you"`
- Push notification: `"{name} wants to follow u"`

### 3. Profile Viewing API (`GET /profile/{viewer_id}/{profile_id}`)

**Response includes `is_public` field:**
```json
{
  "status": "success",
  "follow_status": "following" | "not_following" | "pending" | "own_profile",
  "is_public": true | false,
  "user": { ... },
  "design": { ... }
}
```

**Public Profile Response:**
- `is_public: true`
- Shows full profile + design **regardless of follow status**
- Anyone can view

**Private Profile Response:**
- `is_public: false`
- Only shows full profile if following
- Shows limited info if not following

### 4. Privacy Toggle API (`POST /profile/{user_id}/privacy`)
```json
{
  "is_private": true/false
}
```

## Frontend Implementation Guide

### When User Clicks on a Profile:

```javascript
// 1. Fetch profile data
const response = await fetch(`/profile/${viewerId}/${profileId}`);
const data = await response.json();

// 2. Check if profile is public
if (data.is_public === true) {
  // PUBLIC PROFILE
  // ✅ Show full profile immediately
  // ✅ Show design if available
  // ✅ Show follow button (or "following" if already following)
  showFullProfile(data);

} else {
  // PRIVATE PROFILE
  // Check follow_status
  if (data.follow_status === "following") {
    // ✅ Show full profile (user is approved follower)
    showFullProfile(data);

  } else if (data.follow_status === "pending") {
    // ⏳ Show "Request Pending" state
    showPendingState(data.user);

  } else {
    // 🔒 Show locked profile (limited info)
    showLockedProfile(data.user);
  }
}
```

### Follow Button Logic:

```javascript
// When user clicks "Follow" button
async function handleFollowClick(requesterId, requestedId) {
  const response = await fetch('/follow/request', {
    method: 'POST',
    body: JSON.stringify({
      requester_id: requesterId,
      requested_id: requestedId
    })
  });

  const result = await response.json();

  if (result.message === "Now following (public profile)") {
    // ✅ PUBLIC PROFILE - instantly following
    // Update UI to show "Following"
    // Refresh profile to show full content
    updateButtonToFollowing();

  } else if (result.message === "Follow request sent") {
    // ⏳ PRIVATE PROFILE - request pending
    // Update UI to show "Request Pending"
    updateButtonToPending();
  }
}
```

### Notification Types:

**Type: `new_follower`** (Public profile follow)
```json
{
  "type": "new_follower",
  "follower_name": "Archita",
  "follower_id": "user_123",
  "follower_username": "archita"
}
```
- Title: "{name} started following u"
- Body: "{name} is now following you. check out their vibe!"

**Type: `follow_request`** (Private profile request)
```json
{
  "type": "follow_request",
  "requester_name": "Archita",
  "requester_id": "user_123",
  "requester_username": "archita"
}
```
- Title: "{name} wants to follow u"
- Body: "{name} thinks your vibe matches hers. prove her right?"

## Migration Steps

1. **Run the migration:**
   ```bash
   python add_is_private_column.py
   ```

2. **Restart the application**

3. **All users will be PUBLIC by default**

4. **Users can toggle privacy in settings:**
   ```bash
   POST /profile/{user_id}/privacy
   Body: {"is_private": true}
   ```

## Key Points for Frontend

✅ **Always check `is_public` field first** when rendering a profile
✅ **Public profiles show everything** regardless of follow status
✅ **Private profiles** follow the old logic (request → pending → approved)
✅ **Different notifications** for public vs private follows
✅ **Follow button behavior** changes based on profile type
