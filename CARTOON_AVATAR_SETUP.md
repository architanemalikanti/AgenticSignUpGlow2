# Cartoon Avatar Feature - Setup Guide

## Overview
Automatically assigns cartoon avatar images to **FEMALE users only** based on their ethnicity during onboarding.
Male and non-binary users will have `profile_image` set to `null`.

---

## Flow Summary

1. **User completes onboarding** → Answers questions (name, gender, ethnicity, etc.)
2. **Data stored in Redis** → `session:{session_id}` contains all signup data
3. **Verification code correct** → `finalize_simple_signup()` tool is called
4. **Avatar selection (females only)** → If gender is "female", `get_cartoon_avatar()` returns S3 URL based on ethnicity
5. **User created in Postgres** → Includes `profile_image` field (S3 URL for females, null for others)
6. **User ID + avatar URL stored in Redis** → Same Redis key now has `user_id` and `profile_image` (if female)
7. **iOS polls** → `GET /poll/{session_id}` returns `user_id`, tokens, and `profile_image` (may be null)
8. **iOS displays avatar** → Shows the cartoon image in the UI (if female)

---

## Files Modified/Created

### 1. `database/models.py`
**Added:** `profile_image` column to User model
```python
profile_image = Column(String(500), nullable=True)  # Cartoon avatar URL from S3
```

### 2. `avatar_helper.py` (NEW)
**Purpose:** Maps gender + ethnicity to S3 avatar URLs

**Mapping:**
- Female: `female_asian.png`, `female_black.png`, `female_white.png`, etc.
- Male: `male_asian.png`, `male_black.png`, `male_white.png`, etc.
- Non-binary: `nonbinary_asian.png`, `nonbinary_black.png`, etc.

**TODO:** Update `BASE_URL` with your actual S3 bucket URL!

### 3. `simple_onboarding_tools.py`
**Updated:** `finalize_simple_signup()` function

**Changes:**
- Gets gender and ethnicity from Redis
- **Only for females:** Calls `get_cartoon_avatar(gender, ethnicity)`
- Saves `profile_image` to Postgres User record (null for males/non-binary)
- Adds `profile_image` to Redis for iOS polling (only if not null)

### 4. `stream.py`
**Updated:** `/poll/{session_id}` endpoint

**Changes:**
- Returns `profile_image` in the response along with `user_id` and tokens

### 5. `add_profile_image_column.py` (NEW)
**Purpose:** Migration script to add `profile_image` column to existing users table

---

## Setup Instructions

### Step 1: Upload Avatar Images to S3

1. Create an S3 bucket (e.g., `my-app-avatars`)
2. Create a folder: `avatars/`
3. Upload **female** cartoon images with these exact filenames:
   - `female_asian.png`
   - `female_black.png`
   - `female_white.png`
   - `female_hispanic.png`
   - `female_middle_eastern.png`
   - `female_mixed.png`
   - `female_other.png` (fallback for unknown ethnicities)

4. Make bucket/objects publicly readable OR configure S3 presigned URLs

### Step 2: Update S3 URL in Code

Edit `avatar_helper.py` line 13:
```python
BASE_URL = "https://your-bucket-name.s3.us-west-1.amazonaws.com/avatars"
```

Replace with your actual S3 bucket URL.

### Step 3: Run Database Migration

SSH to your EC2 server and run:
```bash
cd AgenticSignUpGlow2
python add_profile_image_column.py
```

This adds the `profile_image` column to the existing `users` table.

### Step 4: Test the Flow

1. Start a new onboarding session
2. Answer all questions including gender and ethnicity
3. Enter verification code
4. Poll `/poll/{session_id}`
5. Verify response includes `profile_image` URL
6. Check Postgres: `SELECT id, username, profile_image FROM users;`

---

## API Response Format

### `/poll/{session_id}` Response (Female User):
```json
{
  "status": "ready",
  "user_id": "3ce657af-9a89-4173-8055-8a17f5a646be",
  "access_token": "eyJhbGciOiJIUzI1NiIs...",
  "refresh_token": "eyJhbGciOiJIUzI1NiIs...",
  "profile_image": "https://my-bucket.s3.us-west-1.amazonaws.com/avatars/female_asian.png",
  "session_id": "abc123"
}
```

### `/poll/{session_id}` Response (Male/Non-binary User):
```json
{
  "status": "ready",
  "user_id": "3ce657af-9a89-4173-8055-8a17f5a646be",
  "access_token": "eyJhbGciOiJIUzI1NiIs...",
  "refresh_token": "eyJhbGciOiJIUzI1NiIs...",
  "profile_image": null,
  "session_id": "abc123"
}
```

---

## How iOS Uses the Avatar

When iOS receives the poll response:
1. Save `user_id`, `access_token`, `refresh_token` to UserDefaults/Keychain
2. Check if `profile_image` is not null
3. If female (has `profile_image`), load and display the avatar:
   ```swift
   if let profileImage = response.profile_image,
      let imageURL = URL(string: profileImage) {
       avatarImageView.sd_setImage(with: imageURL)
   } else {
       // Male/non-binary user - show default placeholder or initials
       avatarImageView.image = UIImage(named: "default_placeholder")
   }
   ```

---

## Troubleshooting

### Avatar not showing?
- Check S3 bucket permissions (public read access)
- Verify BASE_URL in `avatar_helper.py` is correct
- Check backend logs for avatar selection: `🎨 Selected avatar for female/asian: ...`

### Column doesn't exist error?
- Run the migration: `python add_profile_image_column.py`
- Or recreate tables: `python init_db.py` (WARNING: deletes all data)

### Avatar not assigned?
- Only **female** users get avatars - males and non-binary users will have `profile_image = null`
- Check that gender is exactly "female" (case-insensitive)
- Valid ethnicities: "asian", "black", "white", "hispanic", "middle eastern", "mixed", "other"
- Values are case-insensitive
- Check backend logs for: `🎨 Selected avatar for female/asian: ...` or `ℹ️ No avatar assigned (gender: male)`

---

## Future Enhancements

- Allow users to upload custom avatars
- Add more avatar variations (styles, accessories, etc.)
- Generate avatars dynamically using AI (DiceBear API, etc.)
- Cache avatars locally on iOS for faster loading
