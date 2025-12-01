# Coupling Analysis: map_label.html and label_search.html

## Overview

This document analyzes the potential coupling between the Leaflet-based 2D labeling interface (`map_label.html`) and the Cesium-based 3D labeling interface (`label_search.html`), with focus on model training workflows and tasks suitable for each interface.

## Current State

### map_label.html (Leaflet - 2D Interface)
- **Location**: `/deepgis-xr/deepgis_xr/apps/web/templates/web/map_label.html`
- **JavaScript**: `/deepgis-xr/staticfiles/scripts/webclient/map_label.js`
- **Technology**: Leaflet.js with Leaflet.draw
- **Purpose**: 2D map-based labeling on tiled raster/vector layers
- **Label Model**: Designed for `TiledGISLabel` (currently disabled)
- **Save Endpoint**: `/webclient/addTiledLabel` (commented out in code)

**Key Features:**
- Draw polygons, rectangles on map tiles
- Category selection with color coding
- Histogram analysis for drawn regions
- Free-hand drawing support
- Layer management (raster/vector/terrain)

**Current Status:**
- Label saving is **DISABLED** (lines 673, 775 in map_label.js)
- Shows message: "Adding objects to database is currently disabled."
- Code structure exists but endpoint calls are commented out

### label_search.html (Cesium - 3D Interface)
- **Location**: `/deepgis-xr/deepgis_xr/apps/web/templates/web/label_search.html`
- **JavaScript**: Uses `main.js` (shared across pages)
- **Technology**: Cesium.js for 3D globe
- **Purpose**: 3D visualization and labeling with ML assistance
- **Label Model**: Uses `ImageLabel` model
- **Save Endpoints**: 
  - `save_labels` - Standard label saving
  - `save_assisted_labels` - ML-assisted labeling with training dataset support

**Key Features:**
- 3D globe visualization
- Mask2Former segmentation
- SAM (Segment Anything Model) integration
- YOLOv8 object detection
- Training dataset linking via `training_dataset_id`

## Training Data Flow

### Current Training Data Models

1. **ImageLabel** (Used by label_search.html)
   - Stores GeoJSON in `combined_label_shapes` field
   - Links to `Image` model
   - Used by `train_mask2former_deepgis.py`
   - Can be linked to `TrainingDataset` via `TrainingLabel`

2. **TiledGISLabel** (Designed for map_label.html)
   - Stores labels with geographic bounds (northeast/southwest lat/lng)
   - Links to `RasterImage` model
   - Has `label_json` (JSONField) and `geometry` (TextField)
   - Used by `DeepGISTrainer` class (but not actively used)

### Training Scripts

1. **train_mask2former_deepgis.py**
   - Uses `ImageLabel` objects
   - Converts GeoJSON to segmentation masks
   - Located: `/dreams_laboratory/scripts/train_mask2former_deepgis.py`

2. **DeepGISTrainer** (deepgis_xr/apps/ml/services/trainer.py)
   - Uses `TiledGISLabel` objects
   - Currently not actively used for training
   - Designed for geographic tile-based training

## Coupling Opportunities

### 1. Unified Training Dataset Creation

**Current Gap:**
- `map_label.html` labels are not being saved (disabled)
- Even if enabled, they create `TiledGISLabel` objects
- Training script uses `ImageLabel` objects
- No conversion path between the two

**Solution:**
- Enable label saving in `map_label.html`
- Create conversion utility: `TiledGISLabel` → `ImageLabel`
- Or: Extend training script to support both label types
- Or: Create unified `TrainingLabel` model that accepts both

### 2. Task Suitability Analysis

#### Tasks Suitable for Leaflet (map_label.html - 2D)

**Advantages:**
- ✅ **Large-area labeling**: Better for labeling across multiple tiles
- ✅ **Geographic context**: See surrounding areas, roads, landmarks
- ✅ **Tile-based workflows**: Natural for MBTiles/raster tile datasets
- ✅ **Quick polygon drawing**: Fast for simple shapes
- ✅ **Histogram analysis**: Built-in spectral analysis
- ✅ **Layer comparison**: Easy to compare different dates/layers

**Best For:**
- Regional/landscape-scale labeling
- Multi-tile datasets
- When geographic context matters
- Quick bulk labeling
- Spectral analysis tasks

#### Tasks Suitable for Cesium (label_search.html - 3D)

**Advantages:**
- ✅ **3D context**: See elevation, terrain, 3D structures
- ✅ **ML assistance**: Mask2Former, SAM, YOLOv8 integration
- ✅ **Precise segmentation**: Better for complex object boundaries
- ✅ **Training dataset integration**: Built-in `training_dataset_id` support
- ✅ **Image-based**: Works with individual images, not tiles

**Best For:**
- Object-level precise segmentation
- ML-assisted labeling workflows
- 3D-aware labeling (buildings, terrain)
- Training dataset curation
- Single image annotation

### 3. Recommended Workflow Integration

```
┌─────────────────────────────────────────────────────────────┐
│                    Labeling Workflow                        │
└─────────────────────────────────────────────────────────────┘

1. INITIAL LABELING (map_label.html - Leaflet)
   ├─ Quick bulk labeling on map tiles
   ├─ Geographic context awareness
   ├─ Create TiledGISLabel objects
   └─ Export/convert to ImageLabel format

2. REFINEMENT (label_search.html - Cesium)
   ├─ Load labels from map_label session
   ├─ Use ML assistance (Mask2Former/SAM)
   ├─ Precise boundary refinement
   ├─ Link to TrainingDataset
   └─ Save as ImageLabel with training_dataset_id

3. TRAINING
   ├─ Query TrainingDataset
   ├─ Load ImageLabel objects
   ├─ Convert GeoJSON to masks
   └─ Train Mask2Former/Mask R-CNN
```

## Implementation Recommendations

### Phase 1: Enable map_label.html Saving

**File**: `deepgis-xr/staticfiles/scripts/webclient/map_label.js`

**Changes:**
1. Uncomment label saving code (lines 675-685, 778-788)
2. Verify `/webclient/addTiledLabel` endpoint exists
3. If missing, create endpoint in `views.py`:
   ```python
   @csrf_exempt
   def addTiledLabel(request):
       # Create TiledGISLabel from request
       # Link to RasterImage
       # Return success/error
   ```

### Phase 2: Create Label Conversion Utility

**New File**: `deepgis-xr/deepgis_xr/apps/core/utils/label_converter.py`

**Functionality:**
```python
def tiled_gis_label_to_image_label(tiled_label: TiledGISLabel, image: Image) -> ImageLabel:
    """
    Convert TiledGISLabel to ImageLabel format.
    Extracts tile region from RasterImage, creates ImageLabel.
    """
    # 1. Get tile bounds from TiledGISLabel
    # 2. Extract/crop image region from RasterImage
    # 3. Convert label_json to GeoJSON format
    # 4. Create ImageLabel with combined_label_shapes
    # 5. Link to TrainingDataset if specified
```

### Phase 3: Extend Training Script

**File**: `dreams_laboratory/scripts/train_mask2former_deepgis.py`

**Changes:**
1. Add support for `TiledGISLabel` input
2. Auto-convert `TiledGISLabel` → `ImageLabel` if needed
3. Or create separate dataset class: `DeepGISTiledLabelDataset`

### Phase 4: Unified Training Dataset UI

**New Feature**: Training dataset management in both interfaces

**In map_label.html:**
- Add "Add to Training Dataset" checkbox
- Select/create training dataset
- Save labels with `training_dataset_id`

**In label_search.html:**
- Already has `training_dataset_id` support
- Enhance UI to show linked datasets
- Add dataset statistics

## Code Locations

### map_label.html Related
- Template: `deepgis-xr/deepgis_xr/apps/web/templates/web/map_label.html`
- JavaScript: `deepgis-xr/staticfiles/scripts/webclient/map_label.js`
- View: `deepgis-xr/deepgis_xr/apps/web/views.py` (line 123)
- URL: `deepgis-xr/deepgis_xr/apps/web/urls.py` (line 19: `map-label/`)

### label_search.html Related
- Template: `deepgis-xr/deepgis_xr/apps/web/templates/web/label_search.html`
- JavaScript: `deepgis-xr/staticfiles/web/js/main.js`
- View: `deepgis-xr/deepgis_xr/apps/web/views.py` (search for `label_search`)
- Save endpoints: `save_labels`, `save_assisted_labels`

### Training Related
- Training script: `dreams_laboratory/scripts/train_mask2former_deepgis.py`
- Trainer service: `deepgis-xr/deepgis_xr/apps/ml/services/trainer.py`
- Models: `deepgis-xr/deepgis_xr/apps/core/models.py`
  - `ImageLabel` (line ~240)
  - `TiledGISLabel` (line 205)
  - `TrainingDataset` (line 626)
  - `TrainingLabel` (line 660)

## Summary

### Current State
- ✅ `label_search.html` fully functional for training
- ❌ `map_label.html` label saving disabled
- ⚠️ Two separate label models with no conversion
- ⚠️ Training script only supports `ImageLabel`

### Recommended Actions
1. **Short-term**: Enable `map_label.html` saving, create conversion utility
2. **Medium-term**: Extend training script to support both label types
3. **Long-term**: Unified training dataset UI across both interfaces

### Key Insight
The two interfaces are complementary:
- **Leaflet (2D)**: Fast bulk labeling with geographic context
- **Cesium (3D)**: Precise ML-assisted labeling with training integration

They should work together in a pipeline: Leaflet for initial labeling → Cesium for refinement → Training.

