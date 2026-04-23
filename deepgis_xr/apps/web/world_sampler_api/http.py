"""
HTTP handlers for the world-sampler API.

Moved out of the legacy module in the Tier C refactor. These nine
endpoints form the public surface of the DeepGIS world-sampler (routes
wired in `deepgis_xr/apps/web/urls.py`):

    POST  /webclient/sampler/initialize        initialize_sampler
    POST  /webclient/sampler/sample            sample_locations
    POST  /webclient/sampler/update            update_distribution
    GET   /webclient/sampler/query             query_region
    GET   /webclient/sampler/statistics        get_statistics
    POST  /webclient/sampler/reset             reset_sampler
    GET   /webclient/sampler/history           get_sample_history
    GET   /webclient/sampler/scored            get_scored_locations
    POST  /webclient/sampler/analyze-viewport  analyze_viewport

`analyze_viewport` dispatches per `model_type` to the seven internal
`_analyze_viewport_<model>` branches, imported from the `analyzers/`
subpackage below. The dispatch is still an explicit if/elif chain
inside the handler; it will move to `ANALYZER_REGISTRY.dispatch(
model_type, ...)` when the Analyzer ABC lands in a follow-up commit
(that change is what unblocks the kernelcal ModelKernelSelector
thread).
"""

from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
import json
import math

from ..world_sampler import SamplePoint, WorldSampler
from ..models import DistributionUpdate, SampledLocation, SamplingSession
from .core import (
    altitude_to_zoom_level,
    get_or_create_sampler,
    reset_global_sampler,
)
from .analyzers import (
    _analyze_viewport_sam,
    _analyze_viewport_zero_shot,
    _analyze_viewport_mask2former,
    _analyze_viewport_yolov8,
    _analyze_viewport_grounding_dino,
    _analyze_viewport_grounded_sam,
    _analyze_viewport_prithvi,
    _analyze_viewport_urban_spectral,
)


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
        
        sampler = reset_global_sampler(WorldSampler(
            num_points=data.get('num_points', 1000),
            lat_range=tuple(data.get('lat_range', [-90, 90])),
            lon_range=tuple(data.get('lon_range', [-180, 180])),
            alt_range=tuple(data.get('alt_range', [0, 5000])),
            initialization=data.get('initialization', 'uniform'),
            seed=data.get('seed')
        ))
        
        stats = sampler.get_statistics()
        
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

        # Bbox-only analyzers short-circuit before the "image required" check
        # because they consume a geographic viewport rather than a rendered
        # tile. Currently just urban_spectral; add future bbox-only branches
        # here as they land.
        if analysis_type == 'urban_spectral':
            return _analyze_viewport_urban_spectral(data)

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
