# CV Service Deployment Guide

Standalone FastAPI service for computer vision processing.

## Architecture

```
┌──────────────────────────┐         ┌──────────────────────────┐
│   Main Backend           │  HTTP   │   CV Service             │
│   (EC2 Instance 1)       │ ───────>│   (EC2 Instance 2)       │
│   Port 8000              │         │   Port 8001              │
│   Lightweight (no PyTorch)         │   With PyTorch + YOLO    │
└──────────────────────────┘         └──────────────────────────┘
```

## Setup on New EC2 Instance

### 1. Launch EC2 Instance

**Recommended instance type:** `g4dn.xlarge` (GPU-enabled)
- 4 vCPU, 16 GB RAM, NVIDIA T4 GPU
- **Use "Deep Learning AMI GPU PyTorch (Ubuntu)"** - comes with CUDA + PyTorch pre-installed
- ~$390/month (~$0.526/hour on-demand)
- Can use Spot Instances for ~70% savings

**Alternative (CPU-only):** `t3.medium` or `t3.large` for lower traffic/cost

**AMI Selection:**
When launching EC2, search for: `Deep Learning AMI GPU PyTorch`
- This includes CUDA 12.x, cuDNN, PyTorch, and all GPU drivers
- Saves 30+ minutes of setup time

### 2. Clone Repository

```bash
git clone <your-repo-url>
cd GlowBack
```

### 3. Copy CV Service to Instance

The CV service is completely self-contained in the `cv_service/` directory:

```bash
cv_service/
├── main.py                              # FastAPI service
├── requirements.txt                     # Dependencies
└── product_retrival_computer_vision/    # CV modules (included)
    ├── detector.py
    ├── feature_extractor.py
    └── vector_search.py
```

You can use `rsync` or `scp`:

```bash
# From your local machine:
rsync -avz cv_service/ ec2-user@<cv-instance-ip>:~/cv_service/
```

### 4. Install Dependencies

```bash
cd cv_service
pip install -r requirements-cv.txt
```

**Note:**
- PyTorch with CUDA support will be installed (~2GB download)
- If using Deep Learning AMI, CUDA drivers are already installed
- First install will take 5-10 minutes

### 5. Set Environment Variables

```bash
cp .env.example .env
# Edit .env with your credentials:
nano .env
```

Required:
- `PINECONE_API_KEY` - for vector search

Optional:
- `SERPAPI_API_KEY` - for Google Shopping fallback

### 6. Run the Service

**Development:**
```bash
python main.py
```

**Production (with Uvicorn):**
```bash
uvicorn main:app --host 0.0.0.0 --port 8001 --workers 2
```

**With systemd (recommended for production):**

Create `/etc/systemd/system/cv-service.service`:

```ini
[Unit]
Description=Fashion CV Service
After=network.target

[Service]
User=ec2-user
WorkingDirectory=/home/ec2-user/GlowBack/cv_service
ExecStart=/usr/bin/python3 -m uvicorn main:app --host 0.0.0.0 --port 8001 --workers 2
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Then:
```bash
sudo systemctl daemon-reload
sudo systemctl enable cv-service
sudo systemctl start cv-service
sudo systemctl status cv-service
```

### 7. Configure Security Group

Allow inbound traffic on port **8001** from your main backend's security group.

Or if testing, allow from anywhere temporarily:
- Type: Custom TCP
- Port: 8001
- Source: Your main backend IP or 0.0.0.0/0 (for testing only)

## API Endpoints

### Health Check
```bash
GET http://<cv-instance-ip>:8001/health
```

### Detect Fashion Items
```bash
POST http://<cv-instance-ip>:8001/detect
Content-Type: multipart/form-data

file: <image-file>
```

### Search Similar Products
```bash
POST http://<cv-instance-ip>:8001/search
Content-Type: application/json

{
  "image_base64": "base64-encoded-image",
  "top_k": 5,
  "category_filter": "dress"  // optional
}
```

### Analyze Outfit (Complete Pipeline)
```bash
POST http://<cv-instance-ip>:8001/analyze-outfit?top_k=3
Content-Type: multipart/form-data

file: <outfit-image>
```

Returns detected items + similar products for each.

## Testing

```bash
# Health check
curl http://localhost:8001/health

# Analyze an outfit
curl -X POST http://localhost:8001/analyze-outfit \
  -F "file=@test_outfit.jpg" \
  -F "top_k=3"
```

## Performance

**GPU Inference Times (g4dn.xlarge with T4):**
- Detection: ~50-100ms per image
- Feature extraction: ~30-50ms per item
- Vector search: <10ms
- **Total pipeline: ~100-200ms per outfit**

**CPU Inference Times (t3.medium - if using CPU):**
- Detection: ~500ms per image
- Feature extraction: ~200ms per item
- **Total pipeline: ~700-1000ms per outfit**

## Troubleshooting

### PyTorch Installation Slow
- GPU version is ~2GB download (vs 200MB CPU version)
- Use Deep Learning AMI (Ubuntu) - comes with PyTorch + CUDA pre-installed
- Or temporarily use larger instance with better network bandwidth

### GPU Not Detected
```bash
# Check if GPU is available
python -c "import torch; print(torch.cuda.is_available())"
# Should print: True

# Check GPU info
nvidia-smi
```
If False, ensure you're using Deep Learning AMI with CUDA drivers

### Out of Memory
- Reduce batch size or image resolution
- Upgrade to instance with more RAM
- Or use GPU instance

### Models Not Found
- YOLO models download automatically on first use (~6MB)
- Models are cached in `~/.cache/torch/hub/` and `~/.ultralytics/`
- Ensure internet connectivity for model downloads

## Connecting from Main Backend

In your main backend's `.env`:
```bash
CV_SERVICE_URL=http://<cv-instance-private-ip>:8001
```

Use the CV client:
```python
from services.cv_client import get_cv_client

cv_client = get_cv_client()
result = await cv_client.analyze_outfit(image_bytes=image_data)
```

## Logs

View logs:
```bash
# If using systemd:
sudo journalctl -u cv-service -f

# If running manually:
# Logs will appear in terminal
```

## Scaling

For high traffic:
1. Use multiple workers: `--workers 4`
2. Use GPU instance for faster inference
3. Add load balancer with multiple CV instances
4. Cache frequent requests with Redis

## Cost Optimization

- **Development:** Use `t3.small` with CPU (~$15/month)
- **Production:** Use `t3.medium` or `g4dn.xlarge` with autoscaling
- **GPU needed?** Only if you need <100ms latency per image
