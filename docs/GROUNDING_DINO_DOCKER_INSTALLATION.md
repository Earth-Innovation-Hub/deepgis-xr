# Grounding DINO Docker Installation Guide

## Quick Start - Rebuild Container

The Dockerfile has been updated to include Grounding DINO. Simply rebuild:

```bash
cd /home/jdas/dreams-lab-website-server/deepgis-xr

# Rebuild the web container
docker-compose build web

# Start the container
docker-compose up -d

# Verify installation
docker exec deepgis-xr_web_1 python -c "from groundingdino.util.inference import load_model; print('✓ Grounding DINO installed!')"
```

## What Gets Installed

### System Dependencies
- `ninja-build` - Required for building Grounding DINO extensions

### Python Package
- Grounding DINO from GitHub (source installation)
- Installed AFTER torch/torchvision/detectron2 for compatibility

### Model Weights Directory
- `/app/models/` - Created for storing downloaded model checkpoints
- Models auto-download on first use (~700-900MB)

## Installation Order (Critical)

The Dockerfile installs in this specific order:

1. ✅ GDAL (system + Python bindings)
2. ✅ Base requirements (torch, torchvision, etc.)
3. ✅ Fiona (after GDAL)
4. ✅ Detectron2 (after torch)
5. ✅ **Grounding DINO (after detectron2)** ← NEW!

This order is critical because:
- Detectron2's setup.py imports torch (must exist first)
- Grounding DINO needs torch/torchvision CUDA support
- Building happens with existing CUDA toolkit

## Verification Steps

### 1. Check Installation

```bash
docker exec deepgis-xr_web_1 python -c "
from groundingdino.util.inference import load_model, predict
print('✓ Grounding DINO successfully installed')
"
```

### 2. Test Detection

```bash
docker exec deepgis-xr_web_1 python /app/dreams_laboratory_scripts/grounding_dino_detection.py \
  /app/media/test_image.jpg \
  --prompt 'car . tree . building' \
  --output /app/media/test_output.jpg
```

### 3. Check GPU Support

```bash
docker exec deepgis-xr_web_1 python -c "
import torch
print('CUDA available:', torch.cuda.is_available())
print('GPU:', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'N/A')
"
```

## Troubleshooting

### Build Fails - "ninja: not found"

Add to Dockerfile before Grounding DINO install:
```dockerfile
RUN apt-get update && apt-get install -y ninja-build
```
✅ Already included in updated Dockerfile!

### Build Fails - "torch not found"

Ensure requirements.txt is installed first:
```dockerfile
RUN pip install -r requirements.txt
# Then install detectron2
# Then install Grounding DINO
```
✅ Already in correct order!

### CUDA Errors

Make sure docker-compose.yml has GPU support:
```yaml
deploy:
  resources:
    reservations:
      devices:
        - driver: nvidia
          count: 1
          capabilities: [gpu]
```
✅ Already configured!

### Model Download Fails

Manually download models:
```bash
# Inside container
docker exec -it deepgis-xr_web_1 bash

# Download Swin-T model
cd /app/models
wget https://github.com/IDEA-Research/GroundingDINO/releases/download/v0.1.0-alpha/groundingdino_swint_ogc.pth

# Download Swin-B model (optional, larger/better)
wget https://github.com/IDEA-Research/GroundingDINO/releases/download/v0.1.0-alpha2/groundingdino_swinb_cogcoor.pth
```

### Import Errors

```bash
# Check if GroundingDINO directory exists in container
docker exec deepgis-xr_web_1 find / -name "GroundingDINO" -type d 2>/dev/null

# Check Python path
docker exec deepgis-xr_web_1 python -c "import sys; print('\n'.join(sys.path))"
```

## Alternative: Install Without Rebuild

If you want to test without rebuilding the entire container:

```bash
# Enter container
docker exec -it deepgis-xr_web_1 bash

# Install dependencies
apt-get update
apt-get install -y ninja-build git

# Clone and install
cd /tmp
git clone https://github.com/IDEA-Research/GroundingDINO.git
cd GroundingDINO
pip install -e .

# Create models directory
mkdir -p /app/models

# Restart Django
supervisorctl restart web  # or just exit and restart container
```

**Note:** This won't persist after container restarts. Use rebuild for permanent installation.

## Memory Requirements

### Minimum
- **GPU:** 4 GB VRAM (for Swin-T)
- **RAM:** 8 GB
- **Disk:** 2 GB (for model weights)

### Recommended
- **GPU:** 8+ GB VRAM (for Swin-B)
- **RAM:** 16 GB
- **Disk:** 5 GB (for multiple models + cache)

## Performance Expectations

### Swin-T Model (Default)
- **Speed:** 2-5 seconds per image (GPU)
- **Accuracy:** Very good
- **Size:** ~700 MB

### Swin-B Model
- **Speed:** 5-10 seconds per image (GPU)
- **Accuracy:** Excellent
- **Size:** ~900 MB

### CPU Mode
- **Speed:** 15-40 seconds per image
- Works but significantly slower
- Good for testing/development

## Testing After Installation

### 1. Web Interface Test
1. Navigate to: `https://deepgis.org/label/3d/search/`
2. Open "AI Viewport Analysis" panel
3. Select "Grounding DINO (Text-Based Detection) ⭐"
4. Enter prompt: `building . vehicle . tree`
5. Click "Analyze Viewport"
6. Should see detections appear!

### 2. Backend API Test

```bash
# From inside container
docker exec -it deepgis-xr_web_1 python manage.py shell

# Then in Python shell:
from PIL import Image
from dreams_laboratory.scripts.grounding_dino_detection import GroundingDINODetector

detector = GroundingDINODetector(model_type='swin_t', device='cuda')
image = Image.open('/app/media/test_image.jpg')
results = detector.detect(image, text_prompt='car . tree', box_threshold=0.35)
print(f"Found {results['num_detections']} objects")
```

## Dockerfile Changes Summary

**Added to Dockerfile:**
1. `ninja-build` system package
2. Grounding DINO git clone and pip install
3. `/app/models` directory creation

**Installation happens after:**
- ✅ torch/torchvision (required)
- ✅ detectron2 (for compatibility)
- ✅ All other requirements

## Size Impact

**Total Docker image size increase:**
- Grounding DINO package: ~100 MB
- Model weights (downloaded on first use): ~700-900 MB
- Total: ~1 GB additional space

## Next Steps After Installation

1. **Rebuild container:**
   ```bash
   docker-compose build web
   docker-compose up -d
   ```

2. **Verify installation:**
   ```bash
   docker exec deepgis-xr_web_1 python -c "from groundingdino.util.inference import load_model; print('OK')"
   ```

3. **Test in web interface:**
   - Go to DeepGIS Search
   - Try Grounding DINO detection
   - First run will download model (~700MB)
   - Subsequent runs will be faster

4. **Monitor first run:**
   ```bash
   docker logs -f deepgis-xr_web_1
   ```
   Look for: "Downloading model..." then "✓ Model loaded"

## Date
2025-11-29

