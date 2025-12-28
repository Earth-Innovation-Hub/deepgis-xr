"""
World Sampler API Views

Django views for integrating the world sampler with the DeepGIS Search frontend.
"""

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.utils import timezone
import json
import math
from typing import Optional

from .world_sampler import WorldSampler, SamplePoint
from .models import SampledLocation, SamplingSession, DistributionUpdate


# Global sampler instance (in production, use Django cache or database)
_global_sampler: Optional[WorldSampler] = None


def get_or_create_sampler(session_id: str = 'default') -> WorldSampler:
    """Get or create a sampler instance for a session"""
    global _global_sampler
    
    # In production, store per-session in cache/database
    # For now, use a single global instance
    if _global_sampler is None:
        _global_sampler = WorldSampler(
            num_points=1000,
            initialization='gaussian_mixture',
            seed=None  # Random seed
        )
    
    return _global_sampler


@require_http_methods(["POST"])
@csrf_exempt
def initialize_sampler(request):
    """
    Initialize a new sampler instance.
    
    POST /webclient/sampler/initialize
    Body: {
        "num_points": 1000,
        "initialization": "uniform" | "gaussian_mixture" | "population_weighted",
        "lat_range": [-90, 90],
        "lon_range": [-180, 180],
        "alt_range": [0, 5000],
        "seed": 42 (optional)
    }
    """
    try:
        data = json.loads(request.body)
        
        global _global_sampler
        _global_sampler = WorldSampler(
            num_points=data.get('num_points', 1000),
            lat_range=tuple(data.get('lat_range', [-90, 90])),
            lon_range=tuple(data.get('lon_range', [-180, 180])),
            alt_range=tuple(data.get('alt_range', [0, 5000])),
            initialization=data.get('initialization', 'uniform'),
            seed=data.get('seed')
        )
        
        stats = _global_sampler.get_statistics()
        
        return JsonResponse({
            'status': 'success',
            'message': 'Sampler initialized',
            'statistics': stats
        })
        
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': str(e)
        }, status=400)


@require_http_methods(["POST"])
@csrf_exempt
def sample_locations(request):
    """
    Sample n locations from the current distribution.
    
    POST /webclient/sampler/sample
    Body: {
        "n": 10,
        "method": "weighted" | "top_k",
        "session_id": "default" (optional)
    }
    
    Returns: {
        "status": "success",
        "samples": [
            {
                "lat": 28.0,
                "lon": 86.9,
                "alt": 5000.0,
                "weight": 0.001,
                "zoom": 20
            },
            ...
        ],
        "geojson": { ... }  // GeoJSON FeatureCollection
    }
    """
    try:
        data = json.loads(request.body)
        sampler = get_or_create_sampler()
        
        n = data.get('n', 10)
        method = data.get('method', 'weighted')
        session_id = data.get('session_id', 'default')
        
        # Get or create session
        session, _ = SamplingSession.objects.get_or_create(
            session_id=session_id,
            defaults={
                'num_points': sampler.num_points,
                'initialization_method': 'gaussian_mixture',
            }
        )
        
        samples = sampler.sample(n=n, method=method)
        
        # Save samples to database and convert to dict
        samples_data = []
        for s in samples:
            zoom = altitude_to_zoom_level(s.alt)
            
            # Save to database
            location, _ = SampledLocation.objects.get_or_create(
                latitude=round(s.lat, 6),
                longitude=round(s.lon, 6),
                altitude=round(s.alt, 2),
                session_id=session_id,
                defaults={
                    'zoom_level': zoom,
                    'score': 0.0,  # No feedback yet
                    'weight': s.weight,
                    'metadata': s.metadata or {},
                }
            )
            
            samples_data.append({
                'lat': s.lat,
                'lon': s.lon,
                'alt': s.alt,
                'weight': s.weight,
                'zoom': zoom,
                'metadata': s.metadata,
                'db_id': location.id
            })
        
        # Update session stats
        session.total_samples += len(samples)
        session.save()
        
        # Create GeoJSON for Cesium
        geojson = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "Point",
                        "coordinates": [s['lon'], s['lat'], s['alt']]
                    },
                    "properties": {
                        "weight": s['weight'],
                        "zoom": s['zoom'],
                        "metadata": s['metadata'],
                        "db_id": s['db_id']
                    }
                }
                for s in samples_data
            ]
        }
        
        return JsonResponse({
            'status': 'success',
            'samples': samples_data,
            'geojson': geojson,
            'statistics': sampler.get_statistics(),
            'session_id': session_id
        })
        
    except Exception as e:
        import traceback
        return JsonResponse({
            'status': 'error',
            'message': str(e),
            'traceback': traceback.format_exc()
        }, status=400)


def altitude_to_zoom_level(altitude: float) -> int:
    """
    Convert Cesium camera altitude to approximate zoom level.
    Cesium zoom levels roughly follow: altitude = 40075000 / (2^zoom)
    """
    if altitude <= 0:
        return 28  # Maximum zoom
    zoom = math.log2(40075000 / altitude)
    return max(0, min(28, int(round(zoom))))


@require_http_methods(["POST"])
@csrf_exempt
def update_distribution(request):
    """
    Update the sampling distribution based on feedback.
    
    POST /webclient/sampler/update
    Body: {
        "rule": "reward" | "exploration" | "concentration" | "custom",
        "feedback_points": [
            {"lat": 28.0, "lon": 86.9, "alt": 5000, "reward": 1.0, "zoom": 20},
            ...
        ],
        "params": {
            "learning_rate": 0.1,
            "radius": 100000,
            ...
        },
        "session_id": "default" (optional)
    }
    """
    try:
        data = json.loads(request.body)
        sampler = get_or_create_sampler()
        
        rule = data.get('rule', 'reward')
        feedback_points = data.get('feedback_points', [])
        params = data.get('params', {})
        session_id = data.get('session_id', 'default')
        
        # Get or create session
        session, _ = SamplingSession.objects.get_or_create(
            session_id=session_id,
            defaults={
                'num_points': sampler.num_points,
                'initialization_method': 'gaussian_mixture',
            }
        )
        
        # Save feedback points to database
        saved_locations = []
        for fp in feedback_points:
            lat = fp['lat']
            lon = fp['lon']
            alt = fp['alt']
            reward = fp.get('reward', 1.0)
            zoom = fp.get('zoom', altitude_to_zoom_level(alt))
            
            # Create or update sampled location
            location, created = SampledLocation.objects.get_or_create(
                latitude=round(lat, 6),
                longitude=round(lon, 6),
                altitude=round(alt, 2),
                session_id=session_id,
                defaults={
                    'zoom_level': zoom,
                    'score': reward,
                    'weight': fp.get('weight', 1.0),
                    'metadata': fp.get('metadata', {}),
                }
            )
            
            if not created:
                # Update existing location's score
                location.score = reward
                location.scored_at = timezone.now()
                location.save()
            else:
                location.scored_at = timezone.now()
                location.save()
            
            saved_locations.append(location)
        
        # Convert feedback points to tuples for sampler
        feedback_tuples = [
            (fp['lat'], fp['lon'], fp['alt'], fp.get('reward', 1.0))
            for fp in feedback_points
        ]
        
        # Apply update to in-memory sampler
        sampler.update_weights(
            rule=rule,
            feedback_points=feedback_tuples if feedback_tuples else None,
            **params
        )
        
        # Log the distribution update
        update = DistributionUpdate.objects.create(
            session=session,
            update_rule=rule,
            learning_rate=params.get('learning_rate', 0.1),
            radius=params.get('radius'),
            parameters=params,
        )
        update.feedback_locations.set(saved_locations)
        
        # Update session stats
        session.total_updates += 1
        session.save()
        
        stats = sampler.get_statistics()
        
        return JsonResponse({
            'status': 'success',
            'message': f'Distribution updated using {rule} rule',
            'statistics': stats,
            'num_updates': len(sampler.update_history),
            'db_saved': len(saved_locations),
            'session_id': session_id
        })
        
    except Exception as e:
        import traceback
        return JsonResponse({
            'status': 'error',
            'message': str(e),
            'traceback': traceback.format_exc()
        }, status=400)


@require_http_methods(["POST"])
@csrf_exempt
def query_region(request):
    """
    Query samples in a specific region.
    
    POST /webclient/sampler/query
    Body: {
        "lat": 28.0,
        "lon": 86.9,
        "alt": 5000,
        "radius": 100000  // meters
    }
    """
    try:
        data = json.loads(request.body)
        sampler = get_or_create_sampler()
        
        lat = data.get('lat')
        lon = data.get('lon')
        alt = data.get('alt', 0)
        radius = data.get('radius', 100000)
        
        if lat is None or lon is None:
            return JsonResponse({
                'status': 'error',
                'message': 'lat and lon are required'
            }, status=400)
        
        samples = sampler.query_region(lat, lon, alt, radius)
        
        samples_data = [
            {
                'lat': s.lat,
                'lon': s.lon,
                'alt': s.alt,
                'weight': s.weight,
                'metadata': s.metadata
            }
            for s in samples
        ]
        
        return JsonResponse({
            'status': 'success',
            'num_samples': len(samples),
            'samples': samples_data,
            'query': {
                'lat': lat,
                'lon': lon,
                'alt': alt,
                'radius': radius
            }
        })
        
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': str(e)
        }, status=400)


@require_http_methods(["GET"])
def get_statistics(request):
    """
    Get current sampler statistics.
    
    GET /webclient/sampler/statistics
    """
    try:
        sampler = get_or_create_sampler()
        stats = sampler.get_statistics()
        
        return JsonResponse({
            'status': 'success',
            'statistics': stats,
            'history': {
                'num_samples_taken': len(sampler.sample_history),
                'num_updates': len(sampler.update_history)
            }
        })
        
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': str(e)
        }, status=400)


@require_http_methods(["POST"])
@csrf_exempt
def reset_sampler(request):
    """
    Reset the sampler to initial state.
    
    POST /webclient/sampler/reset
    Body: {
        "keep_history": false
    }
    """
    try:
        data = json.loads(request.body) if request.body else {}
        sampler = get_or_create_sampler()
        
        keep_history = data.get('keep_history', False)
        sampler.reset(keep_history=keep_history)
        
        return JsonResponse({
            'status': 'success',
            'message': 'Sampler reset',
            'statistics': sampler.get_statistics()
        })
        
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': str(e)
        }, status=400)


@require_http_methods(["GET"])
def get_sample_history(request):
    """
    Get history of sampled locations.
    
    GET /webclient/sampler/history?limit=100&session_id=default
    """
    try:
        sampler = get_or_create_sampler()
        limit = int(request.GET.get('limit', 100))
        session_id = request.GET.get('session_id', 'default')
        
        history = sampler.sample_history[-limit:]
        
        history_data = [
            {
                'lat': s.lat,
                'lon': s.lon,
                'alt': s.alt,
                'weight': s.weight,
                'metadata': s.metadata
            }
            for s in history
        ]
        
        return JsonResponse({
            'status': 'success',
            'history': history_data,
            'total_samples': len(sampler.sample_history)
        })
        
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': str(e)
        }, status=400)


@require_http_methods(["GET"])
def get_scored_locations(request):
    """
    Get scored locations from the database.
    
    GET /webclient/sampler/scored?session_id=default&min_score=-10&limit=100
    """
    try:
        session_id = request.GET.get('session_id', 'default')
        min_score = float(request.GET.get('min_score', -10))
        limit = int(request.GET.get('limit', 100))
        
        locations = SampledLocation.objects.filter(
            session_id=session_id,
            scored_at__isnull=False,  # Only locations with feedback
            score__gte=min_score
        ).order_by('-score')[:limit]
        
        locations_data = [
            {
                'id': loc.id,
                'lat': loc.latitude,
                'lon': loc.longitude,
                'alt': loc.altitude,
                'zoom': loc.zoom_level,
                'score': loc.score,
                'weight': loc.weight,
                'sampled_at': loc.sampled_at.isoformat(),
                'scored_at': loc.scored_at.isoformat() if loc.scored_at else None,
                'metadata': loc.metadata
            }
            for loc in locations
        ]
        
        # Get session stats
        total_samples = SampledLocation.objects.filter(session_id=session_id).count()
        total_scored = SampledLocation.objects.filter(
            session_id=session_id,
            scored_at__isnull=False
        ).count()
        
        return JsonResponse({
            'status': 'success',
            'locations': locations_data,
            'total_samples': total_samples,
            'total_scored': total_scored,
            'session_id': session_id
        })
        
    except Exception as e:
        import traceback
        return JsonResponse({
            'status': 'error',
            'message': str(e),
            'traceback': traceback.format_exc()
        }, status=400)


@require_http_methods(["POST"])
@csrf_exempt
def analyze_viewport(request):
    """
    Analyze viewport image using Segment Anything Model (SAM).
    
    POST /webclient/sampler/analyze-viewport
    Body: {
        "image": "data:image/png;base64,...",  // Base64 encoded image
        "location": {
            "lon": -83.447567,
            "lat": 41.550336,
            "alt": 890.8,
            "heading": 353.3,
            "pitch": -8.7
        },
        "model_type": "vit_b" | "vit_l" | "vit_h",  // SAM model size
        "min_area": 100  // Minimum mask area in pixels
    }
    
    Returns: {
        "status": "success",
        "num_segments": 150,
        "segments": [
            {
                "area": 1234,
                "bbox": [x, y, w, h],
                "predicted_iou": 0.92,
                "stability_score": 0.95,
                "segmentation": "base64_mask"  // Binary mask
            },
            ...
        ],
        "geojson": { ... }  // GeoJSON with segment polygons
    }
    """
    try:
        import base64
        import io
        import sys
        from pathlib import Path
        from PIL import Image
        import numpy as np
        import json
        
        data = json.loads(request.body)
        image_data = data.get('image')
        location = data.get('location', {})
        analysis_type = data.get('model_type', 'sam')  # 'sam' or 'zero_shot'
        sam_model = data.get('sam_model', 'vit_b')  # For SAM: 'vit_b', 'vit_l', 'vit_h'
        min_area = data.get('min_area', 100)  # For SAM
        confidence_threshold = data.get('confidence_threshold', 0.5)  # For zero-shot
        
        if not image_data:
            return JsonResponse({
                'status': 'error',
                'message': 'Image data is required'
            }, status=400)
        
        # Decode base64 image
        try:
            # Remove data URL prefix if present
            if ',' in image_data:
                image_data = image_data.split(',')[1]
            image_bytes = base64.b64decode(image_data)
            image = Image.open(io.BytesIO(image_bytes)).convert('RGB')
        except Exception as e:
            return JsonResponse({
                'status': 'error',
                'message': f'Failed to decode image: {str(e)}'
            }, status=400)
        
        # Import SAM module
        # The scripts directory should already be in sys.path via Django settings
        # But we'll verify and add it if needed
        scripts_dir = None
        
        try:
            from django.conf import settings
            # Use the SCRIPTS_DIR from settings if available
            if hasattr(settings, 'SCRIPTS_DIR') and settings.SCRIPTS_DIR.exists():
                scripts_dir = settings.SCRIPTS_DIR
            else:
                # Fallback: resolve from BASE_DIR
                base_dir = Path(settings.BASE_DIR).resolve()
                scripts_dir = base_dir.parent / 'dreams_laboratory' / 'scripts'
        except Exception:
            pass
        
        # If still not found, try container paths
        if scripts_dir is None or not scripts_dir.exists():
            # Try container mount points (scripts mounted at /app/dreams_laboratory_scripts)
            for candidate_path in [
                Path('/app') / 'dreams_laboratory_scripts',  # Container mount
                Path('/app') / 'dreams_laboratory' / 'scripts',  # Alternative container path
                Path('/workspace') / 'dreams_laboratory' / 'scripts',
                Path('/code') / 'dreams_laboratory' / 'scripts'
            ]:
                if candidate_path.exists():
                    scripts_dir = candidate_path
                    break
        
        # Last resort: resolve from current file
        if scripts_dir is None or not scripts_dir.exists():
            current_file = Path(__file__).resolve()
            project_root = current_file.parent.parent.parent.parent.parent.resolve()
            scripts_dir = project_root / 'dreams_laboratory' / 'scripts'
        
        # Verify scripts directory exists
        if not scripts_dir.exists():
            return JsonResponse({
                'status': 'error',
                'message': f'Segmentation scripts directory not found',
                'debug': {
                    'tried_paths': [
                        str(Path('/app') / 'dreams_laboratory' / 'scripts'),
                        str(Path('/workspace') / 'dreams_laboratory' / 'scripts'),
                        str(Path('/code') / 'dreams_laboratory' / 'scripts'),
                        str(Path('/home/jdas/dreams-lab-website-server') / 'dreams_laboratory' / 'scripts') if Path('/home/jdas').exists() else 'N/A'
                    ],
                    'current_file': str(Path(__file__).resolve()),
                    'base_dir': str(Path(__file__).parent.parent.parent.parent.parent.resolve()) if hasattr(Path(__file__), 'parent') else 'N/A'
                }
            }, status=500)
        
        # Ensure scripts directory is in Python path
        scripts_dir_str = str(scripts_dir.resolve())
        if scripts_dir_str not in sys.path:
            sys.path.insert(0, scripts_dir_str)
        
        # Route to appropriate analysis based on analysis_type
        if analysis_type == 'zero_shot':
            # Zero-Shot Detection path
            return _analyze_viewport_zero_shot(image, location, confidence_threshold, scripts_dir)
        elif analysis_type == 'mask2former':
            # Mask2Former path (pre-trained COCO)
            return _analyze_viewport_mask2former(image, location, confidence_threshold, scripts_dir)
        elif analysis_type == 'yolov8':
            # YOLOv8 path (fast object detection)
            yolo_model = data.get('yolo_model', 'yolov8n')
            class_filter = data.get('class_filter', '')
            return _analyze_viewport_yolov8(image, location, confidence_threshold, yolo_model, class_filter, scripts_dir)
        elif analysis_type == 'grounding_dino':
            # Grounding DINO path (open-vocabulary text-based detection)
            text_prompt = data.get('text_prompt', 'object')
            box_threshold = data.get('box_threshold', 0.3)
            text_threshold = data.get('text_threshold', 0.25)
            return _analyze_viewport_grounding_dino(image, location, text_prompt, box_threshold, text_threshold, scripts_dir)
        elif analysis_type == 'grounded_sam':
            # Grounded-SAM-2 path (detection + high-quality segmentation)
            text_prompt = data.get('text_prompt', 'object')
            box_threshold = data.get('box_threshold', 0.35)
            text_threshold = data.get('text_threshold', 0.25)
            return _analyze_viewport_grounded_sam(image, location, text_prompt, box_threshold, text_threshold, scripts_dir)
        elif analysis_type == 'prithvi':
            # Prithvi-EO path (Earth Observation foundation model)
            return _analyze_viewport_prithvi(image, location, scripts_dir)
        else:
            # SAM path (default)
            return _analyze_viewport_sam(image, location, sam_model, min_area, scripts_dir)
    
    except Exception as e:
        import traceback
        return JsonResponse({
            'status': 'error',
            'message': str(e),
            'traceback': traceback.format_exc()
        }, status=500)


def _analyze_viewport_sam(image, location, model_type, min_area, scripts_dir):
    """Internal function to handle SAM analysis."""
    try:
        import sys
        from pathlib import Path
        import numpy as np
        import json
        from datetime import datetime
        import importlib
        import torch
        from PIL import Image
        from django.conf import settings
        
        # Check if SAM library is available FIRST (before importing the wrapper)
        try:
            from segment_anything import sam_model_registry, SamAutomaticMaskGenerator
            sam_available = True
        except ImportError as import_err:
            sam_available = False
            return JsonResponse({
                'status': 'error',
                'message': 'Segment Anything library not installed',
                'suggestion': 'Install with: pip install git+https://github.com/facebookresearch/segment-anything.git',
                'note': 'This package must be installed in the Docker container. Add to requirements.txt and rebuild.',
                'debug': {
                    'import_error': str(import_err),
                    'scripts_dir': str(scripts_dir)
                }
            }, status=500)
        
        # Now import the wrapper (it will work since SAM is available)
        try:
            # Force reload the module to ensure SAM_AVAILABLE is updated
            import importlib
            if 'segment_anything_rocks' in sys.modules:
                importlib.reload(sys.modules['segment_anything_rocks'])
            from segment_anything_rocks import SegmentAnythingRocks
        except ImportError as e:
            return JsonResponse({
                'status': 'error',
                'message': f'Segment Anything Model script not found: {str(e)}',
                'suggestion': f'Ensure segment_anything_rocks.py is in {scripts_dir}',
                'debug': {
                    'scripts_dir': str(scripts_dir),
                    'scripts_dir_exists': scripts_dir.exists(),
                    'segment_anything_rocks_exists': (scripts_dir / 'segment_anything_rocks.py').exists() if scripts_dir.exists() else False
                }
            }, status=500)
        
        # Check GPU availability
        import torch
        cuda_available = torch.cuda.is_available()
        device_info = {
            'cuda_available': cuda_available,
            'device': 'cuda' if cuda_available else 'cpu'
        }
        if cuda_available:
            device_info['gpu_name'] = torch.cuda.get_device_name(0)
            device_info['gpu_count'] = torch.cuda.device_count()
        
        # Initialize SAM
        try:
            if cuda_available:
                segmenter = SegmentAnythingRocks(model_type=model_type, device='cuda')
            else:
                segmenter = SegmentAnythingRocks(model_type=model_type, device='cpu')
        except Exception as e:
            # Fallback to CPU if CUDA fails
            if cuda_available:
                try:
                    segmenter = SegmentAnythingRocks(model_type=model_type, device='cpu')
                    device_info['device'] = 'cpu'  # Update device info
                    device_info['cuda_failed'] = str(e)
                except Exception as e2:
                    error_msg = str(e2)
                # Check if it's the SAM_AVAILABLE check
                if 'SAM_AVAILABLE' in error_msg or 'Segment Anything not installed' in error_msg:
                    # Force reload and try again
                    import importlib
                    if 'segment_anything_rocks' in sys.modules:
                        importlib.reload(sys.modules['segment_anything_rocks'])
                    try:
                        segmenter = SegmentAnythingRocks(model_type=model_type, device='cpu')
                    except Exception as e3:
                        return JsonResponse({
                            'status': 'error',
                            'message': f'Failed to initialize SAM after reload: {str(e3)}',
                            'suggestion': 'Restart Django server to clear module cache',
                            'debug': {
                                'original_error': error_msg,
                                'reload_error': str(e3)
                            }
                        }, status=500)
                else:
                    return JsonResponse({
                        'status': 'error',
                        'message': f'Failed to initialize SAM: {error_msg}',
                        'debug': {
                            'model_type': model_type,
                            'tried_cuda': True,
                            'tried_cpu': True
                        }
                    }, status=500)
        
        # Create organized directory structure for saving results
        from django.conf import settings
        from datetime import datetime
        
        # Use shared deepgis_results folder (mounted from host)
        # This allows direct access to results from the host filesystem
        sam_results_dir = Path('/app/deepgis_results') / 'sam_results'
        sam_results_dir.mkdir(parents=True, exist_ok=True)
        
        # Create descriptive folder name with timestamp and location
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        lat_str = f"{location.get('lat', 0):.6f}".replace('.', 'p').replace('-', 'n')
        lon_str = f"{location.get('lon', 0):.6f}".replace('.', 'p').replace('-', 'n')
        alt_str = f"{location.get('alt', 0):.0f}m"
        folder_name = f"sam_{timestamp}_lat{lat_str}_lon{lon_str}_alt{alt_str}_model{model_type}"
        session_dir = sam_results_dir / folder_name
        session_dir.mkdir(parents=True, exist_ok=True)
        
        # Extract session ID for report URL (use folder name as session identifier)
        session_id = folder_name
        
        # Save original query image
        query_image_path = session_dir / 'query_image.png'
        image.save(query_image_path)
        
        # Save image temporarily for SAM processing
        import tempfile
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp_file:
            image.save(tmp_file.name)
            tmp_path = Path(tmp_file.name)
        
        try:
            # Run segmentation
            masks, processed_image = segmenter.segment_image(tmp_path)
            
            # Filter by minimum area
            filtered_masks = [m for m in masks if m['area'] >= min_area]
            
            # Limit number of segments to prevent response size issues
            # Sort by quality (predicted_iou) and take top N
            MAX_SEGMENTS = 200  # Reasonable limit for viewport display
            if len(filtered_masks) > MAX_SEGMENTS:
                # Sort by quality (predicted_iou * stability_score) and take best
                filtered_masks.sort(key=lambda m: m.get('predicted_iou', 0) * m.get('stability_score', 0), reverse=True)
                filtered_masks = filtered_masks[:MAX_SEGMENTS]
                print(f"Limited segments from {len(masks)} to {MAX_SEGMENTS} top-quality segments")
            
            # Use SAM's built-in export_to_geojson method
            geojson = segmenter.export_to_geojson(filtered_masks, image.size)
            
            # Simplify GeoJSON polygons to reduce response size
            # This reduces coordinate points while maintaining shape
            MAX_COORDS_PER_POLYGON = 100  # Maximum coordinate points per polygon
            
            simplified_features = []
            for feature in geojson.get('features', []):
                try:
                    coords = feature['geometry']['coordinates'][0]  # Get polygon coordinates
                    
                    # If polygon has too many points, simplify by sampling
                    if len(coords) > MAX_COORDS_PER_POLYGON:
                        # Sample every Nth point to reduce size
                        step = max(1, len(coords) // MAX_COORDS_PER_POLYGON)
                        simplified_coords = coords[::step]
                        
                        # Ensure polygon is closed (first point = last point)
                        if len(simplified_coords) > 0 and simplified_coords[0] != simplified_coords[-1]:
                            simplified_coords.append(simplified_coords[0])
                        
                        # Update feature with simplified coordinates
                        simplified_feature = {
                            'type': feature['type'],
                            'geometry': {
                                'type': feature['geometry']['type'],
                                'coordinates': [simplified_coords]
                            },
                            'properties': feature.get('properties', {})
                        }
                        simplified_features.append(simplified_feature)
                    else:
                        # Keep original if small enough
                        simplified_features.append(feature)
                except Exception as e:
                    # If simplification fails, use original
                    print(f"Warning: Could not simplify polygon: {e}")
                    simplified_features.append(feature)
            
            geojson['features'] = simplified_features
            
            # Log response size estimate
            import sys
            geojson_size = sys.getsizeof(json.dumps(geojson))
            print(f"GeoJSON size: ~{geojson_size / 1024:.1f} KB ({len(simplified_features)} features)")
            
            # Save visualization with masks overlay
            visualization_path = None
            try:
                visualization = segmenter.visualize_masks(processed_image, filtered_masks)
                visualization_path = session_dir / 'segmentation_visualization.jpg'
                visualization.save(visualization_path, quality=95)
            except Exception as viz_error:
                print(f"Warning: Could not save visualization: {viz_error}")
            
            # Save GeoJSON
            geojson_path = session_dir / 'segments.geojson'
            with open(geojson_path, 'w') as f:
                json.dump(geojson, f, indent=2)
            
            # Save metadata
            metadata = {
                'timestamp': timestamp,
                'location': location,
                'model_type': model_type,
                'min_area': min_area,
                'image_size': [image.width, image.height],
                'num_segments': len(filtered_masks),
                'device_info': device_info,
                'session_dir': str(session_dir.relative_to('/app/deepgis_results'))
            }
            metadata_path = session_dir / 'metadata.json'
            with open(metadata_path, 'w') as f:
                json.dump(metadata, f, indent=2)
            
            # Save individual mask images (optional, for large numbers of segments)
            if len(filtered_masks) <= 50:  # Only save individual masks if reasonable number
                masks_dir = session_dir / 'individual_masks'
                masks_dir.mkdir(exist_ok=True)
                for i, mask_data in enumerate(filtered_masks):
                    mask = mask_data['segmentation']
                    mask_array = (mask.astype(np.uint8) * 255)
                    mask_image = Image.fromarray(mask_array)
                    mask_path = masks_dir / f'mask_{i+1:04d}_area{mask_data["area"]}.png'
                    mask_image.save(mask_path)
            
            # Prepare response with segment metadata (without base64 masks to keep response small)
            # The frontend only needs the GeoJSON for visualization, not the individual mask images
            segments_data = []
            for i, mask_data in enumerate(filtered_masks):
                segments_data.append({
                    "segment_id": i + 1,
                    "area": int(mask_data['area']),
                    "bbox": [int(x) for x in mask_data['bbox']],
                    "predicted_iou": float(mask_data.get('predicted_iou', 0.0)),
                    "stability_score": float(mask_data.get('stability_score', 0.0))
                    # Note: Removed base64-encoded mask images to keep response size manageable
                    # Individual mask images are saved to disk in individual_masks/ folder if needed
                })
            
            # Extract session ID for report URL (use folder name as session identifier)
            session_id = folder_name
            
            return JsonResponse({
                'status': 'success',
                'num_segments': len(filtered_masks),
                'segments': segments_data,
                'geojson': geojson,
                'location': location,
                'image_size': [image.width, image.height],
                'model_type': model_type,
                'device_info': device_info,  # Include GPU/CPU info
                'saved_to': {
                    'session_dir': str(session_dir.relative_to('/app/deepgis_results')),
                    'query_image': str(query_image_path.relative_to('/app/deepgis_results')),
                    'visualization': str(visualization_path.relative_to('/app/deepgis_results')) if visualization_path else None,
                    'geojson': str(geojson_path.relative_to('/app/deepgis_results')),
                    'metadata': str(metadata_path.relative_to('/app/deepgis_results')),
                    'host_path': str(session_dir).replace('/app/deepgis_results', './deepgis_results')
                },
                'report_url': f'/label/ai-analysis/report/{session_id}/'
            })
            
        finally:
            # Clean up temporary file
            if tmp_path.exists():
                tmp_path.unlink()
        
    except Exception as e:
        import traceback
        error_traceback = traceback.format_exc()
        print(f"\n❌ SAM Analysis Error:")
        print(f"Error message: {str(e)}")
        print(f"Traceback:\n{error_traceback}")
        return JsonResponse({
            'status': 'error',
            'message': str(e),
            'traceback': error_traceback
        }, status=500)


def _analyze_viewport_zero_shot(image, location, confidence_threshold, scripts_dir):
    """Internal function to handle Zero-Shot Detection analysis."""
    try:
        import sys
        from pathlib import Path
        import numpy as np
        import json
        from datetime import datetime
        import torch
        import tempfile
        
        # Import zero-shot detection module
        try:
            from zero_shot_detection import ZeroShotMaskRCNN, predictions_to_geojson
        except ImportError as e:
            return JsonResponse({
                'status': 'error',
                'message': f'Zero-Shot Detection script not found: {str(e)}',
                'suggestion': f'Ensure zero_shot_detection.py is in {scripts_dir}',
                'debug': {
                    'scripts_dir': str(scripts_dir),
                    'scripts_dir_exists': scripts_dir.exists(),
                    'zero_shot_exists': (scripts_dir / 'zero_shot_detection.py').exists() if scripts_dir.exists() else False
                }
            }, status=500)
        
        # Check GPU availability
        cuda_available = torch.cuda.is_available()
        device_info = {
            'cuda_available': cuda_available,
            'device': 'cuda' if cuda_available else 'cpu'
        }
        if cuda_available:
            device_info['gpu_name'] = torch.cuda.get_device_name(0)
            device_info['gpu_count'] = torch.cuda.device_count()
        
        # Create results directory
        zero_shot_results_dir = Path('/app/deepgis_results') / 'zero_shot_results'
        zero_shot_results_dir.mkdir(parents=True, exist_ok=True)
        
        # Create descriptive folder name
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        lat_str = f"{location.get('lat', 0):.6f}".replace('.', 'p').replace('-', 'n')
        lon_str = f"{location.get('lon', 0):.6f}".replace('.', 'p').replace('-', 'n')
        alt_str = f"{location.get('alt', 0):.0f}m"
        folder_name = f"zero_shot_{timestamp}_lat{lat_str}_lon{lon_str}_alt{alt_str}_conf{confidence_threshold:.2f}"
        session_dir = zero_shot_results_dir / folder_name
        session_dir.mkdir(parents=True, exist_ok=True)
        
        # Save query image
        query_image_path = session_dir / 'query_image.png'
        image.save(query_image_path)
        
        # Save image temporarily for processing
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp_file:
            image.save(tmp_file.name)
            tmp_path = Path(tmp_file.name)
        
        try:
            # Initialize detector
            device = 'cuda' if cuda_available else 'cpu'
            detector = ZeroShotMaskRCNN(confidence_threshold=confidence_threshold, device=device)
            
            # Run detection
            predictions = detector.predict(tmp_path)
            
            # Convert to GeoJSON
            geojson = predictions_to_geojson(predictions)
            
            # Save visualization
            visualization_path = None
            try:
                visualization = detector.visualize(tmp_path, predictions)
                visualization_path = session_dir / 'detection_visualization.jpg'
                visualization.save(visualization_path, quality=95)
            except Exception as viz_error:
                print(f"Warning: Could not save visualization: {viz_error}")
            
            # Save GeoJSON
            geojson_path = session_dir / 'detections.geojson'
            with open(geojson_path, 'w') as f:
                json.dump(geojson, f, indent=2)
            
            # Save metadata
            metadata = {
                'timestamp': timestamp,
                'location': location,
                'model_type': 'zero_shot',
                'confidence_threshold': confidence_threshold,
                'image_size': [image.width, image.height],
                'num_detections': predictions['num_detections'],
                'device_info': device_info,
                'session_dir': str(session_dir.relative_to('/app/deepgis_results'))
            }
            metadata_path = session_dir / 'metadata.json'
            with open(metadata_path, 'w') as f:
                json.dump(metadata, f, indent=2)
            
            # Prepare response with detection metadata
            detections_data = []
            for i, det in enumerate(predictions['detections']):
                detections_data.append({
                    "detection_id": i + 1,
                    "class_name": det['class_name'],
                    "class_id": det['class_id'],
                    "confidence": float(det['confidence']),
                    "bbox": [float(x) for x in det['bbox']],
                    "area": int(det.get('mask_area', 0))
                })
            
            return JsonResponse({
                'status': 'success',
                'num_detections': predictions['num_detections'],
                'detections': detections_data,
                'geojson': geojson,
                'location': location,
                'image_size': [image.width, image.height],
                'model_type': 'zero_shot',
                'device_info': device_info,
                'saved_to': {
                    'session_dir': str(session_dir.relative_to('/app/deepgis_results')),
                    'query_image': str(query_image_path.relative_to('/app/deepgis_results')),
                    'visualization': str(visualization_path.relative_to('/app/deepgis_results')) if visualization_path else None,
                    'geojson': str(geojson_path.relative_to('/app/deepgis_results')),
                    'metadata': str(metadata_path.relative_to('/app/deepgis_results')),
                    'host_path': str(session_dir).replace('/app/deepgis_results', './deepgis_results')
                },
                'report_url': f'/label/ai-analysis/report/{session_id}/'
            })
            
        finally:
            # Clean up temporary file
            if tmp_path.exists():
                tmp_path.unlink()
        
    except Exception as e:
        import traceback
        return JsonResponse({
            'status': 'error',
            'message': str(e),
            'traceback': traceback.format_exc()
        }, status=500)



def _analyze_viewport_mask2former(image, location, confidence_threshold, scripts_dir):
    """Internal function to handle Mask2Former (pre-trained COCO) analysis."""
    try:
        import sys
        from pathlib import Path
        import numpy as np
        import json
        from datetime import datetime
        import torch
        import tempfile
        
        # Import zero-shot detection module (contains ZeroShotMask2Former)
        try:
            from zero_shot_detection import ZeroShotMask2Former, predictions_to_geojson
        except ImportError as e:
            return JsonResponse({
                'status': 'error',
                'message': f'Zero-Shot Detection script not found: {str(e)}',
                'suggestion': f'Ensure zero_shot_detection.py is in {scripts_dir}',
                'debug': {
                    'scripts_dir': str(scripts_dir),
                    'scripts_dir_exists': scripts_dir.exists(),
                    'zero_shot_exists': (scripts_dir / 'zero_shot_detection.py').exists() if scripts_dir.exists() else False
                }
            }, status=500)
        
        # Check GPU availability
        cuda_available = torch.cuda.is_available()
        device_info = {
            'cuda_available': cuda_available,
            'device': 'cuda' if cuda_available else 'cpu'
        }
        if cuda_available:
            device_info['gpu_name'] = torch.cuda.get_device_name(0)
            device_info['gpu_count'] = torch.cuda.device_count()
        
        # Create results directory
        mask2former_results_dir = Path('/app/deepgis_results') / 'mask2former_results'
        mask2former_results_dir.mkdir(parents=True, exist_ok=True)
        
        # Create descriptive folder name
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        lat_str = f"{location.get('lat', 0):.6f}".replace('.', 'p').replace('-', 'n')
        lon_str = f"{location.get('lon', 0):.6f}".replace('.', 'p').replace('-', 'n')
        alt_str = f"{location.get('alt', 0):.0f}m"
        folder_name = f"mask2former_{timestamp}_lat{lat_str}_lon{lon_str}_alt{alt_str}_conf{confidence_threshold:.2f}"
        session_dir = mask2former_results_dir / folder_name
        session_dir.mkdir(parents=True, exist_ok=True)
        
        # Extract session ID for report URL
        session_id = folder_name
        
        # Save query image
        query_image_path = session_dir / 'query_image.png'
        image.save(query_image_path)
        
        # Save image temporarily for processing
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp_file:
            image.save(tmp_file.name)
            tmp_path = Path(tmp_file.name)
        
        try:
            # Initialize Mask2Former detector (pre-trained COCO)
            device = 'cuda' if cuda_available else 'cpu'
            detector = ZeroShotMask2Former(confidence_threshold=confidence_threshold, device=device)
            
            # Run detection
            predictions = detector.predict(tmp_path)
            
            # Convert to GeoJSON
            geojson = predictions_to_geojson(predictions)
            
            # Save visualization (if available)
            visualization_path = None
            try:
                # Note: ZeroShotMask2Former doesn't have a visualize method like ZeroShotMaskRCNN
                # We can create a simple visualization using PIL
                from PIL import ImageDraw, ImageFont
                vis_image = image.copy()
                draw = ImageDraw.Draw(vis_image)
                
                # Try to load a font
                try:
                    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 16)
                except:
                    font = ImageFont.load_default()
                
                # Colors for different classes
                colors = [
                    (255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0),
                    (255, 0, 255), (0, 255, 255), (128, 0, 0), (0, 128, 0)
                ]
                
                # Draw bounding boxes and labels
                for i, det in enumerate(predictions['detections']):
                    color = colors[i % len(colors)]
                    bbox = det['bbox']
                    label = f"{det['class_name']}: {det['confidence']:.2f}"
                    
                    # Draw bounding box
                    draw.rectangle(bbox, outline=color, width=3)
                    
                    # Draw label background
                    text_bbox = draw.textbbox((bbox[0], bbox[1] - 20), label, font=font)
                    draw.rectangle(text_bbox, fill=color)
                    draw.text((bbox[0], bbox[1] - 20), label, fill='white', font=font)
                
                visualization_path = session_dir / 'detection_visualization.jpg'
                vis_image.save(visualization_path, quality=95)
            except Exception as viz_error:
                print(f"Warning: Could not save visualization: {viz_error}")
            
            # Save GeoJSON
            geojson_path = session_dir / 'detections.geojson'
            with open(geojson_path, 'w') as f:
                json.dump(geojson, f, indent=2)
            
            # Save metadata
            metadata = {
                'timestamp': timestamp,
                'location': location,
                'model_type': 'mask2former_coco',
                'confidence_threshold': confidence_threshold,
                'image_size': [image.width, image.height],
                'num_detections': predictions['num_detections'],
                'device_info': device_info,
                'session_dir': str(session_dir.relative_to('/app/deepgis_results'))
            }
            metadata_path = session_dir / 'metadata.json'
            with open(metadata_path, 'w') as f:
                json.dump(metadata, f, indent=2)
            
            # Prepare response with detection metadata
            detections_data = []
            for i, det in enumerate(predictions['detections']):
                detections_data.append({
                    "detection_id": i + 1,
                    "class_name": det['class_name'],
                    "class_id": det['class_id'],
                    "confidence": float(det['confidence']),
                    "bbox": [float(x) for x in det['bbox']],
                    "area": int(det.get('mask_area', 0)) if 'mask_area' in det else 0
                })
            
            return JsonResponse({
                'status': 'success',
                'num_detections': predictions['num_detections'],
                'detections': detections_data,
                'geojson': geojson,
                'location': location,
                'image_size': [image.width, image.height],
                'model_type': 'mask2former',
                'device_info': device_info,
                'saved_to': {
                    'session_dir': str(session_dir.relative_to('/app/deepgis_results')),
                    'query_image': str(query_image_path.relative_to('/app/deepgis_results')),
                    'visualization': str(visualization_path.relative_to('/app/deepgis_results')) if visualization_path else None,
                    'geojson': str(geojson_path.relative_to('/app/deepgis_results')),
                    'metadata': str(metadata_path.relative_to('/app/deepgis_results')),
                    'host_path': str(session_dir).replace('/app/deepgis_results', './deepgis_results')
                },
                'report_url': f'/label/ai-analysis/report/{session_id}/'
            })
            
        finally:
            # Clean up temporary file
            if tmp_path.exists():
                tmp_path.unlink()
        
    except Exception as e:
        import traceback
        return JsonResponse({
            'status': 'error',
            'message': str(e),
            'traceback': traceback.format_exc()
        }, status=500)


def _analyze_viewport_yolov8(image, location, confidence_threshold, yolo_model, class_filter, scripts_dir):
    """Internal function to handle YOLOv8 object detection analysis."""
    try:
        import sys
        from pathlib import Path
        import numpy as np
        import json
        from datetime import datetime
        import torch
        from PIL import Image, ImageDraw, ImageFont
        from django.conf import settings
        
        # Ensure scripts directory is in path
        if str(scripts_dir) not in sys.path:
            sys.path.insert(0, str(scripts_dir))
        
        # Import the YOLO detector
        try:
            from yolo_detection import YOLODetector, COCO_CLASSES
        except ImportError as e:
            return JsonResponse({
                'status': 'error',
                'message': f'YOLOv8 detection script not found: {str(e)}',
                'suggestion': 'Install ultralytics: pip install ultralytics',
                'debug': {
                    'scripts_dir': str(scripts_dir),
                    'sys_path': sys.path[:5],
                    'yolo_detection_exists': (scripts_dir / 'yolo_detection.py').exists() if scripts_dir.exists() else False
                }
            }, status=500)
        
        # Check GPU availability
        cuda_available = torch.cuda.is_available()
        device_info = {'cuda_available': cuda_available}
        
        if cuda_available:
            device_info['device'] = 'cuda'
            device_info['gpu_name'] = torch.cuda.get_device_name(0)
            device_info['gpu_memory'] = f'{torch.cuda.get_device_properties(0).total_memory / 1024**3:.1f} GB'
        else:
            device_info['device'] = 'cpu'
        
        # Initialize detector
        device = 'cuda' if cuda_available else 'cpu'
        try:
            detector = YOLODetector(model_type=yolo_model, device=device, model_dir='/app/models')
        except Exception as e:
            return JsonResponse({
                'status': 'error',
                'message': f'Failed to initialize YOLOv8: {str(e)}',
                'suggestion': 'Make sure ultralytics is properly installed',
                'device_info': device_info
            }, status=500)
        
        # Create organized directory structure for saving results
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        lat_str = f"lat{location.get('lat', 0):.6f}".replace('.', 'p').replace('-', 'n')
        lon_str = f"lon{location.get('lon', 0):.6f}".replace('.', 'p').replace('-', 'n')
        alt_str = f"alt{int(location.get('alt', 0))}m"
        
        yolo_results_dir = Path('/app/deepgis_results') / 'yolov8_results'
        yolo_results_dir.mkdir(parents=True, exist_ok=True)
        
        # Create session folder
        folder_name = f"yolov8_{timestamp}_{lat_str}_{lon_str}_{alt_str}"
        session_dir = yolo_results_dir / folder_name
        session_dir.mkdir(exist_ok=True)
        
        # Save query image
        query_image_path = session_dir / 'query_image.png'
        image.save(query_image_path, format='PNG')
        
        # Parse class filter if provided
        class_names = None
        if class_filter and class_filter.strip():
            class_names = [c.strip() for c in class_filter.split(',') if c.strip()]
        
        try:
            print(f"🔍 Running YOLOv8 detection...")
            print(f"   Model: {yolo_model}")
            print(f"   Confidence: {confidence_threshold}")
            print(f"   Class filter: {class_names if class_names else 'All classes'}")
            
            # Run detection
            detections = detector.detect(
                image,
                confidence=confidence_threshold,
                class_names=class_names
            )
            
            num_detections = detections['num_detections']
            print(f"✓ Found {num_detections} objects")
            
            # Convert to GeoJSON
            geojson = detector.to_geojson(
                detections,
                image.width,
                image.height,
                viewport_bounds=None  # No geo bounds for now
            )
            
            # Create visualization
            visualization_path = None
            try:
                vis_image = detector.visualize(image, detections)
                visualization_path = session_dir / 'detection_visualization.jpg'
                vis_image.save(visualization_path, quality=95)
            except Exception as viz_error:
                print(f"Warning: Could not save visualization: {viz_error}")
            
            # Save GeoJSON
            geojson_path = session_dir / 'detections.geojson'
            with open(geojson_path, 'w') as f:
                json.dump(geojson, f, indent=2)
            
            # Session ID matches folder name for report lookup
            session_id = folder_name
            
            # Save metadata
            metadata = {
                'timestamp': timestamp,
                'location': location,
                'model_type': yolo_model,
                'confidence_threshold': confidence_threshold,
                'class_filter': class_filter if class_filter else None,
                'image_size': [image.width, image.height],
                'num_detections': num_detections,
                'device_info': device_info,
                'session_dir': str(session_dir.relative_to('/app/deepgis_results'))
            }
            metadata_path = session_dir / 'metadata.json'
            with open(metadata_path, 'w') as f:
                json.dump(metadata, f, indent=2)
            
            # Prepare response with detection metadata
            detections_data = []
            for i in range(num_detections):
                bbox = detections['boxes'][i] if len(detections['boxes']) > i else [0, 0, 0, 0]
                detections_data.append({
                    "detection_id": i + 1,
                    "class_name": detections['class_names'][i] if len(detections['class_names']) > i else 'unknown',
                    "class_id": int(detections['class_ids'][i]) if len(detections['class_ids']) > i else -1,
                    "confidence": float(detections['scores'][i]) if len(detections['scores']) > i else 0.0,
                    "bbox": [float(x) for x in bbox]
                })
            
            return JsonResponse({
                'status': 'success',
                'num_detections': num_detections,
                'detections': detections_data,
                'geojson': geojson,
                'location': location,
                'image_size': [image.width, image.height],
                'model_type': 'yolov8',
                'yolo_model': yolo_model,
                'device_info': device_info,
                'saved_to': {
                    'session_dir': str(session_dir.relative_to('/app/deepgis_results')),
                    'query_image': str(query_image_path.relative_to('/app/deepgis_results')),
                    'visualization': str(visualization_path.relative_to('/app/deepgis_results')) if visualization_path else None,
                    'geojson': str(geojson_path.relative_to('/app/deepgis_results')),
                    'metadata': str(metadata_path.relative_to('/app/deepgis_results')),
                    'host_path': str(session_dir).replace('/app/deepgis_results', './deepgis_results')
                },
                'report_url': f'/label/ai-analysis/report/{session_id}/'
            })
            
        except Exception as detection_error:
            import traceback
            return JsonResponse({
                'status': 'error',
                'message': f'YOLOv8 detection failed: {str(detection_error)}',
                'traceback': traceback.format_exc(),
                'device_info': device_info
            }, status=500)
        
    except Exception as e:
        import traceback
        return JsonResponse({
            'status': 'error',
            'message': str(e),
            'traceback': traceback.format_exc()
        }, status=500)


def _analyze_viewport_grounding_dino(image, location, text_prompt, box_threshold, text_threshold, scripts_dir):
    """
    Internal function to handle Grounding DINO (text-based detection) analysis.
    
    Supports two modes:
    1. Remote API mode: If GROUNDING_DINO_API_URL is configured, calls the remote Docker API
    2. Local mode: Falls back to local GroundingDINODetector if no remote API configured
    """
    try:
        import sys
        import io
        import base64
        from pathlib import Path
        import json
        from datetime import datetime
        from PIL import Image, ImageDraw, ImageFont
        from django.conf import settings
        import requests
        
        # Check if remote API is configured
        api_url = getattr(settings, 'GROUNDING_DINO_API_URL', None)
        use_remote_api = api_url is not None and api_url.strip() != ''
        
        # Create organized directory structure for saving results
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        lat_str = f"lat{location.get('lat', 0):.6f}".replace('.', 'p').replace('-', 'n')
        lon_str = f"lon{location.get('lon', 0):.6f}".replace('.', 'p').replace('-', 'n')
        alt_str = f"alt{int(location.get('alt', 0))}m"
        
        grounding_dino_results_dir = Path('/app/deepgis_results') / 'grounding_dino_results'
        grounding_dino_results_dir.mkdir(parents=True, exist_ok=True)
        
        # Create session folder
        folder_name = f"grounding_dino_{timestamp}_{lat_str}_{lon_str}_{alt_str}"
        session_dir = grounding_dino_results_dir / folder_name
        session_dir.mkdir(exist_ok=True)
        
        # Save query image
        query_image_path = session_dir / 'query_image.png'
        image.save(query_image_path, format='PNG')
        
        print(f"🔍 Running Grounding DINO detection...")
        print(f"   Text prompt: '{text_prompt}'")
        print(f"   Box threshold: {box_threshold}")
        print(f"   Text threshold: {text_threshold}")
        print(f"   Mode: {'Remote API' if use_remote_api else 'Local'}")
        
        if use_remote_api:
            # ============================================
            # REMOTE API MODE - Call Docker container API
            # ============================================
            print(f"   API URL: {api_url}")
            
            device_info = {
                'mode': 'remote_api',
                'api_url': api_url,
                'device': 'remote_gpu'
            }
            
            # Convert PIL image to JPEG bytes for API (more compatible than PNG)
            img_buffer = io.BytesIO()
            # Convert to RGB if necessary (in case of RGBA images)
            if image.mode in ('RGBA', 'LA', 'P'):
                rgb_image = Image.new('RGB', image.size, (255, 255, 255))
                if image.mode == 'P':
                    image = image.convert('RGBA')
                rgb_image.paste(image, mask=image.split()[-1] if image.mode == 'RGBA' else None)
                rgb_image.save(img_buffer, format='JPEG', quality=95)
            else:
                image.save(img_buffer, format='JPEG', quality=95)
            img_buffer.seek(0)
            
            try:
                # Call remote Grounding DINO API
                # API expects multipart/form-data with:
                # - file: image file (JPEG recommended)
                # - text_prompt: string (e.g., "rock . boulder . crater")
                # - box_threshold: float
                # - text_threshold: float
                print(f"   Sending request to {api_url}/api/predict")
                print(f"   Image size: {image.width}x{image.height}, buffer size: {img_buffer.getbuffer().nbytes} bytes")
                
                response = requests.post(
                    f"{api_url.rstrip('/')}/api/predict",
                    files={'file': ('viewport.jpg', img_buffer, 'image/jpeg')},
                    data={
                        'text_prompt': text_prompt,
                        'box_threshold': box_threshold,
                        'text_threshold': text_threshold
                    },
                    timeout=120  # 2 minute timeout for large images
                )
                
                # Check response status and get details
                if response.status_code != 200:
                    error_detail = ""
                    try:
                        error_json = response.json()
                        error_detail = error_json.get('detail', str(error_json))
                    except:
                        error_detail = response.text[:500] if response.text else "No error details"
                    
                    print(f"❌ API returned {response.status_code}: {error_detail}")
                    return JsonResponse({
                        'status': 'error',
                        'message': f'Grounding DINO API error: HTTP {response.status_code}',
                        'detail': error_detail,
                        'api_url': api_url,
                        'suggestion': 'Check container logs: docker logs grounding-dino-api'
                    }, status=502)
                
                api_result = response.json()
                
                # Check if API call was successful
                if not api_result.get('success', False):
                    error_msg = api_result.get('error', 'Unknown error from API')
                    print(f"❌ API returned error: {error_msg}")
                    return JsonResponse({
                        'status': 'error',
                        'message': f'Grounding DINO API error: {error_msg}',
                        'api_url': api_url
                    }, status=500)
                
                predictions = api_result.get('predictions', {})
                num_detections = predictions.get('count', 0)
                print(f"✓ API response received: {num_detections} detections")
                
            except requests.exceptions.ConnectionError as e:
                return JsonResponse({
                    'status': 'error',
                    'message': f'Cannot connect to Grounding DINO API at {api_url}',
                    'suggestion': 'Ensure the Grounding DINO Docker container is running',
                    'debug': {
                        'api_url': api_url,
                        'error': str(e)
                    }
                }, status=503)
            except requests.exceptions.Timeout:
                return JsonResponse({
                    'status': 'error',
                    'message': 'Grounding DINO API request timed out',
                    'suggestion': 'The image may be too large or the server is under heavy load',
                    'api_url': api_url
                }, status=504)
            except Exception as e:
                import traceback
                return JsonResponse({
                    'status': 'error',
                    'message': f'Grounding DINO API request failed: {str(e)}',
                    'traceback': traceback.format_exc(),
                    'api_url': api_url
                }, status=500)
            
            # Parse API response
            # API returns (per reference guide):
            # {
            #   "success": true,
            #   "predictions": {
            #     "boxes": [[x1, y1, x2, y2], ...],  # NORMALIZED coordinates (0-1)
            #     "logits": [0.95, 0.87, ...],
            #     "phrases": ["rock", "boulder", ...],
            #     "count": 5
            #   },
            #   "annotated_image": "base64_encoded_image",
            #   "result_url": "/api/result/filename.jpg"
            # }
            
            predictions = api_result.get('predictions', {})
            num_detections = predictions.get('count', 0)
            print(f"✓ Found {num_detections} objects via remote API")
            
            # Get image dimensions (use PIL image size)
            img_width = image.width
            img_height = image.height
            
            # Convert normalized corner coordinates to pixel coordinates
            # API format: [x1, y1, x2, y2] (normalized 0-1)
            # Our format: [x1, y1, x2, y2] (pixel coordinates)
            api_boxes = predictions.get('boxes', [])
            api_logits = predictions.get('logits', [])
            api_phrases = predictions.get('phrases', [])
            
            detections_data = []
            for i in range(num_detections):
                if i < len(api_boxes):
                    # Convert normalized coords to pixel coords
                    x1_norm, y1_norm, x2_norm, y2_norm = api_boxes[i]
                    x1 = x1_norm * img_width
                    y1 = y1_norm * img_height
                    x2 = x2_norm * img_width
                    y2 = y2_norm * img_height
                    bbox = [x1, y1, x2, y2]
                else:
                    bbox = [0, 0, 0, 0]
                
                score = api_logits[i] if i < len(api_logits) else 0.0
                label = api_phrases[i] if i < len(api_phrases) else 'object'
                
                detections_data.append({
                    "detection_id": i + 1,
                    "class_name": label,
                    "confidence": float(score),
                    "bbox": [float(x) for x in bbox]
                })
            
            # Save annotated image if provided by API
            visualization_path = None
            annotated_image_data = api_result.get('annotated_image')
            if annotated_image_data:
                try:
                    # Remove data URL prefix if present (e.g., "data:image/jpeg;base64,")
                    if ',' in annotated_image_data:
                        annotated_image_data = annotated_image_data.split(',')[1]
                    annotated_bytes = base64.b64decode(annotated_image_data)
                    annotated_image = Image.open(io.BytesIO(annotated_bytes))
                    visualization_path = session_dir / 'detection_visualization.jpg'
                    annotated_image.save(visualization_path, quality=95)
                    print(f"✓ Saved annotated image from API")
                except Exception as viz_error:
                    print(f"Warning: Could not save annotated image: {viz_error}")
            
            # Create visualization locally if not provided by API
            if visualization_path is None and num_detections > 0:
                try:
                    visualization_path = _create_grounding_dino_visualization(
                        image, detections_data, session_dir
                    )
                except Exception as viz_error:
                    print(f"Warning: Could not create visualization: {viz_error}")
            
        else:
            # ============================================
            # LOCAL MODE - Use local GroundingDINODetector
            # ============================================
            import torch
            
            # Ensure scripts directory is in path
            if str(scripts_dir) not in sys.path:
                sys.path.insert(0, str(scripts_dir))
            
            # Import the Grounding DINO wrapper
            try:
                from grounding_dino_detection import GroundingDINODetector
            except ImportError as e:
                return JsonResponse({
                    'status': 'error',
                    'message': f'Grounding DINO not available locally and no remote API configured',
                    'suggestion': 'Either set GROUNDING_DINO_API_URL environment variable or install Grounding DINO locally',
                    'debug': {
                        'scripts_dir': str(scripts_dir),
                        'import_error': str(e),
                        'grounding_dino_exists': (scripts_dir / 'grounding_dino_detection.py').exists() if scripts_dir.exists() else False
                    }
                }, status=500)
            
            # Check GPU availability
            cuda_available = torch.cuda.is_available()
            device_info = {'cuda_available': cuda_available, 'mode': 'local'}
            
            if cuda_available:
                device_info['device'] = 'cuda'
                device_info['gpu_name'] = torch.cuda.get_device_name(0)
                device_info['gpu_memory'] = f'{torch.cuda.get_device_properties(0).total_memory / 1024**3:.1f} GB'
            else:
                device_info['device'] = 'cpu'
            
            # Initialize detector
            detector = None
            device = 'cuda' if cuda_available else 'cpu'
            
            if cuda_available:
                try:
                    detector = GroundingDINODetector(model_type='swin_t', device='cuda')
                except Exception as e:
                    print(f"⚠ CUDA initialization failed: {e}")
                    print("⚠ Falling back to CPU mode...")
                    device = 'cpu'
                    device_info['device'] = 'cpu'
                    device_info['cuda_fallback'] = True
            
            if detector is None:
                try:
                    detector = GroundingDINODetector(model_type='swin_t', device='cpu')
                except Exception as e:
                    return JsonResponse({
                        'status': 'error',
                        'message': f'Failed to initialize Grounding DINO: {str(e)}',
                        'suggestion': 'Configure GROUNDING_DINO_API_URL to use remote API instead',
                        'device_info': device_info
                    }, status=500)
            
            # Run detection
            detections = detector.detect(
                image,
                text_prompt=text_prompt,
                box_threshold=box_threshold,
                text_threshold=text_threshold
            )
            
            num_detections = detections['num_detections']
            print(f"✓ Found {num_detections} objects locally")
            
            # Convert to standard format
            detections_data = []
            for i, (box, score, phrase) in enumerate(zip(detections['boxes'], detections['logits'], detections['phrases'])):
                detections_data.append({
                    "detection_id": i + 1,
                    "class_name": phrase,
                    "confidence": float(score),
                    "bbox": [float(x) for x in box]
                })
            
            # Save visualization
            visualization_path = None
            try:
                visualization = detector.visualize(image, detections)
                visualization_path = session_dir / 'detection_visualization.jpg'
                visualization.save(visualization_path, quality=95)
            except Exception as viz_error:
                print(f"Warning: Could not save visualization: {viz_error}")
        
        # ============================================
        # Common processing for both modes
        # ============================================
        
        # Convert detections to GeoJSON (pixel coordinates)
        geojson = _detections_to_geojson(detections_data, image.width, image.height)
        
        # Save GeoJSON
        geojson_path = session_dir / 'detections.geojson'
        with open(geojson_path, 'w') as f:
            json.dump(geojson, f, indent=2)
        
        # Save metadata
        metadata = {
            'timestamp': timestamp,
            'location': location,
            'text_prompt': text_prompt,
            'box_threshold': box_threshold,
            'text_threshold': text_threshold,
            'image_size': [image.width, image.height],
            'num_detections': num_detections,
            'device_info': device_info,
            'session_dir': str(session_dir.relative_to('/app/deepgis_results'))
        }
        metadata_path = session_dir / 'metadata.json'
        with open(metadata_path, 'w') as f:
            json.dump(metadata, f, indent=2)
        
        session_id = folder_name
        
        return JsonResponse({
            'status': 'success',
            'num_detections': num_detections,
            'detections': detections_data,
            'geojson': geojson,
            'location': location,
            'image_size': [image.width, image.height],
            'model_type': 'grounding_dino',
            'text_prompt': text_prompt,
            'device_info': device_info,
            'saved_to': {
                'session_dir': str(session_dir.relative_to('/app/deepgis_results')),
                'query_image': str(query_image_path.relative_to('/app/deepgis_results')),
                'visualization': str(visualization_path.relative_to('/app/deepgis_results')) if visualization_path else None,
                'geojson': str(geojson_path.relative_to('/app/deepgis_results')),
                'metadata': str(metadata_path.relative_to('/app/deepgis_results')),
                'host_path': str(session_dir).replace('/app/deepgis_results', './deepgis_results')
            },
            'report_url': f'/label/ai-analysis/report/{session_id}/'
        })
        
    except Exception as e:
        import traceback
        error_traceback = traceback.format_exc()
        print(f"\n❌ Grounding DINO Analysis Error:")
        print(f"Error message: {str(e)}")
        print(f"Traceback:\n{error_traceback}")
        return JsonResponse({
            'status': 'error',
            'message': str(e),
            'traceback': error_traceback
        }, status=500)


def _analyze_viewport_grounded_sam(image, location, text_prompt, box_threshold, text_threshold, scripts_dir):
    """
    Internal function to handle Grounded-SAM-2 (detection + segmentation) analysis.
    
    Calls remote Grounded-SAM-2 API for combined detection and instance segmentation.
    """
    try:
        import sys
        import io
        import base64
        from pathlib import Path
        import json
        from datetime import datetime
        from PIL import Image, ImageDraw, ImageFont
        from django.conf import settings
        import requests
        
        # Check if remote API is configured
        api_url = getattr(settings, 'GROUNDED_SAM_API_URL', None)
        if not api_url or api_url.strip() == '':
            return JsonResponse({
                'status': 'error',
                'message': 'Grounded-SAM API URL not configured',
                'suggestion': 'Set GROUNDED_SAM_API_URL environment variable'
            }, status=503)
        
        # Create organized directory structure for saving results
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        lat_str = f"lat{location.get('lat', 0):.6f}".replace('.', 'p').replace('-', 'n')
        lon_str = f"lon{location.get('lon', 0):.6f}".replace('.', 'p').replace('-', 'n')
        alt_str = f"alt{int(location.get('alt', 0))}m"
        
        grounded_sam_results_dir = Path('/app/deepgis_results') / 'grounded_sam_results'
        grounded_sam_results_dir.mkdir(parents=True, exist_ok=True)
        
        # Create session folder
        folder_name = f"grounded_sam_{timestamp}_{lat_str}_{lon_str}_{alt_str}"
        session_dir = grounded_sam_results_dir / folder_name
        session_dir.mkdir(exist_ok=True)
        
        # Save query image
        query_image_path = session_dir / 'query_image.png'
        image.save(query_image_path, format='PNG')
        
        print(f"🎯 Running Grounded-SAM-2 detection + segmentation...")
        print(f"   Text prompt: '{text_prompt}'")
        print(f"   Box threshold: {box_threshold}")
        print(f"   Text threshold: {text_threshold}")
        print(f"   API URL: {api_url}")
        
        # Convert PIL image to JPEG bytes for API
        img_buffer = io.BytesIO()
        if image.mode in ('RGBA', 'LA', 'P'):
            rgb_image = Image.new('RGB', image.size, (255, 255, 255))
            if image.mode == 'P':
                image = image.convert('RGBA')
            rgb_image.paste(image, mask=image.split()[-1] if image.mode == 'RGBA' else None)
            rgb_image.save(img_buffer, format='JPEG', quality=95)
        else:
            image.save(img_buffer, format='JPEG', quality=95)
        img_buffer.seek(0)
        
        device_info = {
            'mode': 'remote_api',
            'api_url': api_url,
            'device': 'remote_gpu'
        }
        
        try:
            # Call Grounded-SAM-2 API
            print(f"   Sending request to {api_url}/detect")
            print(f"   Image size: {image.width}x{image.height}")
            
            response = requests.post(
                f"{api_url.rstrip('/')}/detect",
                files={'image': ('viewport.jpg', img_buffer, 'image/jpeg')},
                data={
                    'text_prompt': text_prompt,
                    'box_threshold': box_threshold,
                    'text_threshold': text_threshold
                },
                timeout=180  # 3 minute timeout (segmentation takes longer)
            )
            
            if response.status_code != 200:
                error_detail = ""
                try:
                    error_json = response.json()
                    error_detail = error_json.get('error', str(error_json))
                except:
                    error_detail = response.text[:500] if response.text else "No error details"
                
                print(f"❌ API returned {response.status_code}: {error_detail}")
                return JsonResponse({
                    'status': 'error',
                    'message': f'Grounded-SAM API error: HTTP {response.status_code}',
                    'detail': error_detail,
                    'api_url': api_url
                }, status=502)
            
            api_result = response.json()
            
            if not api_result.get('success', False):
                error_msg = api_result.get('error', 'Unknown error from API')
                print(f"❌ API returned error: {error_msg}")
                return JsonResponse({
                    'status': 'error',
                    'message': f'Grounded-SAM API error: {error_msg}',
                    'api_url': api_url
                }, status=500)
            
            results = api_result.get('results', {})
            num_detections = results.get('num_detections', 0)
            detections = results.get('detections', [])
            print(f"✓ API response received: {num_detections} detections")
            
        except requests.exceptions.ConnectionError as e:
            return JsonResponse({
                'status': 'error',
                'message': f'Cannot connect to Grounded-SAM API at {api_url}',
                'suggestion': 'Ensure the Grounded-SAM-2 Docker container is running'
            }, status=503)
        except requests.exceptions.Timeout:
            return JsonResponse({
                'status': 'error',
                'message': 'Grounded-SAM API request timed out',
                'suggestion': 'Segmentation takes longer - wait or reduce image size'
            }, status=504)
        
        # Parse detections and convert to our format
        img_width = image.width
        img_height = image.height
        
        detections_data = []
        for i, det in enumerate(detections):
            label = det.get('label', 'object')
            confidence = det.get('confidence', 0.0)
            box = det.get('box', [0, 0, 0, 0])  # [x1, y1, x2, y2] in pixels
            
            detections_data.append({
                "detection_id": i + 1,
                "class_name": label,
                "confidence": float(confidence),
                "bbox": [float(x) for x in box]
            })
        
        # Save annotated image from API if available
        visualization_path = None
        output_image_url = api_result.get('output_image')
        if output_image_url:
            try:
                # Download the annotated image from API
                result_response = requests.get(f"{api_url.rstrip('')}{output_image_url}", timeout=30)
                if result_response.status_code == 200:
                    visualization_path = session_dir / 'segmentation_visualization.jpg'
                    with open(visualization_path, 'wb') as f:
                        f.write(result_response.content)
                    print(f"✓ Saved annotated image from API")
            except Exception as viz_error:
                print(f"Warning: Could not download annotated image: {viz_error}")
        
        # Create GeoJSON from detections (bounding boxes as polygons)
        features = []
        for det in detections_data:
            bbox = det['bbox']
            x1, y1, x2, y2 = bbox
            
            # Normalize coordinates (0-1) for consistency
            coords = [
                [x1/img_width, y1/img_height],
                [x2/img_width, y1/img_height],
                [x2/img_width, y2/img_height],
                [x1/img_width, y2/img_height],
                [x1/img_width, y1/img_height]
            ]
            
            feature = {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [coords]
                },
                "properties": {
                    "detection_id": det['detection_id'],
                    "class_name": det['class_name'],
                    "category": det['class_name'],
                    "confidence": det['confidence'],
                    "class_id": det['detection_id']
                }
            }
            features.append(feature)
        
        geojson = {
            "type": "FeatureCollection",
            "features": features
        }
        
        # Save GeoJSON
        geojson_path = session_dir / 'detections.geojson'
        with open(geojson_path, 'w') as f:
            json.dump(geojson, f, indent=2)
        
        # Save metadata
        metadata = {
            "timestamp": timestamp,
            "model": "grounded_sam",
            "model_name": "Grounded-SAM-2",
            "text_prompt": text_prompt,
            "box_threshold": box_threshold,
            "text_threshold": text_threshold,
            "num_detections": num_detections,
            "location": location,
            "image_size": [img_width, img_height],
            "device_info": device_info
        }
        
        metadata_path = session_dir / 'metadata.json'
        with open(metadata_path, 'w') as f:
            json.dump(metadata, f, indent=2)
        
        session_id = folder_name
        
        return JsonResponse({
            'status': 'success',
            'num_detections': num_detections,
            'detections': detections_data,
            'geojson': geojson,
            'location': location,
            'image_size': [img_width, img_height],
            'model_type': 'grounded_sam',
            'text_prompt': text_prompt,
            'device_info': device_info,
            'saved_to': {
                'session_dir': str(session_dir.relative_to('/app/deepgis_results')),
                'query_image': str(query_image_path.relative_to('/app/deepgis_results')),
                'visualization': str(visualization_path.relative_to('/app/deepgis_results')) if visualization_path else None,
                'geojson': str(geojson_path.relative_to('/app/deepgis_results')),
                'metadata': str(metadata_path.relative_to('/app/deepgis_results')),
                'host_path': str(session_dir).replace('/app/deepgis_results', './deepgis_results')
            },
            'report_url': f'/label/ai-analysis/report/{session_id}/'
        })
        
    except Exception as e:
        import traceback
        error_traceback = traceback.format_exc()
        print(f"\n❌ Grounded-SAM Analysis Error:")
        print(f"Error message: {str(e)}")
        print(f"Traceback:\n{error_traceback}")
        return JsonResponse({
            'status': 'error',
            'message': str(e),
            'traceback': error_traceback
        }, status=500)


def _create_grounding_dino_visualization(image, detections_data, session_dir):
    """Create a visualization with bounding boxes and labels."""
    from PIL import ImageDraw, ImageFont
    
    vis_image = image.copy()
    draw = ImageDraw.Draw(vis_image)
    
    # Try to load a font
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 16)
    except:
        font = ImageFont.load_default()
    
    # Colors for different classes
    colors = [
        (255, 87, 51), (51, 255, 87), (51, 87, 255), (255, 255, 51),
        (255, 51, 255), (51, 255, 255), (255, 128, 0), (128, 0, 255)
    ]
    
    for i, det in enumerate(detections_data):
        color = colors[i % len(colors)]
        bbox = det['bbox']
        label = f"{det['class_name']}: {det['confidence']:.2f}"
        
        # Draw bounding box
        draw.rectangle(bbox, outline=color, width=3)
        
        # Draw label background
        text_bbox = draw.textbbox((bbox[0], bbox[1] - 20), label, font=font)
        draw.rectangle(text_bbox, fill=color)
        draw.text((bbox[0], bbox[1] - 20), label, fill='white', font=font)
    
    visualization_path = session_dir / 'detection_visualization.jpg'
    vis_image.save(visualization_path, quality=95)
    return visualization_path


def _detections_to_geojson(detections_data, image_width, image_height):
    """Convert detections to GeoJSON format with normalized coordinates."""
    features = []
    
    for det in detections_data:
        bbox = det['bbox']
        # Normalize coordinates to 0-1 range
        x1, y1, x2, y2 = bbox
        norm_x1 = x1 / image_width
        norm_y1 = y1 / image_height
        norm_x2 = x2 / image_width
        norm_y2 = y2 / image_height
        
        # Create polygon from bounding box
        coordinates = [[
            [norm_x1, norm_y1],
            [norm_x2, norm_y1],
            [norm_x2, norm_y2],
            [norm_x1, norm_y2],
            [norm_x1, norm_y1]  # Close the polygon
        ]]
        
        feature = {
            "type": "Feature",
            "geometry": {
                "type": "Polygon",
                "coordinates": coordinates
            },
            "properties": {
                "detection_id": det['detection_id'],
                "class_name": det['class_name'],
                "confidence": det['confidence'],
                "bbox_pixels": bbox
            }
        }
        features.append(feature)
    
    return {
        "type": "FeatureCollection",
        "features": features
    }


def _analyze_viewport_prithvi(image, location, scripts_dir):
    """
    Internal function to handle Prithvi-EO-2.0 analysis.
    
    Prithvi is an Earth Observation foundation model that can:
    - Extract rich features from satellite imagery
    - Support multi-temporal analysis
    - Work with multi-spectral data (6 bands: Blue, Green, Red, NIR, SWIR, SWIR2)
    
    For this minimal integration, we use Prithvi as a feature extractor
    on the viewport RGB image.
    """
    try:
        import sys
        import io
        import base64
        from pathlib import Path
        import json
        from datetime import datetime
        from PIL import Image
        import numpy as np
        from django.conf import settings
        import torch
        
        # Create organized directory structure for saving results
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        lat_str = f"lat{location.get('lat', 0):.6f}".replace('.', 'p').replace('-', 'n')
        lon_str = f"lon{location.get('lon', 0):.6f}".replace('.', 'p').replace('-', 'n')
        alt_str = f"alt{int(location.get('alt', 0))}m"
        
        prithvi_results_dir = Path('/app/deepgis_results') / 'prithvi_results'
        prithvi_results_dir.mkdir(parents=True, exist_ok=True)
        
        # Create session folder
        folder_name = f"prithvi_{timestamp}_{lat_str}_{lon_str}_{alt_str}"
        session_dir = prithvi_results_dir / folder_name
        session_dir.mkdir(exist_ok=True)
        
        # Save query image
        query_image_path = session_dir / 'query_image.png'
        image.save(query_image_path, format='PNG')
        
        print(f"🌍 Running Prithvi-EO-2.0 feature extraction...")
        print(f"   Location: {location.get('lat', 0):.6f}, {location.get('lon', 0):.6f}")
        
        # Check if TerraTorch is available (recommended way to use Prithvi)
        try:
            from terratorch.registry import BACKBONE_REGISTRY
            terratorch_available = True
        except ImportError:
            terratorch_available = False
            print("   ⚠️  TerraTorch not available, trying HuggingFace transformers...")
        
        # Check GPU availability
        cuda_available = torch.cuda.is_available()
        device = 'cuda' if cuda_available else 'cpu'
        device_info = {
            'cuda_available': cuda_available,
            'device': device
        }
        if cuda_available:
            device_info['gpu_name'] = torch.cuda.get_device_name(0)
            device_info['gpu_count'] = torch.cuda.device_count()
        
        # Try to load Prithvi model
        model_loaded = False
        feature_vector = None
        model_info = {}
        
        if terratorch_available:
            try:
                print("   📦 Loading Prithvi-EO-2.0-300M-TL via TerraTorch...")
                model = BACKBONE_REGISTRY.build("prithvi_eo_v2_300m_tl", pretrained=True)
                model.eval()
                if cuda_available:
                    model = model.cuda()
                model_loaded = True
                model_info['source'] = 'terratorch'
                model_info['model_name'] = 'prithvi_eo_v2_300m_tl'
                print("   ✅ Prithvi model loaded successfully")
            except Exception as e:
                print(f"   ⚠️  Failed to load via TerraTorch: {str(e)}")
                # Try smaller model
                try:
                    print("   📦 Trying Prithvi-EO-2.0-100M-TL...")
                    model = BACKBONE_REGISTRY.build("prithvi_eo_v2_100m_tl", pretrained=True)
                    model.eval()
                    if cuda_available:
                        model = model.cuda()
                    model_loaded = True
                    model_info['source'] = 'terratorch'
                    model_info['model_name'] = 'prithvi_eo_v2_100m_tl'
                    print("   ✅ Prithvi-100M model loaded successfully")
                except Exception as e2:
                    print(f"   ⚠️  Failed to load 100M model: {str(e2)}")
        
        if not model_loaded:
            # Try HuggingFace transformers as fallback
            try:
                from transformers import AutoModel, AutoImageProcessor
                print("   📦 Loading Prithvi-EO-2.0-300M-TL via HuggingFace...")
                model_name = "ibm-nasa-geospatial/Prithvi-EO-2.0-300M-TL"
                processor = AutoImageProcessor.from_pretrained(model_name)
                model = AutoModel.from_pretrained(model_name)
                model.eval()
                if cuda_available:
                    model = model.cuda()
                model_loaded = True
                model_info['source'] = 'huggingface'
                model_info['model_name'] = model_name
                print("   ✅ Prithvi model loaded via HuggingFace")
            except ImportError:
                return JsonResponse({
                    'status': 'error',
                    'message': 'Prithvi dependencies not installed',
                    'suggestion': 'Install with: pip install terratorch OR pip install transformers',
                    'note': 'TerraTorch is recommended for Prithvi models. Add to requirements.txt and rebuild Docker container.',
                    'device_info': device_info
                }, status=500)
            except Exception as e:
                return JsonResponse({
                    'status': 'error',
                    'message': f'Failed to load Prithvi model: {str(e)}',
                    'suggestion': 'Ensure model weights are downloaded and GPU memory is available',
                    'device_info': device_info
                }, status=500)
        
        if not model_loaded:
            return JsonResponse({
                'status': 'error',
                'message': 'Could not load Prithvi model',
                'device_info': device_info
            }, status=500)
        
        # Prepare image for Prithvi
        # Prithvi expects multi-spectral data, but we have RGB from viewport
        # Convert RGB to numpy array and prepare for model
        try:
            # Convert PIL image to numpy array
            img_array = np.array(image).astype(np.float32) / 255.0
            
            # Prithvi expects input shape: (batch, channels, height, width)
            # For RGB viewport, we'll use it as-is (Prithvi can handle RGB)
            # In production, you'd want to use actual multi-spectral data
            
            # Resize to model's expected input size if needed
            # Prithvi typically expects 224x224 or similar
            target_size = 224
            if img_array.shape[0] != target_size or img_array.shape[1] != target_size:
                from PIL import Image as PILImage
                resized_image = image.resize((target_size, target_size), Image.Resampling.LANCZOS)
                img_array = np.array(resized_image).astype(np.float32) / 255.0
            
            # Convert to tensor: (H, W, C) -> (C, H, W) -> (1, C, H, W)
            img_tensor = torch.from_numpy(img_array).permute(2, 0, 1).unsqueeze(0)
            
            if cuda_available:
                img_tensor = img_tensor.cuda()
            
            # Extract features
            print("   🔍 Extracting features...")
            with torch.no_grad():
                if terratorch_available:
                    # TerraTorch models typically have a forward method that returns features
                    outputs = model(img_tensor)
                    # Extract feature vector (adjust based on actual model output)
                    if isinstance(outputs, dict):
                        feature_vector = outputs.get('features', outputs.get('last_hidden_state'))
                    elif isinstance(outputs, tuple):
                        feature_vector = outputs[0]
                    else:
                        feature_vector = outputs
                else:
                    # HuggingFace transformers
                    outputs = model(img_tensor)
                    feature_vector = outputs.last_hidden_state if hasattr(outputs, 'last_hidden_state') else outputs[0]
            
            # Convert to numpy and get a summary statistic
            if feature_vector is not None:
                feature_np = feature_vector.cpu().numpy()
                feature_summary = {
                    'shape': list(feature_np.shape),
                    'mean': float(np.mean(feature_np)),
                    'std': float(np.std(feature_np)),
                    'min': float(np.min(feature_np)),
                    'max': float(np.max(feature_np))
                }
                
                # Save feature vector
                feature_path = session_dir / 'features.npy'
                np.save(feature_path, feature_np)
                
                print(f"   ✅ Feature extraction complete: shape {feature_np.shape}")
            else:
                feature_summary = {'error': 'Could not extract features'}
            
        except Exception as e:
            import traceback
            return JsonResponse({
                'status': 'error',
                'message': f'Failed to process image with Prithvi: {str(e)}',
                'traceback': traceback.format_exc(),
                'device_info': device_info,
                'model_info': model_info
            }, status=500)
        
        # Return success response
        return JsonResponse({
            'status': 'success',
            'message': 'Prithvi feature extraction completed',
            'model_info': model_info,
            'device_info': device_info,
            'feature_summary': feature_summary,
            'session_dir': str(session_dir),
            'query_image_path': str(query_image_path),
            'geojson': {
                'type': 'FeatureCollection',
                'features': [{
                    'type': 'Feature',
                    'geometry': {
                        'type': 'Point',
                        'coordinates': [location.get('lon', 0), location.get('lat', 0)]
                    },
                    'properties': {
                        'analysis_type': 'prithvi',
                        'feature_shape': feature_summary.get('shape', []),
                        'timestamp': timestamp
                    }
                }]
            }
        })
        
    except Exception as e:
        import traceback
        return JsonResponse({
            'status': 'error',
            'message': f'Prithvi analysis failed: {str(e)}',
            'traceback': traceback.format_exc()
        }, status=500)
