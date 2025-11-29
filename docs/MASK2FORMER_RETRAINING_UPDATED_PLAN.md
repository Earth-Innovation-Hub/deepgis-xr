# Mask2Former Retraining with Annotations - Updated Implementation Plan

## Overview

This plan leverages **existing annotation models** in `deepgis_xr.apps.core.models` and **reusable frontend components** from `label.html` and `map_label.html` to implement Mask2Former retraining with user corrections.

**Estimated Code Reuse:** ~60-70% of frontend code can be adapted from existing label interfaces.

See `REUSABLE_FRONTEND_FEATURES.md` for detailed analysis of reusable components.

## Existing Annotation Infrastructure

### Current Models (deepgis_xr/apps/core/models.py)

1. **`ImageLabel`** (line 133)
   - Stores labels for images
   - `combined_label_shapes` (TextField) - JSON data
   - `labeler` - ForeignKey to Labeler
   - `image` - ForeignKey to Image
   - `time_taken` - Annotation time tracking

2. **`CategoryLabel`** (line 146)
   - Category-specific labels
   - `label_shapes` (TextField) - JSON data
   - `category` - ForeignKey to CategoryType
   - `parent_label` - ForeignKey to ImageLabel

3. **`TiledGISLabel`** (line 205)
   - GIS/tiled labels with GeoJSON
   - `label_json` (JSONField) - GeoJSON format
   - `geometry` (TextField) - Geometry data
   - `category` - ForeignKey to CategoryType
   - `labeler` - ForeignKey to Labeler

4. **`Labeler`** (line 94)
   - User who performs labeling
   - Links to AUTH_USER_MODEL

5. **`CategoryType`** (line 49)
   - Categories for classification
   - `category_name`, `label_type`, `color`

6. **`Image`** (line 76)
   - Base image model
   - `name`, `path`, `width`, `height`

### Existing API Endpoints

1. **`save_labels()`** (views.py line 360)
   - Saves labels with GeoJSON features
   - Creates `ImageLabel` and `CategoryLabel` records
   - Handles grid metrics

2. **`save_assisted_labels()`** (views.py line 1390)
   - Saves refined labels from AI-assisted labeling
   - Creates `ImageLabel` records with confidence scores
   - Supports auto-generated vs manual labels

---

## Updated Implementation Strategy

### Phase 1: Extend Existing Models (Minimal Changes)

Instead of creating new models, we'll **extend existing ones** with training-specific fields.

#### Option A: Add Fields to Existing Models (Recommended)

**File:** `deepgis_xr/apps/core/models.py`

```python
# Add to ImageLabel model
class ImageLabel(models.Model):
    # ... existing fields ...
    
    # NEW: Training dataset fields
    is_training_data = models.BooleanField(default=False)
    training_dataset_name = models.CharField(max_length=200, blank=True, null=True)
    source_prediction_id = models.CharField(max_length=200, blank=True, null=True)  # Mask2Former session_id
    source_type = models.CharField(max_length=50, choices=[
        ('prediction', 'From Prediction'),
        ('manual', 'Manual Annotation'),
        ('corrected', 'Corrected Prediction'),
    ], default='manual')
    reviewed_for_training = models.BooleanField(default=False)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='reviewed_labels')
    reviewed_at = models.DateTimeField(null=True, blank=True)
    
    # NEW: COCO format cache (for faster training dataset prep)
    coco_annotation_json = models.JSONField(null=True, blank=True)
```

#### Option B: Create Lightweight Training Metadata Model

**File:** `deepgis_xr/apps/core/models.py`

```python
class TrainingDataset(models.Model):
    """Metadata for organizing labels into training datasets"""
    name = models.CharField(max_length=200, unique=True)
    description = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=20, choices=[
        ('draft', 'Draft'),
        ('ready', 'Ready for Training'),
        ('training', 'Training in Progress'),
        ('completed', 'Training Completed'),
    ], default='draft')
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return self.name
    
    @property
    def num_annotations(self):
        return self.training_labels.count()
    
    @property
    def num_images(self):
        return self.training_labels.values('image').distinct().count()


class TrainingLabel(models.Model):
    """Links existing ImageLabels to training datasets"""
    dataset = models.ForeignKey(TrainingDataset, on_delete=models.CASCADE, related_name='training_labels')
    image_label = models.ForeignKey(ImageLabel, on_delete=models.CASCADE, related_name='training_datasets')
    
    # Metadata
    source_prediction_id = models.CharField(max_length=200, blank=True, null=True)
    corrections_made = models.JSONField(default=dict, blank=True)  # Track what was corrected
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ('dataset', 'image_label')
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.dataset.name} - {self.image_label}"


class ModelVersion(models.Model):
    """Trained model versions"""
    name = models.CharField(max_length=200)
    version = models.CharField(max_length=50)
    description = models.TextField(blank=True)
    
    training_dataset = models.ForeignKey(TrainingDataset, on_delete=models.SET_NULL, null=True, blank=True)
    base_model = models.CharField(max_length=100, default='mask2former_coco')
    
    model_path = models.CharField(max_length=500)
    config_path = models.CharField(max_length=500, blank=True)
    
    # Training metrics
    training_loss = models.FloatField(null=True, blank=True)
    validation_loss = models.FloatField(null=True, blank=True)
    mAP_score = models.FloatField(null=True, blank=True)
    
    status = models.CharField(max_length=20, choices=[
        ('training', 'Training'),
        ('completed', 'Completed'),
        ('deployed', 'Deployed'),
        ('archived', 'Archived'),
    ], default='training')
    
    trained_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    trained_at = models.DateTimeField(auto_now_add=True)
    deployed_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        unique_together = ('name', 'version')
        ordering = ['-trained_at']
    
    def __str__(self):
        return f"{self.name} v{self.version}"
```

**Recommendation:** Use **Option B** - keeps training metadata separate while reusing existing `ImageLabel` infrastructure.

---

### Phase 2: Backend API - Leverage Existing Endpoints

#### 2.1 Extend `save_assisted_labels()` for Training Data

**File:** `deepgis_xr/apps/web/views.py`

```python
@csrf_exempt
def save_assisted_labels(request):
    """
    Save refined labels - EXTENDED for training dataset support
    
    POST data:
    - image_id: ID of image
    - labels: GeoJSON with refined labels
    - user_id: ID of user (labeler)
    - training_dataset_id: (NEW) Optional - add to training dataset
    - source_prediction_id: (NEW) Original Mask2Former session_id
    - corrections: (NEW) List of corrections made
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)
    
    try:
        data = json.loads(request.body)
        image_id = data.get('image_id')
        labels_geojson = data.get('labels')
        user_id = data.get('user_id', 'anonymous')
        
        # NEW: Training dataset fields
        training_dataset_id = data.get('training_dataset_id')
        source_prediction_id = data.get('source_prediction_id')
        corrections = data.get('corrections', [])
        
        if not image_id or not labels_geojson:
            return JsonResponse({'error': 'image_id and labels required'}, status=400)
        
        # Get image
        image = Image.objects.get(id=image_id)
        
        # Get or create labeler
        labeler, _ = Labeler.objects.get_or_create(
            user=request.user if request.user.is_authenticated else None,
            defaults={}
        )
        
        # Create ImageLabel (existing functionality)
        image_label = ImageLabel.objects.create(
            image=image,
            combined_label_shapes=json.dumps(labels_geojson),
            labeler=labeler,
            time_taken=data.get('time_taken')
        )
        
        # NEW: Link to training dataset if provided
        if training_dataset_id:
            from deepgis_xr.apps.core.models import TrainingDataset, TrainingLabel
            
            try:
                dataset = TrainingDataset.objects.get(id=training_dataset_id, created_by=request.user)
                
                # Create training label link
                training_label = TrainingLabel.objects.create(
                    dataset=dataset,
                    image_label=image_label,
                    source_prediction_id=source_prediction_id,
                    corrections_made={'corrections': corrections}
                )
                
                # Convert to COCO format and cache
                coco_annotation = convert_geojson_to_coco(labels_geojson, image)
                image_label.coco_annotation_json = coco_annotation
                image_label.save()
                
            except TrainingDataset.DoesNotExist:
                pass  # Dataset doesn't exist, skip training link
        
        # Create CategoryLabel records (existing functionality)
        saved_count = 0
        for feature in labels_geojson.get('features', []):
            category_name = feature['properties'].get('category')
            geometry = feature['geometry']
            
            try:
                category = CategoryType.objects.get(category_name=category_name)
                
                CategoryLabel.objects.create(
                    category=category,
                    label_shapes=json.dumps(geometry),
                    parent_label=image_label
                )
                saved_count += 1
            except CategoryType.DoesNotExist:
                continue
        
        return JsonResponse({
            'success': True,
            'image_label_id': image_label.id,
            'saved_count': saved_count,
            'training_dataset_linked': training_dataset_id is not None
        })
        
    except Exception as e:
        return JsonResponse({
            'error': str(e)
        }, status=500)
```

#### 2.2 New Training Dataset Management API

**File:** `deepgis_xr/apps/api/v1/views/training_datasets.py` (new file)

```python
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST, require_GET
from django.contrib.auth.decorators import login_required
import json

from deepgis_xr.apps.core.models import TrainingDataset, TrainingLabel, ImageLabel, ModelVersion


@csrf_exempt
@require_POST
@login_required
def create_training_dataset(request):
    """Create a new training dataset"""
    data = json.loads(request.body)
    dataset = TrainingDataset.objects.create(
        name=data['name'],
        description=data.get('description', ''),
        created_by=request.user
    )
    return JsonResponse({
        'status': 'success',
        'dataset_id': dataset.id,
        'dataset_name': dataset.name
    })


@csrf_exempt
@require_GET
@login_required
def list_training_datasets(request):
    """List all training datasets for user"""
    datasets = TrainingDataset.objects.filter(created_by=request.user)
    return JsonResponse({
        'status': 'success',
        'datasets': [
            {
                'id': d.id,
                'name': d.name,
                'num_annotations': d.num_annotations,
                'num_images': d.num_images,
                'status': d.status,
                'created_at': d.created_at.isoformat()
            }
            for d in datasets
        ]
    })


@csrf_exempt
@require_GET
@login_required
def get_dataset_details(request, dataset_id):
    """Get dataset details with annotations"""
    dataset = TrainingDataset.objects.get(id=dataset_id, created_by=request.user)
    training_labels = dataset.training_labels.select_related('image_label', 'image_label__image').all()
    
    annotations = []
    for tl in training_labels:
        il = tl.image_label
        annotations.append({
            'id': il.id,
            'image_id': il.image.id,
            'image_name': il.image.name,
            'image_path': il.image.path,
            'coco_annotation': il.coco_annotation_json,
            'source_prediction_id': tl.source_prediction_id,
            'corrections': tl.corrections_made
        })
    
    return JsonResponse({
        'status': 'success',
        'dataset': {
            'id': dataset.id,
            'name': dataset.name,
            'description': dataset.description,
            'status': dataset.status,
            'num_annotations': dataset.num_annotations,
            'num_images': dataset.num_images
        },
        'annotations': annotations
    })


@csrf_exempt
@require_POST
@login_required
def add_label_to_dataset(request):
    """Add existing ImageLabel to training dataset"""
    data = json.loads(request.body)
    dataset_id = data.get('dataset_id')
    image_label_id = data.get('image_label_id')
    
    dataset = TrainingDataset.objects.get(id=dataset_id, created_by=request.user)
    image_label = ImageLabel.objects.get(id=image_label_id)
    
    # Check if already in dataset
    if TrainingLabel.objects.filter(dataset=dataset, image_label=image_label).exists():
        return JsonResponse({
            'status': 'error',
            'message': 'Label already in dataset'
        }, status=400)
    
    # Convert to COCO if not already done
    if not image_label.coco_annotation_json:
        from deepgis_xr.apps.core.utils.training import convert_geojson_to_coco
        geojson = json.loads(image_label.combined_label_shapes)
        coco = convert_geojson_to_coco(geojson, image_label.image)
        image_label.coco_annotation_json = coco
        image_label.save()
    
    # Create training label link
    training_label = TrainingLabel.objects.create(
        dataset=dataset,
        image_label=image_label,
        source_prediction_id=data.get('source_prediction_id'),
        corrections_made=data.get('corrections', {})
    )
    
    return JsonResponse({
        'status': 'success',
        'training_label_id': training_label.id
    })
```

#### 2.3 COCO Format Conversion Utility

**File:** `deepgis_xr/apps/core/utils/training.py` (new file)

```python
"""
Utilities for converting annotations to COCO format for training
"""
import json
from typing import Dict, List, Any
from deepgis_xr.apps.core.models import Image, CategoryType


def convert_geojson_to_coco(geojson: Dict, image: Image) -> Dict:
    """
    Convert GeoJSON annotations to COCO format
    
    Args:
        geojson: GeoJSON FeatureCollection
        image: Image model instance
    
    Returns:
        COCO format annotation dict
    """
    coco_data = {
        'images': [{
            'id': 1,
            'file_name': image.name,
            'width': image.width,
            'height': image.height
        }],
        'annotations': [],
        'categories': []
    }
    
    # Get categories
    categories = CategoryType.objects.all()
    category_map = {}
    for idx, cat in enumerate(categories, start=1):
        coco_data['categories'].append({
            'id': idx,
            'name': cat.category_name,
            'supercategory': 'object'
        })
        category_map[cat.category_name] = idx
    
    # Convert features to annotations
    annotation_id = 1
    for feature in geojson.get('features', []):
        geometry = feature['geometry']
        properties = feature.get('properties', {})
        category_name = properties.get('category', 'unknown')
        
        if category_name not in category_map:
            continue
        
        # Convert polygon coordinates to segmentation format
        segmentation = []
        if geometry['type'] == 'Polygon':
            for ring in geometry['coordinates']:
                # Flatten coordinates: [[x1,y1], [x2,y2], ...] -> [x1,y1,x2,y2,...]
                flat_coords = [coord for ring in ring for coord in ring]
                segmentation.append(flat_coords)
        elif geometry['type'] == 'MultiPolygon':
            for polygon in geometry['coordinates']:
                for ring in polygon:
                    flat_coords = [coord for ring in ring for coord in ring]
                    segmentation.append(flat_coords)
        
        # Calculate bbox
        bbox = calculate_bbox(geometry)
        
        # Calculate area
        area = calculate_polygon_area(geometry)
        
        coco_data['annotations'].append({
            'id': annotation_id,
            'image_id': 1,
            'category_id': category_map[category_name],
            'segmentation': segmentation,
            'area': area,
            'bbox': bbox,  # [x, y, width, height]
            'iscrowd': 0
        })
        annotation_id += 1
    
    return coco_data


def calculate_bbox(geometry: Dict) -> List[float]:
    """Calculate bounding box from geometry"""
    if geometry['type'] == 'Polygon':
        coords = geometry['coordinates'][0]
    elif geometry['type'] == 'MultiPolygon':
        # Get all coordinates from all polygons
        coords = []
        for polygon in geometry['coordinates']:
            coords.extend(polygon[0])
    else:
        return [0, 0, 0, 0]
    
    x_coords = [c[0] for c in coords]
    y_coords = [c[1] for c in coords]
    
    x_min = min(x_coords)
    y_min = min(y_coords)
    x_max = max(x_coords)
    y_max = max(y_coords)
    
    return [x_min, y_min, x_max - x_min, y_max - y_min]


def calculate_polygon_area(geometry: Dict) -> float:
    """Calculate polygon area using shoelace formula"""
    # Simplified - assumes pixel coordinates
    # For actual area calculation, would need coordinate system info
    if geometry['type'] == 'Polygon':
        coords = geometry['coordinates'][0]
    elif geometry['type'] == 'MultiPolygon':
        # Sum areas of all polygons
        total_area = 0
        for polygon in geometry['coordinates']:
            coords = polygon[0]
            area = 0
            n = len(coords)
            for i in range(n):
                j = (i + 1) % n
                area += coords[i][0] * coords[j][1]
                area -= coords[j][0] * coords[i][1]
            total_area += abs(area) / 2
        return total_area
    else:
        return 0
    
    # Shoelace formula
    area = 0
    n = len(coords)
    for i in range(n):
        j = (i + 1) % n
        area += coords[i][0] * coords[j][1]
        area -= coords[j][0] * coords[i][1]
    
    return abs(area) / 2
```

---

### Phase 3: Frontend Integration (Leveraging Reusable Components)

**Reference:** See `REUSABLE_FRONTEND_FEATURES.md` for detailed component analysis.

#### 3.1 Reusable Components Summary

**High Priority Reuse (80%+ code reuse):**
- GeoJSON conversion patterns (from `label.html` lines 1782-1830)
- Save API integration pattern (from `label.html` lines 1832-1900)
- Status message system (from `label_semi_supervised.html` lines 183-217)
- Category selection UI (from `label.html` lines 199-300)
- Sidebar layout and styling (from `label.html` lines 27-64)

**Medium Priority Reuse (50-80% code reuse):**
- Undo/redo system (from `label.html` lines 1215-1244)
- Tool button layout (from `label.html` lines 159-169)
- Clear/reset functionality (from `label.html` lines 2363-2383)

#### 3.2 Update AI Analysis Report - Add Correction Button

**File:** `deepgis_xr/apps/web/templates/web/ai_analysis_report.html`

Add after action buttons:

```html
{% if model_type == 'mask2former' %}
<div class="training-actions mt-3">
    <button class="btn btn-info" onclick="openCorrectionInterface('{{ session_id }}')">
        <i class="fas fa-edit"></i> Correct Predictions & Add to Training Dataset
    </button>
</div>
{% endif %}
```

#### 3.3 Correction Interface JavaScript (Adapting Reusable Components)

**File:** `deepgis-xr/staticfiles/web/js/mask2former-corrector.js` (new file)

**Reuses:**
- GeoJSON conversion pattern from `label.html` (lines 1782-1830)
- Undo/redo system from `label.html` (lines 1215-1244)
- Save API pattern from `label.html` (lines 1832-1900)
- Status message system from `label_semi_supervised.html` (lines 183-217)

```javascript
/**
 * Mask2Former Prediction Corrector
 * Allows users to correct predictions and add to training datasets
 * 
 * Adapts reusable components from label.html and map_label.html
 */
class Mask2FormerCorrector {
    constructor(cesiumViewer) {
        this.viewer = cesiumViewer;
        this.currentSession = null;
        this.currentDataset = null;
        this.predictions = [];
        this.corrections = [];
        this.entities = [];
        
        // Reuse: Undo/redo system (adapted from label.html lines 1215-1244)
        this.undos = [];
        this.redos = [];
        
        // Reuse: Status message system (from label_semi_supervised.html)
        this.statusMessageEl = null;
    }
    
    /**
     * Load prediction results for correction
     */
    async loadPrediction(sessionId) {
        try {
            // Fetch prediction results
            const response = await fetch(`/webclient/sampler/get-prediction/${sessionId}/`);
            const data = await response.json();
            
            this.currentSession = sessionId;
            this.predictions = data.geojson.features;
            
            // Display predictions as editable entities
            this.displayPredictions();
            
            // Show correction UI
            this.showCorrectionPanel();
            
        } catch (error) {
            console.error('Error loading prediction:', error);
            alert('Failed to load prediction results');
        }
    }
    
    /**
     * Display predictions on Cesium viewer
     */
    displayPredictions() {
        // Clear existing entities
        this.entities.forEach(e => this.viewer.entities.remove(e));
        this.entities = [];
        
        this.predictions.forEach((feature, index) => {
            const geometry = feature.geometry;
            const properties = feature.properties;
            
            // Create polygon entity
            const entity = this.viewer.entities.add({
                name: `Prediction ${index + 1}: ${properties.category}`,
                polygon: {
                    hierarchy: this.geojsonToCesiumCoordinates(geometry),
                    material: Cesium.Color.fromCssColorString(
                        properties.color || '#FF0000'
                    ).withAlpha(0.5),
                    outline: true,
                    outlineColor: Cesium.Color.WHITE,
                    outlineWidth: 2,
                    height: 0,
                    extrudedHeight: 0
                },
                properties: {
                    originalIndex: index,
                    category: properties.category,
                    confidence: properties.confidence || 1.0,
                    originalFeature: feature
                }
            });
            
            // Make editable (using Cesium's entity editing if available)
            entity.editable = true;
            this.entities.push(entity);
        });
    }
    
    /**
     * Show correction panel UI
     */
    showCorrectionPanel() {
        // Create or show correction panel
        let panel = document.getElementById('correction-panel');
        if (!panel) {
            panel = this.createCorrectionPanel();
            document.body.appendChild(panel);
        }
        panel.style.display = 'block';
    }
    
    /**
     * Create correction panel HTML
     * 
     * Reuses: Sidebar layout from label.html (lines 27-64)
     * Reuses: Tool button layout from label.html (lines 159-169)
     * Reuses: Category selection UI from label.html (lines 199-300)
     */
    createCorrectionPanel() {
        const panel = document.createElement('div');
        panel.id = 'correction-panel';
        panel.className = 'correction-panel control-sidebar'; // Reuse sidebar class
        panel.innerHTML = `
            <div class="panel-header">
                <h3>Correct Mask2Former Predictions</h3>
                <button onclick="corrector.closePanel()">×</button>
            </div>
            <div class="panel-body">
                <!-- Reuse: Status message system -->
                <div id="statusMessage" style="display: none;"></div>
                
                <!-- Training Dataset Selection -->
                <div class="form-group">
                    <label>Training Dataset:</label>
                    <select id="training-dataset-select" class="form-control">
                        <option value="">Select or create dataset...</option>
                    </select>
                    <button class="btn btn-sm btn-primary mt-2" onclick="corrector.createNewDataset()">
                        New Dataset
                    </button>
                </div>
                
                <!-- Reuse: Tool buttons layout (adapted from label.html lines 159-169) -->
                <div class="tool-buttons">
                    <button class="btn btn-sm btn-outline-primary" onclick="corrector.activateEditMode()">
                        Edit Mask
                    </button>
                    <button class="btn btn-sm btn-outline-primary" onclick="corrector.activateCategoryChange()">
                        Change Category
                    </button>
                    <button class="btn btn-sm btn-outline-danger" onclick="corrector.deleteSelected()">
                        Delete
                    </button>
                    <button class="btn btn-sm btn-outline-secondary" onclick="corrector.undoLastOperation()">
                        Undo
                    </button>
                    <button class="btn btn-sm btn-outline-secondary" onclick="corrector.redoLastOperation()">
                        Redo
                    </button>
                </div>
                
                <!-- Reuse: Category selection UI (adapted from label.html lines 199-300) -->
                <div class="section">
                    <h4>Categories</h4>
                    <ul id="categories-list" class="categories-list">
                        <!-- Populated dynamically from CategoryType model -->
                    </ul>
                </div>
                
                <!-- Predictions List -->
                <div class="predictions-list" id="predictions-list">
                    <h4>Predictions</h4>
                    <!-- Populated dynamically -->
                </div>
                
                <!-- Panel Actions -->
                <div class="panel-actions">
                    <button class="btn btn-primary" onclick="corrector.saveCorrections()">
                        Save Corrections
                    </button>
                    <button class="btn btn-secondary" onclick="corrector.clearAllCorrections()">
                        Clear All
                    </button>
                </div>
            </div>
        `;
        
        // Load datasets and categories
        this.loadTrainingDatasets();
        this.loadCategories(); // Reuse category loading pattern
        
        return panel;
    }
    
    /**
     * Reuse: Category loading (adapted from label.html category management)
     */
    async loadCategories() {
        try {
            const response = await fetch('/api/categories/');
            const categories = await response.json();
            
            const categoriesList = document.getElementById('categories-list');
            categoriesList.innerHTML = '';
            
            categories.forEach(cat => {
                const li = document.createElement('li');
                li.dataset.category = cat.category_name;
                li.style.backgroundColor = cat.color || '#ff0000';
                li.innerHTML = `
                    <span class="category-name">${cat.category_name}</span>
                    <span class="category-color" style="background-color: ${cat.color || '#ff0000'}"></span>
                `;
                li.addEventListener('click', () => {
                    this.currentCategory = cat.category_name;
                    this.currentColor = cat.color || '#ff0000';
                    // Update UI to show selected category
                    document.querySelectorAll('#categories-list li').forEach(item => {
                        item.classList.remove('selected');
                    });
                    li.classList.add('selected');
                });
                categoriesList.appendChild(li);
            });
        } catch (error) {
            console.error('Error loading categories:', error);
        }
    }
    
    /**
     * Reuse: Clear functionality (adapted from label.html lines 2363-2383)
     */
    clearAllCorrections() {
        if (confirm('Are you sure you want to clear all corrections? This will reset to original predictions.')) {
            // Reset entities to original predictions
            this.entities.forEach((entity, index) => {
                const originalFeature = this.predictions[index];
                if (originalFeature) {
                    entity.polygon.hierarchy = this.geojsonToCesiumCoordinates(originalFeature.geometry);
                    entity.properties.category = originalFeature.properties.category;
                    entity.properties.confidence = originalFeature.properties.confidence || 1.0;
                }
            });
            
            // Clear undo/redo stacks
            this.undos = [];
            this.redos = [];
            
            this.showStatusMessage('All corrections cleared', 'success');
        }
    }
    
    /**
     * Save corrections to training dataset
     * 
     * Reuses: Save API pattern from label.html (lines 1832-1900)
     * Adapts: GeoJSON conversion from label.html (lines 1782-1830)
     */
    async saveCorrections() {
        const datasetId = document.getElementById('training-dataset-select').value;
        if (!datasetId) {
            this.showStatusMessage('Please select a training dataset', 'error');
            return;
        }
        
        this.showStatusMessage('Saving corrections...', 'loading');
        
        // Reuse: GeoJSON conversion pattern (adapted from label.html)
        const correctedFeatures = this.entities.map((entity, index) => {
            const props = entity.properties;
            const hierarchy = entity.polygon.hierarchy.getValue();
            
            // Convert Cesium coordinates back to GeoJSON
            const coordinates = this.cesiumToGeojsonCoordinates(hierarchy);
            
            return {
                type: 'Feature',
                geometry: {
                    type: 'Polygon',
                    coordinates: [coordinates]
                },
                properties: {
                    category: props.category.getValue(),
                    confidence: props.confidence.getValue(),
                    corrected: true,
                    originalIndex: props.originalIndex.getValue()
                }
            };
        });
        
        const geojson = {
            type: 'FeatureCollection',
            features: correctedFeatures
        };
        
        // Get image info from session
        const imageInfo = await this.getImageInfo(this.currentSession);
        
        // Reuse: Save API pattern from label.html (lines 1832-1900)
        try {
            const response = await fetch('/label/semi-supervised/api/save-labels/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.getCookie('csrftoken')
                },
                body: JSON.stringify({
                    image_id: imageInfo.image_id,
                    labels: geojson,
                    user_id: this.getCurrentUserId(),
                    training_dataset_id: datasetId,
                    source_prediction_id: this.currentSession,
                    corrections: this.corrections
                })
            });
            
            const result = await response.json();
            if (result.success) {
                this.showStatusMessage('Corrections saved to training dataset!', 'success');
                setTimeout(() => {
                    this.closePanel();
                }, 2000);
            } else {
                this.showStatusMessage('Error saving corrections: ' + result.error, 'error');
            }
        } catch (error) {
            this.showStatusMessage('Network error: ' + error.message, 'error');
        }
    }
    
    /**
     * Reuse: Status message system (from label_semi_supervised.html lines 183-217)
     */
    showStatusMessage(message, type = 'info') {
        if (!this.statusMessageEl) {
            this.statusMessageEl = document.createElement('div');
            this.statusMessageEl.id = 'statusMessage';
            this.statusMessageEl.className = type;
            document.querySelector('.correction-panel .panel-body').prepend(this.statusMessageEl);
        }
        
        this.statusMessageEl.textContent = message;
        this.statusMessageEl.className = type;
        this.statusMessageEl.style.display = 'block';
        
        if (type !== 'loading') {
            setTimeout(() => {
                this.statusMessageEl.style.display = 'none';
            }, 3000);
        }
    }
    
    /**
     * Reuse: Undo/redo system (adapted from label.html lines 1215-1244)
     */
    addToUndoStack(entity) {
        // Clone entity state
        const state = {
            id: entity.id,
            polygon: entity.polygon.hierarchy.getValue(),
            properties: {
                category: entity.properties.category.getValue(),
                confidence: entity.properties.confidence.getValue()
            }
        };
        this.undos.push(state);
        this.redos = []; // Clear redos when new action is performed
    }
    
    undoLastOperation() {
        if (this.undos.length > 0) {
            const state = this.undos.pop();
            const entity = this.viewer.entities.getById(state.id);
            
            if (entity) {
                // Add to redo stack
                const currentState = {
                    id: entity.id,
                    polygon: entity.polygon.hierarchy.getValue(),
                    properties: {
                        category: entity.properties.category.getValue(),
                        confidence: entity.properties.confidence.getValue()
                    }
                };
                this.redos.push(currentState);
                
                // Restore previous state
                entity.polygon.hierarchy = state.polygon;
                entity.properties.category = state.properties.category;
                entity.properties.confidence = state.properties.confidence;
            }
        }
    }
    
    redoLastOperation() {
        if (this.redos.length > 0) {
            const state = this.redos.pop();
            const entity = this.viewer.entities.getById(state.id);
            
            if (entity) {
                // Add current state to undo stack
                const currentState = {
                    id: entity.id,
                    polygon: entity.polygon.hierarchy.getValue(),
                    properties: {
                        category: entity.properties.category.getValue(),
                        confidence: entity.properties.confidence.getValue()
                    }
                };
                this.undos.push(currentState);
                
                // Restore state
                entity.polygon.hierarchy = state.polygon;
                entity.properties.category = state.properties.category;
                entity.properties.confidence = state.properties.confidence;
            }
        }
    }
    
    /**
     * Helper: Get CSRF token (reused pattern)
     */
    getCookie(name) {
        let cookieValue = null;
        if (document.cookie && document.cookie !== '') {
            const cookies = document.cookie.split(';');
            for (let i = 0; i < cookies.length; i++) {
                const cookie = cookies[i].trim();
                if (cookie.substring(0, name.length + 1) === (name + '=')) {
                    cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                    break;
                }
            }
        }
        return cookieValue;
    }
    
    /**
     * Helper: Convert GeoJSON to Cesium coordinates
     */
    geojsonToCesiumCoordinates(geometry) {
        if (geometry.type === 'Polygon') {
            return Cesium.Cartesian3.fromDegreesArray(
                geometry.coordinates[0].flat()
            );
        }
        return [];
    }
    
    /**
     * Helper: Convert Cesium coordinates to GeoJSON
     */
    cesiumToGeojsonCoordinates(cartesians) {
        return cartesians.map(c => {
            const cartographic = Cesium.Cartographic.fromCartesian(c);
            return [
                Cesium.Math.toDegrees(cartographic.longitude),
                Cesium.Math.toDegrees(cartographic.latitude)
            ];
        });
    }
}

// Global instance
let corrector = null;
```

---

## Updated Implementation Checklist

### Backend
- [ ] Add `TrainingDataset`, `TrainingLabel`, `ModelVersion` models (Option B)
- [ ] Run migrations
- [ ] Extend `save_assisted_labels()` to support training datasets
- [ ] Create training dataset management API endpoints
- [ ] Create COCO conversion utility (`convert_geojson_to_coco`)
- [ ] Implement `Mask2FormerTrainer` class
- [ ] Add training API endpoint

### Frontend (Leveraging Reusable Components)
- [ ] **Create `Mask2FormerCorrector` JavaScript class**
  - [ ] Adapt GeoJSON conversion from `label.html` (lines 1782-1830)
  - [ ] Adapt undo/redo system from `label.html` (lines 1215-1244)
  - [ ] Reuse save API pattern from `label.html` (lines 1832-1900)
  - [ ] Reuse status message system from `label_semi_supervised.html` (lines 183-217)
- [ ] **Add correction UI panel**
  - [ ] Reuse sidebar layout from `label.html` (lines 27-64)
  - [ ] Reuse tool button layout from `label.html` (lines 159-169)
  - [ ] Reuse category selection UI from `label.html` (lines 199-300)
  - [ ] Adapt clear functionality from `label.html` (lines 2363-2383)
- [ ] Add "Correct Predictions" button to AI analysis report
- [ ] Create training dataset management page
- [ ] **Reuse existing components:**
  - [ ] Category loading API integration
  - [ ] CSRF token handling
  - [ ] Error handling patterns

### Integration
- [ ] Update AI analysis report template
- [ ] Add URL routes for training dataset management
- [ ] Test end-to-end workflow
- [ ] Add error handling (reuse patterns from existing code)

### Code Reuse Summary
- **Estimated Frontend Reuse:** 60-70%
- **Direct Reuse (80%+):** GeoJSON conversion, save API pattern, status messages, category UI
- **Adapted Reuse (50-80%):** Undo/redo, tool buttons, sidebar layout, clear functionality

---

## Key Advantages of This Approach

1. **Reuses Existing Infrastructure**: 
   - Leverages `ImageLabel`, `CategoryLabel`, `Labeler` models
   - Reuses 60-70% of frontend code from existing label interfaces
2. **Minimal Database Changes**: Only adds 3 new models for training metadata
3. **Backward Compatible**: Existing labeling workflows continue to work
4. **Flexible**: Can add labels to training datasets from multiple sources
5. **Efficient**: 
   - COCO format cached in `coco_annotation_json` field
   - Reuses proven UI patterns and components
6. **Faster Development**: Leverages existing, tested code patterns
7. **Consistent UX**: Maintains familiar interface patterns for users

---

## Data Flow (Updated)

```
1. User runs Mask2Former prediction
   ↓
2. Results saved to mask2former_results/ (existing)
   ↓
3. User views AI Analysis Report
   ↓
4. User clicks "Correct Predictions"
   ↓
5. Correction interface loads predictions
   ↓
6. User edits masks/categories
   ↓
7. User selects/creates training dataset
   ↓
8. Save via save_assisted_labels() with training_dataset_id
   ↓
9. Creates ImageLabel (existing) + TrainingLabel (new link)
   ↓
10. COCO format cached in ImageLabel.coco_annotation_json
   ↓
11. Training dataset ready for model training
```

---

## Code Reuse Examples

### Example 1: Adapting GeoJSON Conversion

**Original (Paper.js - label.html lines 1814-1829):**
```javascript
const feature = {
    type: 'Feature',
    geometry: {
        type: getGeometryType(child),
        coordinates: getCoordinates(child)
    },
    properties: {
        category: child.data.category,
        color: child.data.color,
        createdAt: child.data.createdAt
    }
};
```

**Adapted (Cesium):**
```javascript
// In Mask2FormerCorrector class
cesiumEntityToGeoJSON(entity) {
    const hierarchy = entity.polygon.hierarchy.getValue();
    const coords = this.cesiumToGeojsonCoordinates(hierarchy);
    
    return {
        type: 'Feature',
        geometry: {
            type: 'Polygon',
            coordinates: [coords]
        },
        properties: {
            category: entity.properties.category.getValue(),
            confidence: entity.properties.confidence.getValue(),
            corrected: true
        }
    };
}
```

### Example 2: Adapting Undo/Redo

**Original (Paper.js - label.html lines 1215-1244):**
```javascript
globals.undos = [];
function addToUndoStack(path) {
    globals.undos.push(path);
    globals.redos = [];
}
function undoLastOperation() {
    const lastItem = globals.undos.pop();
    globals.redos.push(lastItem);
    lastItem.remove();
}
```

**Adapted (Cesium):**
```javascript
// In Mask2FormerCorrector class
addToUndoStack(entity) {
    const state = {
        id: entity.id,
        polygon: entity.polygon.hierarchy.getValue(),
        properties: {
            category: entity.properties.category.getValue(),
            confidence: entity.properties.confidence.getValue()
        }
    };
    this.undos.push(state);
    this.redos = [];
}

undoLastOperation() {
    if (this.undos.length > 0) {
        const state = this.undos.pop();
        const entity = this.viewer.entities.getById(state.id);
        if (entity) {
            this.redos.push({
                id: entity.id,
                polygon: entity.polygon.hierarchy.getValue(),
                properties: {
                    category: entity.properties.category.getValue(),
                    confidence: entity.properties.confidence.getValue()
                }
            });
            // Restore state
            entity.polygon.hierarchy = state.polygon;
            entity.properties.category = state.properties.category;
            entity.properties.confidence = state.properties.confidence;
        }
    }
}
```

### Example 3: Reusing Save API Pattern

**Original (label.html lines 1832-1900):**
```javascript
fetch('/label/api/save-labels/', {
    method: 'POST',
    headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': getCookie('csrftoken')
    },
    body: JSON.stringify({
        image_id: currentImageId,
        labels: geojson,
        user_id: currentUserId
    })
})
.then(response => response.json())
.then(data => {
    if (data.status === 'success') {
        showSuccessMessage('Labels saved successfully!');
    }
});
```

**Adapted (with training dataset support):**
```javascript
// In Mask2FormerCorrector class
fetch('/label/semi-supervised/api/save-labels/', {
    method: 'POST',
    headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': this.getCookie('csrftoken')
    },
    body: JSON.stringify({
        image_id: imageInfo.image_id,
        labels: geojson,
        user_id: this.getCurrentUserId(),
        training_dataset_id: datasetId,      // NEW
        source_prediction_id: this.currentSession,  // NEW
        corrections: this.corrections         // NEW
    })
})
.then(response => response.json())
.then(data => {
    if (data.success) {
        this.showStatusMessage('Corrections saved!', 'success');
    } else {
        this.showStatusMessage('Error: ' + data.error, 'error');
    }
});
```

---

## References

- **Reusable Components Analysis:** `REUSABLE_FRONTEND_FEATURES.md`
- **Original Label Interface:** `deepgis_xr/apps/web/templates/web/label.html`
- **Map Label Interface:** `deepgis_xr/apps/web/templates/web/map_label.html`
- **Semi-Supervised Labeling:** `deepgis_xr/apps/web/templates/web/label_semi_supervised.html`

