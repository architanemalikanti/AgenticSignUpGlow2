# S3 Quick Start - TL;DR Version

## 🚀 Super Quick Setup (15 minutes)

### 1. Create AWS Account
- Go to https://aws.amazon.com/ → Sign up
- Free tier: 5GB storage, 20k requests/month

### 2. Create S3 Bucket
- AWS Console → Search "S3" → Create bucket
- Name: `stream-app-avatars-[random-number]` (must be unique)
- Region: `US West (Oregon)` or `US West (N. California)`
- **IMPORTANT**: Uncheck "Block all public access"
- Click Create

### 3. Upload Images
- Click bucket → Create folder: `avatars`
- Upload 7 images: `female_asian.png`, `female_black.png`, etc.
- **Set permissions**: "Grant public-read access" ✅
- Upload

### 4. Add Bucket Policy
- Bucket → Permissions tab → Bucket policy → Edit
- Paste this (replace `YOUR-BUCKET-NAME`):
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": "*",
      "Action": "s3:GetObject",
      "Resource": "arn:aws:s3:::YOUR-BUCKET-NAME/avatars/*"
    }
  ]
}
```
- Save

### 5. Get Your URL
- Click on any image → Copy "Object URL"
- Example: `https://stream-app-avatars-123.s3.us-west-2.amazonaws.com/avatars/female_asian.png`
- Your base URL is everything before the filename:
  ```
  https://stream-app-avatars-123.s3.us-west-2.amazonaws.com/avatars
  ```

### 6. Update Your Code
SSH to EC2 and add to `.env`:
```bash
cd AgenticSignUpGlow2
nano .env
```

Add this line (replace with YOUR URL):
```
S3_AVATAR_BASE_URL=https://stream-app-avatars-123.s3.us-west-2.amazonaws.com/avatars
```

Save (Ctrl+X, Y, Enter)

### 7. Restart Server
```bash
sudo systemctl restart stream
# or
sudo pkill python && python stream.py
```

### 8. Test!
- Start a new female user onboarding
- Check logs: `🎨 Selected avatar for female/asian: https://...`
- Poll endpoint should return `profile_image` URL
- Load in iOS!

---

## 📝 Required Files on S3:
- `avatars/female_asian.png`
- `avatars/female_black.png`
- `avatars/female_white.png`
- `avatars/female_hispanic.png`
- `avatars/female_middle_eastern.png`
- `avatars/female_mixed.png`
- `avatars/female_other.png`

---

## 🧪 Test Your URLs Work:
Open in browser:
```
https://YOUR-BUCKET.s3.YOUR-REGION.amazonaws.com/avatars/female_asian.png
```

Should display the image! ✅

---

## 💰 Cost:
**$0.00** - Free tier covers everything for small apps

---

## 🐛 Troubleshooting:

**Images not loading?**
1. Check bucket policy saved correctly
2. Verify "Block all public access" is OFF
3. Test URL in browser first

**Access Denied?**
- Double-check bucket policy Resource ARN
- Make sure public access is enabled
- Verify images uploaded with "public-read" permission

---

## 📚 Full Guide:
See `S3_SETUP_GUIDE.md` for detailed step-by-step instructions with screenshots.
