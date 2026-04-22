"""
Training dataset management REST endpoints.

Moved out of the legacy `views.py` monolith in the Tier B refactor.
These four handlers back the labeler-facing dataset panel (list existing
datasets, create a new one, view its annotations, and append an existing
ImageLabel to a dataset).

Public handlers:
    create_training_dataset   POST /api/training/datasets/create/
    list_training_datasets    GET  /api/training/datasets/
    get_dataset_details       GET  /api/training/datasets/<id>/
    add_label_to_dataset      POST /api/training/datasets/add-label/

Note: `get_label_images` (served at /label/semi-supervised/api/get-images/)
is semantically a semi-supervised labeling endpoint and stays in
legacy.py until the semi-supervised module is split out.
"""

import json

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from deepgis_xr.apps.core.models import (
    ImageLabel, TrainingDataset, TrainingLabel,
)


@csrf_exempt
@login_required
def create_training_dataset(request):
    """Create a new training dataset"""
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)
    
    try:
        data = json.loads(request.body)
        name = data.get('name')
        description = data.get('description', '')
        
        if not name:
            return JsonResponse({'error': 'name is required'}, status=400)
        
        # Check if dataset with this name already exists
        if TrainingDataset.objects.filter(name=name, created_by=request.user).exists():
            return JsonResponse({'error': 'Dataset with this name already exists'}, status=400)
        
        dataset = TrainingDataset.objects.create(
            name=name,
            description=description,
            created_by=request.user
        )
        
        return JsonResponse({
            'status': 'success',
            'dataset_id': dataset.id,
            'dataset_name': dataset.name
        })
        
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
@login_required
def list_training_datasets(request):
    """List all training datasets for the current user"""
    if request.method != 'GET':
        return JsonResponse({'error': 'GET required'}, status=405)
    
    try:
        datasets = TrainingDataset.objects.filter(created_by=request.user)
        
        return JsonResponse({
            'status': 'success',
            'datasets': [
                {
                    'id': d.id,
                    'name': d.name,
                    'description': d.description,
                    'num_annotations': d.num_annotations,
                    'num_images': d.num_images,
                    'status': d.status,
                    'created_at': d.created_at.isoformat(),
                    'updated_at': d.updated_at.isoformat()
                }
                for d in datasets
            ]
        })
        
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
@login_required
def get_dataset_details(request, dataset_id):
    """Get dataset details with annotations"""
    if request.method != 'GET':
        return JsonResponse({'error': 'GET required'}, status=405)
    
    try:
        dataset = TrainingDataset.objects.get(id=dataset_id, created_by=request.user)
        training_labels = dataset.training_labels.select_related(
            'image_label', 'image_label__image'
        ).all()
        
        annotations = []
        for tl in training_labels:
            il = tl.image_label
            annotations.append({
                'id': il.id,
                'image_id': il.image.id,
                'image_name': il.image.name,
                'image_path': il.image.path,
                'source_prediction_id': tl.source_prediction_id,
                'corrections': tl.corrections_made,
                'created_at': tl.created_at.isoformat()
            })
        
        return JsonResponse({
            'status': 'success',
            'dataset': {
                'id': dataset.id,
                'name': dataset.name,
                'description': dataset.description,
                'status': dataset.status,
                'num_annotations': dataset.num_annotations,
                'num_images': dataset.num_images,
                'created_at': dataset.created_at.isoformat(),
                'updated_at': dataset.updated_at.isoformat()
            },
            'annotations': annotations
        })
        
    except TrainingDataset.DoesNotExist:
        return JsonResponse({'error': 'Dataset not found'}, status=404)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
@login_required
def add_label_to_dataset(request):
    """Add existing ImageLabel to training dataset"""
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)
    
    try:
        data = json.loads(request.body)
        dataset_id = data.get('dataset_id')
        image_label_id = data.get('image_label_id')
        
        if not dataset_id or not image_label_id:
            return JsonResponse({'error': 'dataset_id and image_label_id required'}, status=400)
        
        dataset = TrainingDataset.objects.get(id=dataset_id, created_by=request.user)
        image_label = ImageLabel.objects.get(id=image_label_id)
        
        # Check if already in dataset
        if TrainingLabel.objects.filter(dataset=dataset, image_label=image_label).exists():
            return JsonResponse({
                'status': 'error',
                'message': 'Label already in dataset'
            }, status=400)
        
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
        
    except TrainingDataset.DoesNotExist:
        return JsonResponse({'error': 'Dataset not found'}, status=404)
    except ImageLabel.DoesNotExist:
        return JsonResponse({'error': 'ImageLabel not found'}, status=404)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)
