# Grounding DINO Setup Guide

## What is Grounding DINO?

Grounding DINO is a revolutionary object detection model that allows you to detect ANY object by describing it in text. Unlike traditional detectors limited to 80-90 fixed classes (COCO), Grounding DINO can find anything you describe.

**Examples:**
- "damaged roof . crack . corrosion"
- "solar panel . wind turbine"
- "vehicle . construction equipment"  
- "person . bicycle . motorcycle"
- "tree . vegetation . forest"

## Installation

### Option 1: Using pip (Recommended)

```bash
pip install groundingdino-py
```

### Option 2: From source (More control)

```bash
# Clone repository
git clone https://github.com/IDEA-Research/GroundingDINO.git
cd GroundingDINO

# Install dependencies
pip install -e .
```

### Option 3: Docker Installation

Add to your `Dockerfile`:

```dockerfile
# Install Grounding DINO
RUN pip install groundingdino-py
```

Then rebuild:

```bash
docker-compose build web
docker-compose up -d
```

## Model Download

Models are auto-downloaded on first use:

1. **Swin-T (default)** - ~700MB - Faster, good accuracy
2. **Swin-B** - ~900MB - Best accuracy, slower

Stored in: `/app/models/` or `~/.cache/groundingdino/`

## Usage in DeepGIS

### 1. Navigate to DeepGIS Search
```
https://deepgis.org/label/3d/search/
```

### 2. Open AI Viewport Analysis Panel
- Click the accordion to expand

### 3. Select Grounding DINO
- **Analysis Type:** Select "Grounding DINO (Text-Based Detection) ⭐"

### 4. Configure Detection
- **Text Prompt:** Type what you want to find
  - Examples:
    - `vehicle . building`
    - `solar panel . roof . window`
    - `tree . bush . grass`
    - `damaged structure . crack`
    - `person . bicycle . motorcycle`
  
- **Box Confidence:** 10-80% (default: 35%)
  - Higher = fewer, more confident detections
  - Lower = more detections, some false positives
  
- **Text Match:** 10-50% (default: 25%)
  - How well text must match visual features
  - Higher = stricter matching

### 5. Click "Analyze Viewport"

### 6. View Results
- Bounding boxes appear on viewport
- Click "View Detailed Report" for full analysis

## Text Prompt Tips

### Format
Use " . " (space-dot-space) to separate objects:
```
object1 . object2 . object3
```

### Good Prompts
✅ `vehicle` - Finds all vehicles
✅ `car . truck . bus` - Multiple specific types
✅ `solar panel` - Specific objects
✅ `damaged building` - With adjectives
✅ `green vegetation` - With colors

### Bad Prompts
❌ `vehicle, car, truck` - Use dots, not commas
❌ `vehicles` - Singular usually works better
❌ `find all cars` - Just the object name
❌ `car.truck.bus` - Need spaces around dots

## Examples for Geospatial Analysis

### Urban Planning
```
building . road . parking lot . sidewalk
```

### Infrastructure Inspection
```
damaged roof . crack . corrosion . debris
```

### Environmental Monitoring
```
tree . water body . vegetation . bare ground
```

### Agricultural
```
crop field . irrigation system . greenhouse . farm equipment
```

### Disaster Response
```
damaged structure . debris . collapsed building . road blockage
```

### Energy Infrastructure
```
solar panel . wind turbine . power line . substation
```

## Performance

- **GPU (CUDA)**: ~2-5 seconds per image
- **CPU**: ~10-30 seconds per image
- **Memory**: 4-6 GB GPU RAM, 8-12 GB system RAM

## Troubleshooting

### "Grounding DINO not installed"
```bash
pip install groundingdino-py
# or
cd GroundingDINO && pip install -e .
```

### Model download fails
```bash
# Manually download models
wget https://github.com/IDEA-Research/GroundingDINO/releases/download/v0.1.0-alpha/groundingdino_swint_ogc.pth
mv groundingdino_swint_ogc.pth ~/.cache/groundingdino/
```

### CUDA out of memory
- Use CPU mode (slower but works)
- Close other GPU applications
- Reduce image resolution

### No detections found
- Lower box_threshold (try 20-25%)
- Check text prompt format (use " . " separator)
- Try synonyms: "car" vs "vehicle", "tree" vs "vegetation"
- Ensure objects are visible in viewport

## Comparison with Other Methods

| Method | Flexibility | Speed | Accuracy | Use Case |
|--------|-------------|-------|----------|----------|
| **Grounding DINO** | ⭐⭐⭐⭐⭐ | ⚡⚡ | ⭐⭐⭐⭐ | Find anything by description |
| **Mask2Former** | ⭐⭐ | ⚡⚡⚡ | ⭐⭐⭐⭐⭐ | 80 COCO classes, best accuracy |
| **Zero-Shot** | ⭐⭐ | ⚡⚡⚡ | ⭐⭐⭐ | 80 COCO classes, good baseline |
| **SAM** | ⭐⭐⭐ | ⚡⚡⚡⚡ | ⭐⭐⭐⭐ | Segment everything, no labels |

## Advanced Usage

### Combining with SAM
1. Use SAM to segment all regions
2. Use Grounding DINO to classify specific segments
3. Gets you both segmentation AND semantic labels

### Custom Vocabularies
Build domain-specific prompts:
- Geological: "rock . sediment . mineral . fault line"
- Marine: "boat . buoy . dock . pier . vessel"
- Arctic: "ice . snow . glacier . crevasse"

## API Documentation

The backend endpoint accepts:

```json
{
  "image": "base64_encoded_image",
  "location": {"latitude": 40.0, "longitude": -119.0, "altitude": 1500},
  "model_type": "grounding_dino",
  "text_prompt": "vehicle . building",
  "box_threshold": 0.35,
  "text_threshold": 0.25
}
```

Returns:

```json
{
  "status": "success",
  "num_detections": 12,
  "detections": [...],
  "geojson": {...},
  "text_prompt": "vehicle . building",
  "device_info": {...},
  "report_url": "/label/ai-analysis/report/..."
}
```

## Date

2025-11-29

