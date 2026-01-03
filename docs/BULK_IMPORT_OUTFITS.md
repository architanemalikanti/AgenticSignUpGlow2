# Bulk Import Outfits from Firebase

Automatically import outfit images from Firebase Storage and generate titles using Claude VLM.

---

## Setup

### 1. Install Dependencies

```bash
pip install firebase-admin
```

(Already added to requirements.txt)

### 2. Get Firebase Credentials

1. Go to [Firebase Console](https://console.firebase.google.com/)
2. Select your project
3. Go to **Project Settings** → **Service Accounts**
4. Click **Generate New Private Key**
5. Save the JSON file as `firebase-credentials.json` in your project root

### 3. Set Environment Variables

Add to your `.env` file:

```bash
# Firebase
FIREBASE_CREDENTIALS_PATH=./firebase-credentials.json
FIREBASE_STORAGE_BUCKET=your-app.appspot.com
FIREBASE_OUTFITS_FOLDER=outfits/

# Anthropic (for VLM)
ANTHROPIC_API_KEY=your-anthropic-key
```

**Note:** Your Firebase Storage bucket name is usually `your-project-id.appspot.com`

---

## Usage

### Run the Import Script

```bash
python scripts/bulk_import_outfits_from_firebase.py
```

### What It Does

1. **Connects to Firebase Storage** - Fetches images from the specified folder
2. **For each image:**
   - Gets the public URL
   - Sends to Claude VLM (claude-3-5-sonnet) to analyze
   - Generates a catchy, Instagram-style title
   - Saves to Postgres with:
     - `base_title`: AI-generated title
     - `image_url`: Firebase public URL
     - `gender`: "women" (default)
3. **Skips duplicates** - Won't re-import existing outfits

---

## Example Output

```
🚀 Starting bulk outfit import from Firebase...
✅ Firebase initialized successfully
📁 Looking for images in: outfits/

📸 Processing: outfits/outfit_001.jpg
✨ Generated title: Y2K throwback vibes
✅ Imported outfit: Y2K throwback vibes

📸 Processing: outfits/outfit_002.jpg
✨ Generated title: Street style icon NYC
✅ Imported outfit: Street style icon NYC

📸 Processing: outfits/outfit_003.jpg
⏭️ Outfit already exists, skipping: outfits/outfit_003.jpg

🎉 Import complete!
   Imported: 2 outfits
   Skipped: 1 (already exist)
✨ All done!
```

---

## Folder Structure in Firebase

Your Firebase Storage should look like:

```
your-bucket/
  └── outfits/
      ├── outfit_001.jpg
      ├── outfit_002.jpg
      ├── outfit_003.png
      └── ...
```

**Supported formats:** `.jpg`, `.jpeg`, `.png`, `.webp`

---

## Title Generation

Claude VLM analyzes each outfit and generates titles like:
- "1999 celeb caught by paparazzi"
- "Clean girl aesthetic moment"
- "90s grunge queen energy"
- "Old money summer look"
- "Y2K throwback vibes"

Titles are:
- ✅ Short (3-6 words)
- ✅ Instagram/TikTok style
- ✅ Capture the aesthetic/era
- ❌ No emojis
- ❌ No price info

---

## Troubleshooting

### "Firebase credentials not found"
- Make sure `firebase-credentials.json` exists in project root
- Or set `FIREBASE_CREDENTIALS_PATH` to correct location

### "Error initializing Firebase"
- Check that `FIREBASE_STORAGE_BUCKET` is set correctly
- Format should be: `your-project-id.appspot.com`

### "No images found"
- Check that `FIREBASE_OUTFITS_FOLDER` matches your actual folder name
- Make sure folder contains `.jpg`, `.jpeg`, `.png`, or `.webp` files

### "Error generating title with VLM"
- Check that `ANTHROPIC_API_KEY` is set and valid
- Make sure you have credits in your Anthropic account
- Check that images are publicly accessible

---

## Cost Estimate

Claude VLM pricing (claude-3-5-sonnet):
- ~$0.003 per image (3mm tokens input + 50 tokens output)
- 100 images = ~$0.30
- 1000 images = ~$3.00

Very cheap! 🎉

---

## Next Steps

After importing:
1. iOS calls `GET /outfits/all` to fetch the list
2. iOS calls `GET /outfits/{outfit_id}` for each outfit
3. Backend calculates prices with LLM
4. Returns formatted outfit with products
