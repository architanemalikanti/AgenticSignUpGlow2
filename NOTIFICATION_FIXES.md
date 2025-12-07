# Notification Fixes Summary

## Issues Fixed

### 1. ✅ Profiles Default Setting
**Problem:** After migration, all profiles were set to PUBLIC, but existing users should stay PRIVATE.

**Solution:**
- Model default: `is_private=False` (new users are PUBLIC)
- Created `fix_existing_users_private.py` migration
- Run on EC2: `python3 fix_existing_users_private.py`
- This sets all existing users to PRIVATE
- New signups from now on will be PUBLIC

### 2. ✅ Follow Notifications Not Showing
**Problem:** When someone follows a public profile, notification says `"{name} started following you"`, but the notifications endpoint only looked for:
- `"wants to follow you"` (follow request)
- `"accepted your follow request"` (follow accept)
- `"posted"` (new post)

So it was skipping the "started following you" notifications!

**Solution:** Added filter in `stream.py:2959`:
```python
elif "started following you" in notif.content:
    notif_type = "new_follower"
```

### 3. ✅ Post Notifications
**Problem Suspected:** Not showing up in feed

**Status:** Post notifications look correct in code. They create:
- In-app notification: `"{name} posted: {title}"` or `"{name} posted"`
- This matches the filter: `"posted" in notif.content`

**If still not working, check:**
1. Are followers being found? (Check `follows` table)
2. Are Era records being created? (Check `eras` table)
3. Check logs for errors during post creation

## Current Notification Flow

### Public Profile Follow:
1. User A clicks "Follow" on User B (public profile)
2. **Immediately creates follow relationship** (no approval needed)
3. Creates Era notification:
   - `user_id`: User B
   - `actor_id`: User A
   - `content`: `"{User A name} started following you"`
4. Sends push notification: `"{name} started following u"`
5. **Notification type:** `"new_follower"`

### Private Profile Follow:
1. User A clicks "Follow" on User B (private profile)
2. **Creates follow request** (needs approval)
3. Creates Era notification:
   - `user_id`: User B
   - `actor_id`: User A
   - `content`: `"{User A name} wants to follow you"`
4. Sends push notification: `"{name} wants to follow u"`
5. **Notification type:** `"follow_request"`

### New Post:
1. User A creates a post
2. Finds all followers
3. For each follower, creates Era notification:
   - `user_id`: Follower ID
   - `actor_id`: User A (poster)
   - `content`: `"{User A name} posted: {title}"` or `"{User A name} posted"`
4. Sends push notification with title and caption preview
5. **Notification type:** `"new_post"`

## Notification Types in API Response

GET `/notifications/{user_id}` returns:

```json
{
  "status": "success",
  "user_id": "user_123",
  "count": 3,
  "notifications": [
    {
      "id": "notif_1",
      "type": "follow_request",
      "content": "Dolev wants to follow you",
      "actor_id": "dolev_id",
      "actor_username": "dolev",
      "actor_name": "Dolev",
      "actor_profile_image": "https://...",
      "created_at": "2025-12-06T..."
    },
    {
      "id": "notif_2",
      "type": "new_follower",
      "content": "Archita started following you",
      "actor_id": "archita_id",
      "actor_username": "archita",
      "actor_name": "Archita",
      "actor_profile_image": "https://...",
      "created_at": "2025-12-06T..."
    },
    {
      "id": "notif_3",
      "type": "new_post",
      "content": "Sarah posted: Beach Day!",
      "actor_id": "sarah_id",
      "actor_username": "sarah",
      "actor_name": "Sarah",
      "actor_profile_image": "https://...",
      "created_at": "2025-12-06T..."
    }
  ]
}
```

## Migration Steps for EC2

```bash
# 1. Set all existing users to PRIVATE
python3 fix_existing_users_private.py

# 2. Restart the application to pick up code changes
# (however you restart your app - systemctl, pm2, etc.)
```

## Frontend Changes Needed

The frontend should now handle the new notification type:

```swift
switch notification.type {
case "follow_request":
    // Show "wants to follow you" with Accept/Decline buttons

case "follow_accept":
    // Show "accepted your follow request"

case "new_follower":  // ← NEW TYPE
    // Show "started following you"
    // No action buttons needed (already following)

case "new_post":
    // Show "posted: {title}" with post preview
}
```

## Debugging Tips

If notifications still don't show:

1. **Check the eras table:**
   ```sql
   SELECT * FROM eras WHERE user_id = 'your_user_id' ORDER BY created_at DESC LIMIT 10;
   ```

2. **Check if follows exist:**
   ```sql
   SELECT * FROM follows WHERE following_id = 'your_user_id';
   ```

3. **Check application logs:**
   ```bash
   # Look for these log messages:
   # "✅ Created follow request notification for..."
   # "✅ Created post notification for follower..."
   ```

4. **Test the notifications endpoint:**
   ```bash
   curl http://your-api/notifications/your_user_id
   ```
