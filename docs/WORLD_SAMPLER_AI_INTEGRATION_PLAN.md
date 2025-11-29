# World Sampler AI Integration Plan
## Integrating Image Segmentation & Object Detection with Viewport Analysis

**Date:** November 27, 2025  
**Status:** Planning Phase

---

## 🎯 Overview

Integrate existing segmentation and object detection capabilities with World Sampler to automatically analyze viewport imagery at sample locations. This will enable AI-powered feedback for the adaptive sampling system.

---

## ✅ Existing Code Available

### 1. **Zero-Shot Object Detection** (`dreams_laboratory/scripts/zero_shot_detection.py`)

**Capabilities:**
- Pre-trained Mask R-CNN / Mask2Former
- 80 COCO categories (person, car, bicycle, etc.)
- No training required
- Instant results

**Use Cases for World Sampler:**
- Detect vehicles, people, structures in viewport
- Identify common objects at sample locations
- Quick analysis of field photos

**Limitations:**
- Only 80 predefined categories
- Won't detect geological features, rocks, minerals
- May have false positives on textures

### 2. **Segment Anything Model (SAM)** (`dreams_laboratory/scripts/segment_anything_rocks.py`)

**Capabilities:**
- Universal segmentation (works on ANY image)
- No training required
- Finds all regions, boundaries, fractures
- High-quality segmentation masks

**Use Cases for World Sampler:**
- Segment all regions in viewport imagery
- Find boundaries and features automatically
- Pre-labeling for faster annotation
- Exploratory analysis of sample locations

**Limitations:**
- No class labels (just "segment_1", "segment_2", etc.)
- Requires manual classification after segmentation

### 3. **Custom Mask2Former** (`dreams_laboratory/scripts/train_mask2former_deepgis.py`)

**Capabilities:**
- Custom class labels (trainable)
- Domain-specific knowledge
- Best accuracy on specific data
- Production-ready

**Use Cases for World Sampler:**
- Detect custom categories (rocks, minerals, geological features)
- High-accuracy detection after training
- Production deployment

**Limitations:**
- Requires labeled training data (100+ images)
- Training time (2-6 hours)
- Must train before use

### 4. **Existing API Endpoints**

**Found in `deepgis-xr/deepgis_xr/apps/web/views.py`:**
- `generate_assisted_labels()` - Already exists!
- Endpoint: `/label/semi-supervised/api/generate-labels/`
- Uses `segmentation_assisted_labeling.py`
- Returns GeoJSON with predictions

---

## 🏗️ Integration Architecture

### Proposed Workflow

```
World Sampler Sample Location
    ↓
Capture Viewport Image (Cesium canvas)
    ↓
Send to AI Analysis API
    ↓
Run Segmentation/Detection
    ↓
Return Results (GeoJSON + metadata)
    ↓
Display on Map + Update Sampler Feedback
```

### Components Needed

1. **Viewport Image Capture**
   - Capture Cesium canvas as image
   - Include camera pose metadata
   - Send to backend API

2. **AI Analysis API Endpoint**
   - New endpoint: `/api/v1/sampler/analyze-viewport/`
   - Accepts image + location metadata
   - Runs segmentation/detection
   - Returns results

3. **Frontend Integration**
   - Add "Analyze Viewport" button in World Sampler
   - Display detection results on map
   - Use results for adaptive sampling feedback

---

## 📋 Implementation Plan

### Phase 1: Viewport Capture

**File:** `deepgis-xr/staticfiles/web/js/world-sampler-ui.js`

```javascript
captureViewportImage() {
    // Capture Cesium canvas
    const canvas = this.viewer.scene.canvas;
    const imageData = canvas.toDataURL('image/png');
    
    // Get camera pose
    const camera = this.viewer.camera;
    const position = camera.positionCartographic;
    
    return {
        image: imageData,
        location: {
            lon: Cesium.Math.toDegrees(position.longitude),
            lat: Cesium.Math.toDegrees(position.latitude),
            alt: position.height,
            heading: Cesium.Math.toDegrees(camera.heading),
            pitch: Cesium.Math.toDegrees(camera.pitch)
        }
    };
}
```

### Phase 2: API Endpoint

**File:** `deepgis-xr/deepgis_xr/apps/web/world_sampler_api.py`

```python
@require_http_methods(["POST"])
@csrf_exempt
def analyze_viewport(request):
    """
    Analyze viewport image using AI segmentation/detection.
    
    POST data:
    - image: base64 encoded image
    - location: {lon, lat, alt, heading, pitch}
    - model_type: 'zero_shot', 'sam', or 'mask2former'
    - confidence_threshold: float (0.0-1.0)
    
    Returns:
    - detections: GeoJSON with detected objects/regions
    - metadata: analysis results, confidence scores
    """
    # 1. Decode base64 image
    # 2. Load appropriate model
    # 3. Run inference
    # 4. Convert to GeoJSON
    # 5. Return results
```

### Phase 3: Frontend Integration

**Add to World Sampler UI:**

```javascript
// In Survey Points section
<button class="btn btn-info" id="analyzeViewportBtn">
    <i class="fas fa-brain"></i> Analyze Viewport (AI)
</button>

// Event handler
analyzeViewportBtn.addEventListener('click', async () => {
    const viewportData = this.captureViewportImage();
    const results = await this.analyzeViewport(viewportData);
    this.displayDetectionResults(results);
    this.updateSamplerFeedback(results);
});
```

---

## 🔧 Technical Details

### Model Selection Strategy

1. **Quick Analysis (Default)**
   - Use **SAM** for universal segmentation
   - Fast, no training needed
   - Finds all regions

2. **Object Detection**
   - Use **Zero-Shot COCO** for common objects
   - Good for vehicles, people, structures
   - Instant results

3. **Custom Detection (If Available)**
   - Use **Custom Mask2Former** if trained
   - Best for domain-specific features
   - Requires trained model

### API Integration

**Reuse Existing Code:**
- `dreams_laboratory/scripts/zero_shot_detection.py`
- `dreams_laboratory/scripts/segment_anything_rocks.py`
- `dreams_laboratory/scripts/segmentation_assisted_labeling.py`

**New Endpoint:**
```python
# deepgis-xr/deepgis_xr/apps/web/world_sampler_api.py

@require_http_methods(["POST"])
@csrf_exempt
def analyze_viewport(request):
    import base64
    import io
    from PIL import Image
    import sys
    from pathlib import Path
    
    # Import segmentation scripts
    project_root = Path(__file__).parent.parent.parent.parent.parent
    scripts_dir = project_root / 'dreams_laboratory' / 'scripts'
    sys.path.insert(0, str(scripts_dir))
    
    data = json.loads(request.body)
    image_data = data.get('image')  # base64
    model_type = data.get('model_type', 'sam')
    
    # Decode image
    image_bytes = base64.b64decode(image_data.split(',')[1])
    image = Image.open(io.BytesIO(image_bytes))
    
    # Run analysis based on model type
    if model_type == 'zero_shot':
        from zero_shot_detection import ZeroShotMaskRCNN
        detector = ZeroShotMaskRCNN()
        results = detector.predict(image)
    elif model_type == 'sam':
        from segment_anything_rocks import SegmentAnythingRocks
        segmenter = SegmentAnythingRocks()
        results = segmenter.segment_image(image)
    # ... etc
    
    return JsonResponse({
        'success': True,
        'detections': results,
        'model_type': model_type
    })
```

---

## 🎨 UI Integration

### World Sampler Panel Additions

**Location:** Survey Points section (after Drone Fly Mode)

```html
<!-- AI Analysis Section -->
<div class="form-group" style="border-top: 1px solid #475569; padding-top: 12px; margin-top: 12px;">
    <h5 style="font-size: 13px; color: #60a5fa; margin-bottom: 8px;">
        <i class="fas fa-brain"></i> AI Viewport Analysis
    </h5>
    <div class="form-group">
        <label>Model:</label>
        <select id="aiModelSelect" class="form-control">
            <option value="sam">Segment Anything (Universal)</option>
            <option value="zero_shot">Zero-Shot COCO (Objects)</option>
            <option value="mask2former">Custom Mask2Former (If Available)</option>
        </select>
    </div>
    <div class="form-group">
        <label>Confidence Threshold:</label>
        <input type="range" id="aiConfidence" class="form-range" 
               min="0" max="100" step="5" value="50">
        <span id="aiConfidenceValue">0.5</span>
    </div>
    <button class="btn btn-info w-100" id="analyzeViewportBtn">
        <i class="fas fa-brain"></i> Analyze Current Viewport
    </button>
    <small class="text-muted" style="display: block; margin-top: 6px; font-size: 11px;">
        Analyzes visible imagery using AI segmentation/detection
    </small>
</div>
```

### Results Display

- Show detection results as overlays on Cesium map
- Display confidence scores
- Allow filtering by confidence
- Export results as GeoJSON

---

## 📊 Use Cases

### 1. **Adaptive Sampling Feedback**

Use AI analysis results to provide automatic feedback:
- High object/feature density → High reward
- Interesting regions detected → Increase sampling weight
- Empty/boring areas → Decrease sampling weight

### 2. **Quality Assessment**

Automatically assess sample location quality:
- Rich in features → Good sample
- Feature-poor → Skip or low priority

### 3. **Exploratory Analysis**

Use SAM to explore unknown regions:
- Segment all visible features
- Identify interesting boundaries
- Guide manual inspection

---

## 🚀 Quick Start Integration

### Step 1: Add Viewport Capture

```javascript
// In world-sampler-ui.js
captureViewportImage() {
    const canvas = this.viewer.scene.canvas;
    return canvas.toDataURL('image/png');
}
```

### Step 2: Create API Endpoint

```python
# In world_sampler_api.py
@require_http_methods(["POST"])
@csrf_exempt
def analyze_viewport(request):
    # Use existing segmentation scripts
    # Return GeoJSON results
```

### Step 3: Add UI Button

```html
<!-- In World Sampler Survey Points section -->
<button id="analyzeViewportBtn">Analyze Viewport (AI)</button>
```

### Step 4: Connect Everything

```javascript
// Event handler
analyzeViewportBtn.addEventListener('click', async () => {
    const image = this.captureViewportImage();
    const results = await fetch('/api/v1/sampler/analyze-viewport/', {
        method: 'POST',
        body: JSON.stringify({ image, model_type: 'sam' })
    });
    this.displayResults(results);
});
```

---

## 📁 File Locations

### Existing Code:
- `dreams_laboratory/scripts/zero_shot_detection.py`
- `dreams_laboratory/scripts/segment_anything_rocks.py`
- `dreams_laboratory/scripts/segmentation_assisted_labeling.py`
- `deepgis-xr/deepgis_xr/apps/web/views.py` (has `generate_assisted_labels`)

### New Files Needed:
- `deepgis-xr/deepgis_xr/apps/web/world_sampler_api.py` (add `analyze_viewport`)
- `deepgis-xr/staticfiles/web/js/world-sampler-ui.js` (add capture & display)

---

## 🎯 Recommended Approach

### For Immediate Integration:

1. **Start with SAM** (Segment Anything)
   - No training needed
   - Works on any imagery
   - Fast results
   - Good for exploration

2. **Add Zero-Shot COCO** as option
   - For common object detection
   - Quick to implement
   - Useful for field photos

3. **Later: Custom Mask2Former**
   - After training custom model
   - Best accuracy
   - Production deployment

---

## ✅ Next Steps

1. ✅ **Documentation** - This file
2. ⏳ **Viewport Capture** - Implement canvas capture
3. ⏳ **API Endpoint** - Create analyze_viewport endpoint
4. ⏳ **Frontend Integration** - Add UI and display results
5. ⏳ **Testing** - Test with real viewport imagery
6. ⏳ **Feedback Loop** - Use results for adaptive sampling

---

**Status:** Ready for implementation  
**Priority:** High (enables AI-powered sampling)  
**Estimated Time:** 4-6 hours for basic integration

