# GroundingDINO CUDA Enablement Plan

## Quick Reference

**Current Setup:**
- PyTorch: 2.8.0+cu128 (CUDA 12.8)
- Base Image: `ubuntu:20.04` (no CUDA toolkit)
- Status: CPU mode working, CUDA extensions not compiled

**Target Setup:**
- Base Image: `nvidia/cuda:12.3.0-cudnn8-devel-ubuntu20.04` (preferred, matches openuav-turbovnc pattern)
- Alternative: `nvidia/cuda:12.1.0-cudnn8-devel-ubuntu20.04` (if 12.3 not available for Ubuntu 20.04)
- CUDA Toolkit: 12.3.x or 12.1.x (compatible with PyTorch CUDA 12.8)
- Expected Speedup: 3-5x faster detection

**Reference Implementation:**
- Found in `/home/jdas/openuav-turbovnc/autonomous_sys_build/Dockerfile.base`
- Uses: `nvidia/cuda:12.3.0-devel-ubuntu22.04` (Ubuntu 22.04 version)
- Note: Adapt for Ubuntu 20.04 (deepgis-xr requirement)

**Estimated Time:** 4-7 hours

## Current Status

### ✅ What's Working
- GroundingDINO is installed and functional in CPU mode
- API has automatic CPU fallback if CUDA fails
- Container has GPU access configured in docker-compose.yml
- PyTorch CUDA support is available at runtime

### ❌ What's Missing
- CUDA Toolkit (nvcc compiler) not installed in build environment
- CUDA extensions (`_C` module) not compiled during build
- Base Docker image doesn't include CUDA development tools

## Requirements

### Hardware
- ✅ NVIDIA GPU available (verified: CUDA available at runtime)
- ✅ GPU access configured in docker-compose.yml

### Software
- ❌ CUDA Toolkit (12.8 recommended - matches PyTorch CUDA 12.8)
- ❌ CUDA development libraries (cudnn, etc.)
- ✅ PyTorch with CUDA support (already installed - PyTorch 2.8.0+cu128)
- ✅ ninja-build (already installed)

**Note:** Current PyTorch uses CUDA 12.8, so Docker image should use CUDA 12.x

## Implementation Plan

### Phase 1: Update Dockerfile Base Image

**Current:** `FROM ubuntu:20.04` (no CUDA)

**Proposed:** Use NVIDIA CUDA base image with development tools

```dockerfile
# Option A: Full CUDA development image (recommended)
# Based on openuav-turbovnc pattern: nvidia/cuda:12.3.0-devel-ubuntu22.04
# Adapted for Ubuntu 20.04 (deepgis-xr requirement)
FROM nvidia/cuda:12.3.0-cudnn8-devel-ubuntu20.04

# Option B: Alternative CUDA 12.1 (if 12.3 not available for Ubuntu 20.04)
# FROM nvidia/cuda:12.1.0-cudnn8-devel-ubuntu20.04

# Option C: Runtime + install dev tools separately (smaller, more control)
# FROM nvidia/cuda:12.3.0-cudnn8-runtime-ubuntu20.04
# RUN apt-get update && apt-get install -y \
#     cuda-toolkit-12-3 \
#     libcudnn8-dev \
#     && apt-get clean
```

**Reference:** The `openuav-turbovnc` project uses `nvidia/cuda:12.3.0-devel-ubuntu22.04` pattern.

**Important:** 
- PyTorch uses CUDA 12.8, Docker images use 12.3.x or 12.1.x
- CUDA 12.x versions are backward compatible
- Ubuntu 20.04 compatibility: Check if `12.3.0-devel-ubuntu20.04` exists, otherwise use `12.1.0`

**Decision needed:** Choose base image strategy
- **Option A**: Simpler, includes everything, larger image (~3GB+)
- **Option B**: More control, smaller base, need to install toolkit

### Phase 2: Set CUDA Environment Variables

Add to Dockerfile after base image:

```dockerfile
# Set CUDA environment variables
ENV CUDA_HOME=/usr/local/cuda
ENV PATH=${CUDA_HOME}/bin:${PATH}
ENV LD_LIBRARY_PATH=${CUDA_HOME}/lib64:${LD_LIBRARY_PATH}
ENV CUDA_VISIBLE_DEVICES=0

# Verify CUDA installation
RUN nvcc --version && \
    python -c "import torch; print('PyTorch CUDA:', torch.version.cuda)"
```

### Phase 3: Update GroundingDINO Installation

Modify the GroundingDINO installation step to ensure CUDA extensions compile:

```dockerfile
# Install Grounding DINO with CUDA support
RUN git clone https://github.com/IDEA-Research/GroundingDINO.git /app/GroundingDINO && \
    cd /app/GroundingDINO && \
    # Set environment for CUDA compilation
    export CUDA_HOME=/usr/local/cuda && \
    export PATH=${CUDA_HOME}/bin:${PATH} && \
    export LD_LIBRARY_PATH=${CUDA_HOME}/lib64:${LD_LIBRARY_PATH} && \
    # Build with CUDA support
    MAX_JOBS=4 pip install --no-cache-dir -e . && \
    # Verify CUDA ops compiled
    python -c "from groundingdino.models.GroundingDINO import ms_deform_attn; \
               assert hasattr(ms_deform_attn, '_C'), 'CUDA ops not compiled!'; \
               print('✓ CUDA extensions compiled successfully')" || \
    (echo "ERROR: CUDA extensions failed to compile" && exit 1)
```

### Phase 4: Update docker-compose.yml (if needed)

Current GPU configuration looks good, but verify:

```yaml
deploy:
  resources:
    reservations:
      devices:
        - driver: nvidia
          count: 1
          capabilities: [gpu]
```

**Note:** May need to add runtime if deploy doesn't work:
```yaml
runtime: nvidia
```

### Phase 5: Update API Code (Optional Enhancement)

The current fallback is good, but we can add better logging:

```python
# In world_sampler_api.py
if cuda_available:
    try:
        detector = GroundingDINODetector(model_type='swin_t', device='cuda')
        print("✓ GroundingDINO initialized with CUDA acceleration")
    except Exception as e:
        print(f"⚠ CUDA initialization failed: {e}")
        print("⚠ Falling back to CPU mode (slower but functional)")
        device = 'cpu'
        detector = GroundingDINODetector(model_type='swin_t', device='cpu')
else:
    device = 'cpu'
    detector = GroundingDINODetector(model_type='swin_t', device='cpu')
```

## Step-by-Step Implementation

### Step 1: Backup Current Setup
```bash
cd /home/jdas/dreams-lab-website-server/deepgis-xr
cp Dockerfile Dockerfile.cpu-backup
cp docker-compose.yml docker-compose.yml.backup
```

### Step 2: Choose CUDA Base Image
- ✅ PyTorch CUDA version: 12.8 (verified)
- ✅ Reference pattern from `openuav-turbovnc`: `nvidia/cuda:12.3.0-devel-ubuntu22.04`
- ✅ Recommended for deepgis-xr: `nvidia/cuda:12.3.0-cudnn8-devel-ubuntu20.04` (if available)
- ✅ Alternative: `nvidia/cuda:12.1.0-cudnn8-devel-ubuntu20.04` (fallback)
- Note: CUDA 12.3.x/12.1.x are compatible with PyTorch CUDA 12.8 (backward compatible)

### Step 3: Update Dockerfile
- Replace base image with CUDA-enabled version
- Add CUDA environment variables
- Update GroundingDINO installation step
- Test build incrementally

### Step 4: Rebuild Container
```bash
# Clean build (no cache to ensure fresh CUDA compilation)
docker-compose build --no-cache web

# Or incremental build
docker-compose build web
```

### Step 5: Verify CUDA Extensions
```bash
# Start container
docker-compose up -d

# Check CUDA toolkit
docker exec deepgis-xr_web_1 nvcc --version

# Check CUDA extensions
docker exec deepgis-xr_web_1 python -c "
from groundingdino.models.GroundingDINO import ms_deform_attn
print('CUDA ops available:', hasattr(ms_deform_attn, '_C'))
"

# Test detector initialization
docker exec deepgis-xr_web_1 python -c "
import sys
sys.path.insert(0, '/app/dreams_laboratory_scripts')
from grounding_dino_detection import GroundingDINODetector
detector = GroundingDINODetector(model_type='swin_t', device='cuda')
print('✓ CUDA detector initialized successfully')
"
```

### Step 6: Performance Testing
```bash
# Test detection speed comparison
docker exec deepgis-xr_web_1 python -c "
import time
import sys
sys.path.insert(0, '/app/dreams_laboratory_scripts')
from grounding_dino_detection import GroundingDINODetector
from PIL import Image

test_img = Image.new('RGB', (1920, 1080), color='white')

# CPU test
print('Testing CPU mode...')
detector_cpu = GroundingDINODetector(model_type='swin_t', device='cpu')
start = time.time()
results_cpu = detector_cpu.detect(test_img, 'rectangle', 0.25, 0.20)
cpu_time = time.time() - start
print(f'CPU time: {cpu_time:.2f}s')

# CUDA test
print('Testing CUDA mode...')
detector_cuda = GroundingDINODetector(model_type='swin_t', device='cuda')
start = time.time()
results_cuda = detector_cuda.detect(test_img, 'rectangle', 0.25, 0.20)
cuda_time = time.time() - start
print(f'CUDA time: {cuda_time:.2f}s')
print(f'Speedup: {cpu_time/cuda_time:.2f}x')
"
```

## Testing Checklist

### Build Phase
- [ ] Dockerfile builds without errors
- [ ] CUDA toolkit is installed (`nvcc --version`)
- [ ] CUDA extensions compile successfully
- [ ] No warnings about missing CUDA ops

### Runtime Phase
- [ ] Container starts successfully
- [ ] GPU is accessible (`nvidia-smi` in container)
- [ ] PyTorch detects CUDA (`torch.cuda.is_available()`)
- [ ] GroundingDINO CUDA ops are available (`hasattr(ms_deform_attn, '_C')`)
- [ ] Detector initializes with CUDA device
- [ ] Detection runs without errors
- [ ] Performance improvement verified (2-5x faster)

### Integration Phase
- [ ] API endpoint works with CUDA
- [ ] Fallback to CPU still works if CUDA fails
- [ ] No memory leaks during extended use
- [ ] Multiple concurrent requests handled correctly

## Rollback Strategy

If CUDA enablement causes issues:

### Quick Rollback
```bash
# Restore backup files
cp Dockerfile.cpu-backup Dockerfile
cp docker-compose.yml.backup docker-compose.yml

# Rebuild with CPU-only version
docker-compose build web
docker-compose up -d
```

### Partial Rollback
Keep CUDA base image but force CPU mode:
```python
# In world_sampler_api.py, force CPU:
device = 'cpu'  # Force CPU mode
detector = GroundingDINODetector(model_type='swin_t', device='cpu')
```

## Potential Issues & Solutions

### Issue 1: CUDA Version Mismatch
**Symptom:** `CUDA runtime version mismatch` or `CUDA driver version is insufficient`

**Solution:**
- Check host CUDA version: `nvidia-smi`
- Match Docker image CUDA version to host
- Use compatible PyTorch CUDA version

### Issue 2: CUDA Extensions Don't Compile
**Symptom:** Build fails with compilation errors

**Solution:**
- Check CUDA toolkit is installed: `nvcc --version`
- Verify environment variables are set
- Check GroundingDINO requirements
- Try building extensions manually first

### Issue 3: Out of Memory
**Symptom:** `CUDA out of memory` errors

**Solution:**
- Reduce batch size in detection
- Use smaller model (swin_t instead of swin_b)
- Limit concurrent requests
- Add memory monitoring

### Issue 4: Slower Than CPU
**Symptom:** CUDA mode is actually slower

**Solution:**
- Check GPU utilization: `nvidia-smi`
- Verify CUDA extensions are being used
- Check for CPU-GPU transfer bottlenecks
- Ensure batch processing is used

## Performance Expectations

### CPU Mode (Current)
- Detection time: 10-30 seconds per image (1920x1080)
- Memory: 8-12 GB system RAM
- Throughput: ~2-3 images/minute

### CUDA Mode (Target)
- Detection time: 2-5 seconds per image (1920x1080)
- Memory: 4-6 GB GPU RAM + 4-6 GB system RAM
- Throughput: ~10-20 images/minute
- **Expected speedup: 3-5x faster**

## Timeline Estimate

- **Phase 1-2 (Dockerfile updates)**: 1-2 hours
- **Phase 3 (Build & test)**: 2-3 hours
- **Phase 4 (Integration testing)**: 1-2 hours
- **Total**: 4-7 hours

## Next Steps

1. **While testing CPU mode:**
   - Test API endpoints
   - Verify detection accuracy
   - Document any issues

2. **When ready for CUDA:**
   - Review this plan
   - Choose base image strategy (Option A or B)
   - Update Dockerfile
   - Build and test incrementally
   - Monitor performance improvements

## References

- [GroundingDINO GitHub](https://github.com/IDEA-Research/GroundingDINO)
- [NVIDIA CUDA Docker Images](https://hub.docker.com/r/nvidia/cuda)
- [PyTorch CUDA Compatibility](https://pytorch.org/get-started/previous-versions/)
- [Docker GPU Access](https://docs.docker.com/config/containers/resource_constraints/#gpu)
- **Reference Implementation**: `/home/jdas/openuav-turbovnc/autonomous_sys_build/Dockerfile.base` uses `nvidia/cuda:12.3.0-devel-ubuntu22.04`

