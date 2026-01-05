# Deployment Guide

## Architecture Overview

```
┌──────────────────────────┐         ┌──────────────────────────┐
│   Main Backend           │  HTTP   │   CV Service             │
│   EC2 Instance           │ ───────>│   EC2 GPU Instance       │
│   Port 8000              │         │   Port 8001              │
│   requirements-backend   │         │   requirements-cv        │
└──────────────────────────┘         └──────────────────────────┘
```

## Quick Start

### 1. Deploy CV Service (GPU Instance)

**Launch EC2:**
- Instance: `g4dn.xlarge`
- AMI: Search "Deep Learning AMI GPU PyTorch (Ubuntu)"
- Storage: 50GB minimum
- Security Group: Allow port 8001

**Setup:**
```bash
# SSH into CV instance
ssh -i your-key.pem ubuntu@<cv-instance-ip>

# Clone repo
git clone <your-repo-url>
cd GlowBack/cv_service

# Install dependencies (PyTorch with GPU)
pip install -r requirements-cv.txt

# Configure environment
cp .env.example .env
nano .env  # Add PINECONE_API_KEY

# Run service
python main.py
# Or with uvicorn: uvicorn main:app --host 0.0.0.0 --port 8001
```

**Verify GPU:**
```bash
python -c "import torch; print(f'CUDA available: {torch.cuda.is_available()}')"
nvidia-smi  # Should show T4 GPU
```

### 2. Deploy Main Backend (Current Instance)

**On your current EC2:**
```bash
# Pull latest code
git pull

# Install lightweight dependencies (NO PyTorch)
pip install -r requirements-backend.txt

# Add CV service URL to .env
echo "CV_SERVICE_URL=http://<cv-instance-private-ip>:8001" >> .env

# Restart your backend
# (however you currently run it - systemd, pm2, etc.)
```

### 3. Test Integration

**Test CV service directly:**
```bash
curl http://<cv-instance-ip>:8001/health
# Should return: {"status": "healthy"}
```

**Test from main backend:**
```python
from services.cv_client import get_cv_client

cv_client = get_cv_client()
health = await cv_client.health_check()
print(f"CV service health: {health}")
```

## File Structure

```
GlowBack/
├── requirements-backend.txt        # Main backend (lightweight)
├── api/
│   ├── outfit_endpoints.py
│   └── cv_example.py              # Integration examples
├── services/
│   └── cv_client.py               # HTTP client for CV service
├── .env                           # Add: CV_SERVICE_URL
└── cv_service/                    # Deploy this to GPU instance
    ├── requirements-cv.txt        # CV service (with PyTorch GPU)
    ├── main.py                    # FastAPI CV service
    ├── README.md                  # Detailed CV setup guide
    └── product_retrival_computer_vision/
```

## Environment Variables

### Main Backend (.env)
```bash
# Existing vars...
ANTHROPIC_API_KEY=...
DATABASE_URL=...

# Add this:
CV_SERVICE_URL=http://10.0.1.50:8001  # Private IP of CV instance
```

### CV Service (cv_service/.env)
```bash
PINECONE_API_KEY=your_key_here
SERPAPI_API_KEY=your_key_here  # Optional
```

## Security

**Recommended Security Group Setup:**

**Main Backend SG:**
- Port 80/443: Public (HTTPS)
- Port 8000: Your load balancer/internal
- Outbound: Allow to CV instance on port 8001

**CV Service SG:**
- Port 8001: Only from Main Backend SG
- No public internet access needed (except for Pinecone/API calls)

Use **private IPs** for CV_SERVICE_URL for better security and no data transfer costs.

## Cost Breakdown

| Component | Instance | Monthly Cost |
|-----------|----------|--------------|
| Main Backend | t3.medium | ~$30 |
| CV Service | g4dn.xlarge | ~$390 |
| **Total** | | **~$420/month** |

**Cost Optimization:**
- Use Spot Instances for CV (save ~70%): ~$120/month
- Scale down during low traffic hours
- Use Reserved Instances for 1-year commitment (save ~40%)

## Monitoring

**Check CV service logs:**
```bash
# On CV instance
sudo journalctl -u cv-service -f  # If using systemd
```

**Monitor GPU usage:**
```bash
watch -n 1 nvidia-smi
```

**Health check endpoint:**
```bash
curl http://<cv-instance>:8001/health
```

## Troubleshooting

### CV service not reachable from main backend
1. Check security group allows port 8001
2. Use private IP in CV_SERVICE_URL
3. Ensure CV service is running: `curl localhost:8001/health`

### GPU not being used
```bash
# Check if CUDA is available
python -c "import torch; print(torch.cuda.is_available())"

# If False, reinstall PyTorch with CUDA
pip uninstall torch torchvision
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121
```

### Out of memory errors
- Reduce image resolution in detector
- Use smaller batch sizes
- Upgrade to g4dn.2xlarge (32GB RAM)

## Production Checklist

- [ ] CV service running with GPU enabled
- [ ] Main backend can reach CV service
- [ ] Environment variables configured on both instances
- [ ] Security groups properly configured
- [ ] Health checks passing
- [ ] Logs being collected/monitored
- [ ] Backups configured for main backend
- [ ] Cost alerts set up in AWS

## Next Steps

1. Set up systemd service for CV service (see cv_service/README.md)
2. Configure auto-scaling for main backend
3. Add CloudWatch monitoring
4. Set up CI/CD pipeline
5. Configure domain + SSL certificates

For detailed CV service setup, see `cv_service/README.md`
