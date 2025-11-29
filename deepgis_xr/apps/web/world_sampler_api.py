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
