# Amazon S3 Setup Guide for Avatar Images

## What You'll Do:
1. Create an AWS account (free tier available)
2. Create an S3 bucket to store avatar images
3. Upload your 7 female avatar images
4. Make the images publicly accessible
5. Get the URLs and update your code

---

## Step 1: Create an AWS Account

1. Go to https://aws.amazon.com/
2. Click "Create an AWS Account"
3. Fill in:
   - Email address
   - Password
   - Account name (e.g., "Stream App")
4. Choose **Personal** account type
5. Enter payment info (required, but you'll use the free tier)
6. Verify your phone number
7. Choose **Free Tier** plan

**Free Tier includes:**
- 5 GB of S3 storage
- 20,000 GET requests per month
- 2,000 PUT requests per month
- More than enough for your avatar images!

---

## Step 2: Sign in to AWS Console

1. Go to https://console.aws.amazon.com/
2. Sign in with your email and password
3. You'll see the AWS Management Console

---

## Step 3: Create an S3 Bucket

1. In the AWS Console, search for "S3" in the top search bar
2. Click "S3" to open the S3 dashboard
3. Click the orange **"Create bucket"** button

**Bucket settings:**
- **Bucket name**: `stream-app-avatars` (must be globally unique, try adding random numbers if taken)
- **Region**: `US West (N. California)` or `US West (Oregon)` (closest to your EC2 server)
- **Object Ownership**: Keep default (ACLs disabled)
- **Block Public Access settings**:
  - ⚠️ **UNCHECK** "Block all public access"
  - Check the box that says "I acknowledge that the current settings might result in this bucket and the objects within becoming public"
- **Bucket Versioning**: Disabled (keep default)
- **Encryption**: Disabled (keep default) or use Amazon S3-managed keys (SSE-S3)
- **Object Lock**: Disabled (keep default)

4. Click **"Create bucket"** at the bottom

---

## Step 4: Create the `avatars/` Folder

1. Click on your newly created bucket name (e.g., `stream-app-avatars`)
2. Click **"Create folder"** button
3. Folder name: `avatars`
4. Click **"Create folder"**

---

## Step 5: Upload Avatar Images

1. Click on the `avatars/` folder to open it
2. Click **"Upload"** button
3. Click **"Add files"** and select your 7 avatar images:
   - `female_asian.png`
   - `female_black.png`
   - `female_white.png`
   - `female_hispanic.png`
   - `female_middle_eastern.png`
   - `female_mixed.png`
   - `female_other.png`

4. **IMPORTANT: Set permissions**
   - Expand "Permissions" section
   - Under "Predefined ACLs", select **"Grant public-read access"**
   - Check the box: "I understand the effects of these changes on the specified objects"

5. Keep all other settings as default
6. Click **"Upload"** at the bottom
7. Wait for upload to complete (should be fast for small images)
8. Click **"Close"** when done

---

## Step 6: Make Bucket Publicly Readable (Bucket Policy)

Now we need to add a bucket policy to ensure all images are publicly accessible.

1. Go back to your bucket (click "stream-app-avatars" in the breadcrumb at top)
2. Click the **"Permissions"** tab
3. Scroll down to **"Bucket policy"**
4. Click **"Edit"**
5. Paste this JSON policy (replace `stream-app-avatars` with your actual bucket name):

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "PublicReadGetObject",
      "Effect": "Allow",
      "Principal": "*",
      "Action": "s3:GetObject",
      "Resource": "arn:aws:s3:::stream-app-avatars/avatars/*"
    }
  ]
}
```

6. Click **"Save changes"**

---

## Step 7: Get Your Avatar URLs

1. In your bucket, click on the `avatars/` folder
2. Click on one of your images (e.g., `female_asian.png`)
3. Copy the **"Object URL"** from the top

**Example URL format:**
```
https://stream-app-avatars.s3.us-west-2.amazonaws.com/avatars/female_asian.png
```

**Your base URL will be:**
```
https://YOUR-BUCKET-NAME.s3.YOUR-REGION.amazonaws.com/avatars
```

For example:
- Bucket name: `stream-app-avatars`
- Region: `us-west-2`
- Base URL: `https://stream-app-avatars.s3.us-west-2.amazonaws.com/avatars`

---

## Step 8: Test Your URLs

Open your browser and paste one of the full URLs:
```
https://stream-app-avatars.s3.us-west-2.amazonaws.com/avatars/female_asian.png
```

You should see the image load! If not, check:
- Bucket policy is correct
- Public access is enabled
- Image was uploaded with "Grant public-read access"

---

## Step 9: Update Your Code

Now update `avatar_helper.py` with your actual S3 URL:

**Before:**
```python
BASE_URL = "https://your-bucket-name.s3.us-west-1.amazonaws.com/avatars"
```

**After (example):**
```python
BASE_URL = "https://stream-app-avatars.s3.us-west-2.amazonaws.com/avatars"
```

---

## Alternative: Environment Variable (Recommended)

Instead of hardcoding the URL, store it in your `.env` file:

1. Add to your `.env` file:
   ```
   S3_AVATAR_BASE_URL=https://stream-app-avatars.s3.us-west-2.amazonaws.com/avatars
   ```

2. Update `avatar_helper.py`:
   ```python
   import os
   from dotenv import load_dotenv

   load_dotenv()

   def get_cartoon_avatar(gender: str, ethnicity: str) -> str:
       BASE_URL = os.getenv("S3_AVATAR_BASE_URL", "https://default-url.com/avatars")
       # rest of your code...
   ```

---

## Cost Estimate

For your use case:
- **Storage**: 7 small PNG images (~50KB each) = ~350KB total
- **Requests**: ~100 new users per month × 1 GET request = 100 requests/month

**Monthly cost**: Essentially $0.00 (well within free tier)

**Free tier limits:**
- 5 GB storage (you're using 0.00035 GB)
- 20,000 GET requests (you're using ~100)

---

## Security Notes

**Current setup: Publicly readable images**
- Anyone with the URL can view the images
- This is fine for cartoon avatars (not sensitive data)
- URLs are not guessable (long random bucket names help)

**If you want more security later:**
- Use presigned URLs (temporary, expiring links)
- Enable CloudFront CDN for faster loading
- Restrict access with IAM policies

---

## Troubleshooting

### Images not loading?
1. Check bucket policy is saved correctly
2. Verify "Block all public access" is OFF
3. Confirm each image has "Grant public-read access"
4. Try accessing URL directly in browser

### "Access Denied" error?
- Bucket policy might be wrong
- Check the Resource ARN matches your bucket name
- Make sure you unchecked "Block all public access"

### URLs not working in code?
- Double-check BASE_URL has no trailing slash
- Verify the region in the URL matches your bucket's region
- Test URL in browser first

---

## Next Steps After Setup

1. Update `avatar_helper.py` with your S3 base URL
2. Restart your backend server
3. Test onboarding with a female user
4. Check logs for: `🎨 Selected avatar for female/asian: https://...`
5. Poll `/poll/{session_id}` and verify `profile_image` URL is returned
6. Load the URL in iOS and display the avatar!

---

## Quick Reference: S3 URL Format

```
https://BUCKET-NAME.s3.REGION.amazonaws.com/FOLDER/FILENAME
```

Example:
```
https://stream-app-avatars.s3.us-west-2.amazonaws.com/avatars/female_asian.png
        ↑                      ↑              ↑        ↑
     bucket name            region         folder   filename
```
