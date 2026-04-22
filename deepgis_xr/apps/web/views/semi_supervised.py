"""
Semi-supervised labeling interface and helpers.

Moved out of the legacy `views.py` monolith in the Tier B refactor.
Drives the assisted-labeling workflow that combines Mask2Former /
Segment Anything for initial label proposals, then lets a labeler
refine and optionally persist the result into a training dataset.

Public handlers:
    label_semi_supervised        GET  /label/semi-supervised/
    generate_assisted_labels     POST /label/semi-supervised/api/generate-labels/
    save_assisted_labels         POST /label/semi-supervised/api/save-labels/
    get_label_images             GET  /label/semi-supervised/api/get-images/

Heavy dependencies (torch, the dreams_laboratory scripts, COCO
conversion utilities) are imported lazily so merely importing this
module stays cheap — the web process does not drag torch in at boot.
"""

import json

from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt

from deepgis_xr.apps.core.models import (
    CategoryLabel, CategoryType, Image, ImageLabel, Labeler,
    TrainingDataset, TrainingLabel,
)



def label_semi_supervised(request):
    """
    Main view for semi-supervised labeling interface.
    Uses Mask2Former and Segment Anything for assisted labeling.
    """
    return render(request, 'web/label_semi_supervised.html', {
        'page_title': 'Semi-Supervised Labeling Tool',
        'model_types': ['mask2former', 'segment_anything'],
    })


@csrf_exempt
def generate_assisted_labels(request):
    """
    API endpoint to generate labels using segmentation model.
    
    POST data:
    - image_id: ID of image to label
    - model_type: 'mask2former' or 'segment_anything'
    - confidence_threshold: minimum confidence for predictions
    
    Returns:
    - GeoJSON with predicted labels
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)
    
    try:
        data = json.loads(request.body)
        image_id = data.get('image_id')
        model_type = data.get('model_type', 'mask2former')
        confidence_threshold = float(data.get('confidence_threshold', 0.5))
        
        if not image_id:
            return JsonResponse({'error': 'image_id required'}, status=400)
        
        # Import the segmentation script functions
        import sys
        from pathlib import Path
        
        # Try to import from dreams_laboratory scripts
        project_root = Path(__file__).parent.parent.parent.parent.parent
        scripts_dir = project_root / 'dreams_laboratory' / 'scripts'
        
        if str(scripts_dir) not in sys.path:
            sys.path.insert(0, str(scripts_dir))
        
        try:
            from segmentation_assisted_labeling import (
                load_segmentation_model, 
                predict_segmentation,
                mask_to_geojson
            )
            
            # Get image from database
            image = Image.objects.get(id=image_id)
            image_path = Path(image.path)
            
            # Get categories
            categories = ['background'] + [cat.name for cat in CategoryType.objects.all().order_by('id')]
            
            # Load model (configure model path)
            model_path = scripts_dir / 'multispectral_segmentation_model.pth'
            config_path = scripts_dir / 'multispectral_vit.pth'
            
            if not model_path.exists():
                return JsonResponse({
                    'error': 'Model not found. Please train a model first.',
                    'model_path': str(model_path)
                }, status=404)
            
            # Load configuration
            import torch
            checkpoint = torch.load(str(config_path), map_location='cpu')
            config = checkpoint.get('config', checkpoint)
            config['num_classes'] = len(categories)
            
            device = 'cuda' if torch.cuda.is_available() else 'cpu'
            model = load_segmentation_model(str(model_path), config, device)
            
            # Predict
            mask = predict_segmentation(model, image_path, device, config['img_size'])
            
            # Convert to GeoJSON
            geojson = mask_to_geojson(
                mask, 
                categories,
                (image.height, image.width),
                confidence_threshold
            )
            
            return JsonResponse({
                'success': True,
                'geojson': geojson,
                'image_id': image_id,
                'num_predictions': len(geojson['features'])
            })
            
        except ImportError as e:
            return JsonResponse({
                'error': f'Segmentation script not available: {str(e)}',
                'suggestion': 'Make sure segmentation_assisted_labeling.py is in dreams_laboratory/scripts/'
            }, status=500)
        except Exception as e:
            return JsonResponse({
                'error': f'Error generating labels: {str(e)}',
                'type': type(e).__name__
            }, status=500)
            
    except Exception as e:
        return JsonResponse({
            'error': str(e),
            'type': type(e).__name__
        }, status=500)


@csrf_exempt
def save_assisted_labels(request):
    """
    API endpoint to save refined labels - EXTENDED for training dataset support.
    
    POST data:
    - image_id: ID of image
    - labels: GeoJSON FeatureCollection with refined labels
    - user_id: ID of user (labeler)
    - training_dataset_id: (NEW) Optional - add to training dataset
    - source_prediction_id: (NEW) Original Mask2Former session_id
    - corrections: (NEW) List of corrections made
    - time_taken: Optional time taken for labeling
    
    Returns:
    - success status
    - image_label_id: ID of created ImageLabel
    - training_dataset_linked: Whether label was linked to training dataset
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
        try:
            image = Image.objects.get(id=image_id)
        except Image.DoesNotExist:
            return JsonResponse({'error': f'Image {image_id} not found'}, status=404)
        
        # Get or create labeler
        labeler = None
        if request.user.is_authenticated:
            labeler, _ = Labeler.objects.get_or_create(user=request.user)
        else:
            # For anonymous users, try to find by user_id string
            try:
                from django.contrib.auth.models import User
                user = User.objects.get(username=user_id)
                labeler, _ = Labeler.objects.get_or_create(user=user)
            except User.DoesNotExist:
                pass  # No labeler for anonymous users
        
        # Create ImageLabel with combined_label_shapes (matching save_labels pattern)
        image_label = ImageLabel.objects.create(
            image=image,
            combined_label_shapes=json.dumps(labels_geojson),
            labeler=labeler,
            time_taken=data.get('time_taken')
        )
        
        # Create CategoryLabel records for each category (matching save_labels pattern)
        categories_by_name = {}
        for feature in labels_geojson.get('features', []):
            category_name = feature['properties'].get('category')
            if not category_name:
                continue
            
            # Get or create category
            if category_name not in categories_by_name:
                try:
                    category = CategoryType.objects.get(category_name=category_name)
                except CategoryType.DoesNotExist:
                    # Create category if it doesn't exist
                    color_hex = feature['properties'].get('color', '#FF0000')
                    color_hex = color_hex.lstrip('#')
                    rgb = tuple(int(color_hex[i:i+2], 16) for i in (0, 2, 4))
                    
                    from deepgis_xr.apps.core.models import Color
                    color, _ = Color.objects.get_or_create(
                        red=rgb[0],
                        green=rgb[1],
                        blue=rgb[2]
                    )
                    
                    category = CategoryType.objects.create(
                        category_name=category_name,
                        color=color,
                        label_type='P'  # Polygon by default
                    )
                
                categories_by_name[category_name] = {
                    'category': category,
                    'features': []
                }
            
            categories_by_name[category_name]['features'].append(feature)
        
        # Create CategoryLabel for each category
        saved_count = 0
        for category_name, cat_data in categories_by_name.items():
            feature_collection = {
                'type': 'FeatureCollection',
                'features': cat_data['features']
            }
            
            CategoryLabel.objects.create(
                category=cat_data['category'],
                label_shapes=json.dumps(feature_collection),
                parent_label=image_label
            )
            saved_count += 1
        
        # NEW: Link to training dataset if provided
        training_dataset_linked = False
        if training_dataset_id:
            try:
                dataset = TrainingDataset.objects.get(id=training_dataset_id, created_by=request.user)
                
                # Convert to COCO format and cache (if utility exists)
                try:
                    from deepgis_xr.apps.core.utils.training import convert_geojson_to_coco
                    coco_annotation = convert_geojson_to_coco(labels_geojson, image)
                    # Note: We'll add coco_annotation_json field to ImageLabel in a future migration
                    # For now, we'll store it in TrainingLabel
                except ImportError:
                    coco_annotation = None
                
                # Create training label link
                TrainingLabel.objects.create(
                    dataset=dataset,
                    image_label=image_label,
                    source_prediction_id=source_prediction_id,
                    corrections_made={'corrections': corrections}
                )
                
                training_dataset_linked = True
            except TrainingDataset.DoesNotExist:
                pass  # Dataset doesn't exist or user doesn't have access
        
        return JsonResponse({
            'success': True,
            'image_label_id': image_label.id,
            'saved_count': saved_count,
            'training_dataset_linked': training_dataset_linked
        })
        
    except Exception as e:
        import traceback
        return JsonResponse({
            'error': str(e),
            'traceback': traceback.format_exc()
        }, status=500)

@csrf_exempt
def get_label_images(request):
    """
    API endpoint to get list of images for labeling.
    
    Query params:
    - limit: max number of images to return
    - offset: pagination offset
    - unlabeled_only: if true, return only unlabeled images
    
    Returns:
    - list of images with metadata
    """
    try:
        limit = int(request.GET.get('limit', 50))
        offset = int(request.GET.get('offset', 0))
        unlabeled_only = request.GET.get('unlabeled_only', 'false').lower() == 'true'
        
        queryset = Image.objects.all()
        
        if unlabeled_only:
            # Filter to images with no labels
            queryset = queryset.filter(imagelabel__isnull=True).distinct()
        
        total_count = queryset.count()
        images = queryset[offset:offset+limit]
        
        image_list = []
        for img in images:
            label_count = ImageLabel.objects.filter(image=img).count()
            
            # Construct the full image URL
            image_url = None
            if hasattr(img, 'url') and img.url:
                image_url = img.url
            elif img.path:
                # If path is a directory, append the filename
                if img.path.endswith('/'):
                    image_url = img.path + img.name
                # If path already contains the full URL
                elif img.path.startswith('http://') or img.path.startswith('https://'):
                    image_url = img.path
                # If path is relative
                else:
                    image_url = f"/static/{img.path}"
            
            image_list.append({
                'id': img.id,
                'name': img.name,
                'path': img.path,
                'url': image_url,
                'width': img.width,
                'height': img.height,
                'label_count': label_count,
                'created_at': img.created_at.isoformat() if hasattr(img, 'created_at') else None
            })
        
        return JsonResponse({
            'success': True,
            'images': image_list,
            'total': total_count,
            'offset': offset,
            'limit': limit
        })
        
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500) 
