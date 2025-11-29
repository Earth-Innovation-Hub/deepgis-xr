# Mask2Former Retraining with Annotations - Implementation Plan

## Overview

This document outlines the implementation plan for adding frontend and backend features to retrain Mask2Former models with user annotations and corrections of predicted masks.

## Current State

### Existing Infrastructure
- ✅ Mask2Former predictions via `_analyze_viewport_mask2former()` 
- ✅ Results saved to `mask2former_results/` with GeoJSON
- ✅ Semi-supervised labeling interface at `/label/semi-supervised/`
- ✅ `ImageLabel` and `CategoryLabel` models for storing annotations
- ✅ `save_assisted_labels()` API endpoint
- ✅ Basic training infrastructure (`DeepGISTrainer` for Mask R-CNN)

### What's Missing
- ❌ UI for viewing/editing Mask2Former predictions
- ❌ Correction tools (edit masks, add/remove objects, change categories)
- ❌ Training dataset management interface
- ❌ Mask2Former-specific training pipeline
- ❌ Model versioning and deployment system

---

## Architecture

### Data Flow

```
1. User runs Mask2Former prediction
   ↓
2. Results displayed in UI with editable masks
   ↓
3. User corrects/annotates predictions
   ↓
4. Corrections saved to database (TrainingDataset model)
   ↓
5. Training dataset prepared from annotations
   ↓
6. Mask2Former fine-tuning job submitted
   ↓
7. New model version saved and deployed
```

---

## Implementation Steps

### Phase 1: Database Models

#### 1.1 Create Training Dataset Model

**File:** `deepgis_xr/apps/core/models.py`

```python
class TrainingDataset(models.Model):
    """Dataset for training Mask2Former models"""
    name = models.CharField(max_length=200, unique=True)
    description = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    # Dataset statistics
    num_images = models.IntegerField(default=0)
    num_annotations = models.IntegerField(default=0)
    
    # Status
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('ready', 'Ready for Training'),
        ('training', 'Training in Progress'),
        ('completed', 'Training Completed'),
    ]
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.name} ({self.num_annotations} annotations)"


class TrainingAnnotation(models.Model):
    """Individual annotation for training dataset"""
    dataset = models.ForeignKey(TrainingDataset, on_delete=models.CASCADE, related_name='annotations')
    
    # Source image
    image_path = models.CharField(max_length=500)  # Path to original image
    image_width = models.IntegerField()
    image_height = models.IntegerField()
    
    # Annotation data (COCO format)
    annotation_json = models.JSONField()  # Full COCO annotation format
    
    # Metadata
    source = models.CharField(max_length=50, choices=[
        ('prediction', 'From Prediction'),
        ('manual', 'Manual Annotation'),
        ('corrected', 'Corrected Prediction'),
    ])
    original_prediction_id = models.CharField(max_length=200, blank=True, null=True)
    
    # Quality metrics
    confidence_score = models.FloatField(null=True, blank=True)
    reviewed = models.BooleanField(default=False)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['dataset', '-created_at']),
            models.Index(fields=['source']),
            models.Index(fields=['reviewed']),
        ]
    
    def __str__(self):
        return f"Annotation {self.id} - {self.dataset.name}"


class ModelVersion(models.Model):
    """Trained model versions"""
    name = models.CharField(max_length=200)
    version = models.CharField(max_length=50)  # e.g., "v1.0", "v2.1"
    description = models.TextField(blank=True)
    
    # Training info
    training_dataset = models.ForeignKey(TrainingDataset, on_delete=models.SET_NULL, null=True, blank=True)
    base_model = models.CharField(max_length=100, default='mask2former_coco')  # Base model used
    
    # Model files
    model_path = models.CharField(max_length=500)  # Path to .pth file
    config_path = models.CharField(max_length=500, blank=True)  # Config file if needed
    
    # Training metrics
    training_loss = models.FloatField(null=True, blank=True)
    validation_loss = models.FloatField(null=True, blank=True)
    mAP_score = models.FloatField(null=True, blank=True)  # Mean Average Precision
    
    # Status
    STATUS_CHOICES = [
        ('training', 'Training'),
        ('completed', 'Completed'),
        ('deployed', 'Deployed'),
        ('archived', 'Archived'),
    ]
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='training')
    
    # Metadata
    trained_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    trained_at = models.DateTimeField(auto_now_add=True)
    deployed_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        unique_together = ('name', 'version')
        ordering = ['-trained_at']
    
    def __str__(self):
        return f"{self.name} v{self.version}"
```

---

### Phase 2: Backend API Endpoints

#### 2.1 Annotation Management API

**File:** `deepgis_xr/apps/api/v1/views/annotations.py` (new file)

```python
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST, require_GET
from django.contrib.auth.decorators import login_required
import json
from pathlib import Path

from deepgis_xr.apps.core.models import TrainingDataset, TrainingAnnotation


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
@require_POST
@login_required
def save_corrected_annotation(request):
    """
    Save corrected annotation from Mask2Former prediction
    
    POST data:
    - dataset_id: ID of training dataset
    - session_id: Original prediction session ID
    - image_path: Path to source image
    - annotations: COCO-format annotations (corrected)
    - corrections: List of corrections made
    """
    data = json.loads(request.body)
    
    try:
        dataset = TrainingDataset.objects.get(id=data['dataset_id'])
        
        # Load original prediction metadata
        session_id = data['session_id']
        results_dir = Path('/app/deepgis_results') / 'mask2former_results' / session_id
        
        # Create annotation record
        annotation = TrainingAnnotation.objects.create(
            dataset=dataset,
            image_path=str(results_dir / 'query_image.png'),
            image_width=data['image_width'],
            image_height=data['image_height'],
            annotation_json=data['annotations'],  # COCO format
            source='corrected',
            original_prediction_id=session_id,
            confidence_score=data.get('confidence_score'),
            reviewed=True,
            reviewed_by=request.user,
        )
        
        # Update dataset statistics
        dataset.num_annotations += 1
        dataset.save()
        
        return JsonResponse({
            'status': 'success',
            'annotation_id': annotation.id
        })
        
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': str(e)
        }, status=500)


@csrf_exempt
@require_GET
@login_required
def list_training_datasets(request):
    """List all training datasets"""
    datasets = TrainingDataset.objects.filter(created_by=request.user)
    return JsonResponse({
        'status': 'success',
        'datasets': [
            {
                'id': d.id,
                'name': d.name,
                'num_annotations': d.num_annotations,
                'status': d.status,
                'created_at': d.created_at.isoformat()
            }
            for d in datasets
        ]
    })


@csrf_exempt
@require_GET
@login_required
def get_dataset_annotations(request, dataset_id):
    """Get all annotations for a dataset"""
    dataset = TrainingDataset.objects.get(id=dataset_id, created_by=request.user)
    annotations = dataset.annotations.all()
    
    return JsonResponse({
        'status': 'success',
        'annotations': [
            {
                'id': a.id,
                'image_path': a.image_path,
                'annotation_json': a.annotation_json,
                'source': a.source,
                'reviewed': a.reviewed
            }
            for a in annotations
        ]
    })
```

#### 2.2 Training API

**File:** `deepgis_xr/apps/ml/services/mask2former_trainer.py` (new file)

```python
from pathlib import Path
import json
import torch
from typing import Dict, List
from detectron2.engine import DefaultTrainer
from detectron2.config import get_cfg
from detectron2 import model_zoo
from detectron2.data import DatasetCatalog, MetadataCatalog
from detectron2.data.datasets import register_coco_instances

from deepgis_xr.apps.core.models import TrainingDataset, TrainingAnnotation, ModelVersion


class Mask2FormerTrainer:
    """Training service for Mask2Former models"""
    
    def __init__(self, dataset_id: int, output_dir: str = '/app/models/mask2former'):
        self.dataset_id = dataset_id
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.device = 'cuda' if torch.cuda.is_available() else 'cpu'
        
    def prepare_coco_dataset(self) -> str:
        """Convert annotations to COCO format and register with Detectron2"""
        dataset = TrainingDataset.objects.get(id=self.dataset_id)
        annotations = dataset.annotations.filter(reviewed=True)
        
        # Convert to COCO format
        coco_data = {
            'images': [],
            'annotations': [],
            'categories': []
        }
        
        # Get categories from database
        from deepgis_xr.apps.core.models import CategoryType
        categories = CategoryType.objects.all()
        
        category_map = {}
        for idx, cat in enumerate(categories, start=1):
            coco_data['categories'].append({
                'id': idx,
                'name': cat.category_name,
                'supercategory': 'object'
            })
            category_map[cat.category_name] = idx
        
        # Process annotations
        annotation_id = 1
        for ann in annotations:
            # Add image
            image_id = len(coco_data['images']) + 1
            coco_data['images'].append({
                'id': image_id,
                'file_name': Path(ann.image_path).name,
                'width': ann.image_width,
                'height': ann.image_height
            })
            
            # Add annotations
            ann_json = ann.annotation_json
            for seg in ann_json.get('annotations', []):
                coco_data['annotations'].append({
                    'id': annotation_id,
                    'image_id': image_id,
                    'category_id': category_map.get(seg['category_name'], 1),
                    'segmentation': seg['segmentation'],
                    'area': seg.get('area', 0),
                    'bbox': seg.get('bbox', []),
                    'iscrowd': 0
                })
                annotation_id += 1
        
        # Save COCO JSON
        coco_path = self.output_dir / f'dataset_{self.dataset_id}.json'
        with open(coco_path, 'w') as f:
            json.dump(coco_data, f)
        
        # Register with Detectron2
        dataset_name = f"deepgis_dataset_{self.dataset_id}"
        register_coco_instances(
            dataset_name,
            {},
            str(coco_path),
            str(Path('/app/deepgis_results').parent)  # Image directory
        )
        
        return dataset_name
    
    def train(self, num_epochs: int = 10, learning_rate: float = 0.0001) -> str:
        """Train Mask2Former model"""
        # Prepare dataset
        dataset_name = self.prepare_coco_dataset()
        
        # Configure model
        cfg = get_cfg()
        cfg.merge_from_file(model_zoo.get_config_file(
            "COCO-PanopticSegmentation/maskformer_R50_bs16_50ep.yaml"
        ))
        cfg.DATASETS.TRAIN = (dataset_name,)
        cfg.DATASETS.TEST = ()
        cfg.DATALOADER.NUM_WORKERS = 2
        cfg.MODEL.WEIGHTS = model_zoo.get_checkpoint_url(
            "COCO-PanopticSegmentation/maskformer_R50_bs16_50ep.yaml"
        )
        cfg.SOLVER.IMS_PER_BATCH = 2
        cfg.SOLVER.BASE_LR = learning_rate
        cfg.SOLVER.MAX_ITER = num_epochs * 100  # Approximate
        cfg.SOLVER.STEPS = []
        cfg.MODEL.ROI_HEADS.BATCH_SIZE_PER_IMAGE = 512
        cfg.MODEL.ROI_HEADS.NUM_CLASSES = len(coco_data['categories'])
        
        # Output directory
        cfg.OUTPUT_DIR = str(self.output_dir)
        
        # Train
        trainer = DefaultTrainer(cfg)
        trainer.resume_or_load(resume=False)
        trainer.train()
        
        # Save model path
        model_path = self.output_dir / "model_final.pth"
        
        return str(model_path)
```

#### 2.3 Update Training API Endpoint

**File:** `deepgis_xr/apps/api/v1/views/training.py`

```python
@csrf_exempt
@require_POST
@login_required
def start_mask2former_training(request):
    """Start Mask2Former training job"""
    data = json.loads(request.body)
    dataset_id = data.get('dataset_id')
    
    if not dataset_id:
        return JsonResponse({'error': 'dataset_id required'}, status=400)
    
    # Create training task (use Celery for async)
    from deepgis_xr.apps.ml.services.mask2former_trainer import Mask2FormerTrainer
    from deepgis_xr.apps.core.models import TrainingDataset, ModelVersion
    
    dataset = TrainingDataset.objects.get(id=dataset_id, created_by=request.user)
    
    # Create model version
    model_version = ModelVersion.objects.create(
        name=data.get('model_name', 'Custom Mask2Former'),
        version=data.get('version', '1.0'),
        training_dataset=dataset,
        status='training',
        trained_by=request.user
    )
    
    # Start training (async)
    trainer = Mask2FormerTrainer(dataset_id, output_dir=f'/app/models/mask2former/v{model_version.version}')
    model_path = trainer.train(
        num_epochs=data.get('num_epochs', 10),
        learning_rate=data.get('learning_rate', 0.0001)
    )
    
    # Update model version
    model_version.model_path = model_path
    model_version.status = 'completed'
    model_version.save()
    
    return JsonResponse({
        'status': 'success',
        'model_version_id': model_version.id,
        'model_path': model_path
    })
```

---

### Phase 3: Frontend UI Components

#### 3.1 Prediction Review & Correction Interface

**File:** `deepgis-xr/staticfiles/web/js/mask2former-corrector.js` (new file)

```javascript
class Mask2FormerCorrector {
    constructor(containerId, cesiumViewer) {
        this.container = document.getElementById(containerId);
        this.viewer = cesiumViewer;
        this.currentSession = null;
        this.annotations = [];
        this.corrections = [];
    }
    
    /**
     * Load prediction results for correction
     */
    async loadPrediction(sessionId) {
        const response = await fetch(`/webclient/sampler/get-prediction/${sessionId}/`);
        const data = await response.json();
        
        this.currentSession = sessionId;
        this.annotations = data.geojson.features;
        
        // Display predictions on map
        this.displayPredictions();
        
        // Show correction UI
        this.showCorrectionPanel();
    }
    
    /**
     * Display predictions as editable entities
     */
    displayPredictions() {
        this.annotations.forEach((feature, index) => {
            const geometry = feature.geometry;
            const properties = feature.properties;
            
            // Create Cesium entity
            const entity = this.viewer.entities.add({
                name: `Prediction ${index + 1}`,
                polygon: {
                    hierarchy: Cesium.Cartesian3.fromDegreesArray(
                        geometry.coordinates[0].flat()
                    ),
                    material: Cesium.Color.fromCssColorString(
                        properties.color || '#FF0000'
                    ).withAlpha(0.5),
                    outline: true,
                    outlineColor: Cesium.Color.WHITE,
                    height: 0
                },
                properties: {
                    category: properties.category,
                    confidence: properties.confidence,
                    originalIndex: index
                }
            });
            
            // Make editable
            entity.editable = true;
            entity.onEdit = () => this.onAnnotationEdit(entity, index);
        });
    }
    
    /**
     * Handle annotation edit
     */
    onAnnotationEdit(entity, originalIndex) {
        // Show edit dialog
        const dialog = this.createEditDialog(entity, originalIndex);
        this.container.appendChild(dialog);
    }
    
    /**
     * Create edit dialog for annotation
     */
    createEditDialog(entity, index) {
        const dialog = document.createElement('div');
        dialog.className = 'correction-dialog';
        dialog.innerHTML = `
            <h3>Edit Annotation</h3>
            <div class="form-group">
                <label>Category:</label>
                <select id="category-select-${index}">
                    ${this.getCategoryOptions(entity.properties.category)}
                </select>
            </div>
            <div class="form-group">
                <label>Confidence:</label>
                <input type="range" min="0" max="1" step="0.01" 
                       value="${entity.properties.confidence}" 
                       id="confidence-${index}">
                <span id="confidence-value-${index}">${entity.properties.confidence}</span>
            </div>
            <div class="form-group">
                <button onclick="corrector.deleteAnnotation(${index})">Delete</button>
                <button onclick="corrector.saveCorrection(${index})">Save</button>
                <button onclick="corrector.cancelEdit()">Cancel</button>
            </div>
        `;
        return dialog;
    }
    
    /**
     * Save correction
     */
    async saveCorrection(index) {
        const annotation = this.annotations[index];
        const correction = {
            type: 'correction',
            originalIndex: index,
            originalAnnotation: annotation,
            correctedAnnotation: this.getCurrentAnnotation(index),
            corrections: this.getCorrectionsList(index)
        };
        
        this.corrections.push(correction);
        
        // Save to backend
        await fetch('/api/v1/annotations/save-corrected/', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                dataset_id: this.currentDatasetId,
                session_id: this.currentSession,
                image_path: this.currentImagePath,
                annotations: this.convertToCOCO(),
                corrections: [correction]
            })
        });
    }
    
    /**
     * Convert annotations to COCO format
     */
    convertToCOCO() {
        return {
            images: [{
                id: 1,
                file_name: Path(this.currentImagePath).name,
                width: this.imageWidth,
                height: this.imageHeight
            }],
            annotations: this.annotations.map((ann, idx) => ({
                id: idx + 1,
                image_id: 1,
                category_id: this.getCategoryId(ann.properties.category),
                segmentation: ann.geometry.coordinates,
                area: this.calculateArea(ann.geometry),
                bbox: this.getBbox(ann.geometry),
                iscrowd: 0
            })),
            categories: this.getCategories()
        };
    }
}
```

#### 3.2 Training Dataset Management UI

**File:** `deepgis-xr/deepgis_xr/apps/web/templates/web/training_datasets.html` (new file)

```html
{% extends "base.html" %}

{% block content %}
<div class="container mt-4">
    <h1>Training Dataset Management</h1>
    
    <!-- Create New Dataset -->
    <div class="card mb-4">
        <div class="card-header">
            <h3>Create New Dataset</h3>
        </div>
        <div class="card-body">
            <form id="create-dataset-form">
                <div class="form-group">
                    <label>Dataset Name:</label>
                    <input type="text" id="dataset-name" class="form-control" required>
                </div>
                <div class="form-group">
                    <label>Description:</label>
                    <textarea id="dataset-description" class="form-control"></textarea>
                </div>
                <button type="submit" class="btn btn-primary">Create Dataset</button>
            </form>
        </div>
    </div>
    
    <!-- Dataset List -->
    <div class="card">
        <div class="card-header">
            <h3>Your Datasets</h3>
        </div>
        <div class="card-body">
            <table class="table" id="datasets-table">
                <thead>
                    <tr>
                        <th>Name</th>
                        <th>Annotations</th>
                        <th>Status</th>
                        <th>Created</th>
                        <th>Actions</th>
                    </tr>
                </thead>
                <tbody id="datasets-tbody">
                    <!-- Populated via JavaScript -->
                </tbody>
            </table>
        </div>
    </div>
    
    <!-- Training Panel -->
    <div class="card mt-4" id="training-panel" style="display: none;">
        <div class="card-header">
            <h3>Start Training</h3>
        </div>
        <div class="card-body">
            <form id="training-form">
                <div class="form-group">
                    <label>Model Name:</label>
                    <input type="text" id="model-name" class="form-control" value="Custom Mask2Former">
                </div>
                <div class="form-group">
                    <label>Version:</label>
                    <input type="text" id="model-version" class="form-control" value="1.0">
                </div>
                <div class="form-group">
                    <label>Epochs:</label>
                    <input type="number" id="num-epochs" class="form-control" value="10" min="1" max="100">
                </div>
                <div class="form-group">
                    <label>Learning Rate:</label>
                    <input type="number" id="learning-rate" class="form-control" value="0.0001" step="0.0001">
                </div>
                <button type="submit" class="btn btn-success">Start Training</button>
            </form>
        </div>
    </div>
</div>

<script src="{% static 'web/js/training-datasets.js' %}"></script>
{% endblock %}
```

---

### Phase 4: Integration Points

#### 4.1 Update AI Analysis Report

Add "Add to Training Dataset" button to AI analysis report page:

**File:** `deepgis_xr/apps/web/templates/web/ai_analysis_report.html`

```html
<!-- Add after action buttons section -->
{% if model_type == 'mask2former' %}
<div class="training-actions mt-3">
    <button class="btn btn-info" onclick="openCorrectionInterface('{{ session_id }}')">
        <i class="fas fa-edit"></i> Correct & Add to Training Dataset
    </button>
</div>
{% endif %}
```

#### 4.2 URL Routes

**File:** `deepgis_xr/apps/web/urls.py`

```python
# Training dataset management
path('training/datasets/', views.training_datasets, name='training_datasets'),
path('training/datasets/<int:dataset_id>/', views.training_dataset_detail, name='training_dataset_detail'),
path('training/correct/<str:session_id>/', views.correct_prediction, name='correct_prediction'),
```

---

## Implementation Checklist

### Backend
- [ ] Create `TrainingDataset`, `TrainingAnnotation`, `ModelVersion` models
- [ ] Run migrations
- [ ] Create annotation management API endpoints
- [ ] Implement `Mask2FormerTrainer` class
- [ ] Add training API endpoint
- [ ] Add Celery task for async training (optional)

### Frontend
- [ ] Create `Mask2FormerCorrector` JavaScript class
- [ ] Build correction UI component
- [ ] Create training dataset management page
- [ ] Add "Correct Predictions" button to AI analysis report
- [ ] Implement COCO format conversion utilities
- [ ] Add training job monitoring UI

### Integration
- [ ] Update AI analysis report template
- [ ] Add URL routes
- [ ] Test end-to-end workflow
- [ ] Add error handling and validation
- [ ] Document API endpoints

---

## Technical Considerations

### 1. COCO Format Conversion
- Mask2Former uses COCO format for training
- Need to convert GeoJSON predictions to COCO annotations
- Handle polygon to RLE (Run-Length Encoding) conversion

### 2. Model Versioning
- Store multiple model versions
- Allow switching between versions
- Track which version is deployed

### 3. Training Resources
- GPU required for training
- Consider using Celery for async training
- Monitor training progress

### 4. Data Quality
- Validate annotations before training
- Check for minimum dataset size
- Ensure category consistency

---

## Future Enhancements

1. **Active Learning**: Automatically select images for annotation
2. **Transfer Learning**: Fine-tune from previous model versions
3. **Evaluation Metrics**: Track mAP, IoU during training
4. **A/B Testing**: Compare model versions
5. **Automated Deployment**: Auto-deploy best-performing models

---

## References

- [Detectron2 Documentation](https://detectron2.readthedocs.io/)
- [Mask2Former Paper](https://arxiv.org/abs/2112.01527)
- [COCO Dataset Format](https://cocodataset.org/#format-data)

