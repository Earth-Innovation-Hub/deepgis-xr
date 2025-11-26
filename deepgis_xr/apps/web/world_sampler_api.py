"""
World Sampler API Views

Django views for integrating the world sampler with the DeepGIS Search frontend.
"""

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
import json
from typing import Optional

from .world_sampler import WorldSampler, SamplePoint


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
        "method": "weighted" | "top_k"
    }
    
    Returns: {
        "status": "success",
        "samples": [
            {
                "lat": 28.0,
                "lon": 86.9,
                "alt": 5000.0,
                "weight": 0.001
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
        
        samples = sampler.sample(n=n, method=method)
        
        # Convert to dict
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
                        "metadata": s['metadata']
                    }
                }
                for s in samples_data
            ]
        }
        
        return JsonResponse({
            'status': 'success',
            'samples': samples_data,
            'geojson': geojson,
            'statistics': sampler.get_statistics()
        })
        
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': str(e)
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
            {"lat": 28.0, "lon": 86.9, "alt": 5000, "reward": 1.0},
            ...
        ],
        "params": {
            "learning_rate": 0.1,
            "radius": 100000,
            ...
        }
    }
    """
    try:
        data = json.loads(request.body)
        sampler = get_or_create_sampler()
        
        rule = data.get('rule', 'reward')
        feedback_points = data.get('feedback_points', [])
        params = data.get('params', {})
        
        # Convert feedback points to tuples
        feedback_tuples = [
            (fp['lat'], fp['lon'], fp['alt'], fp.get('reward', 1.0))
            for fp in feedback_points
        ]
        
        # Apply update
        sampler.update_weights(
            rule=rule,
            feedback_points=feedback_tuples if feedback_tuples else None,
            **params
        )
        
        stats = sampler.get_statistics()
        
        return JsonResponse({
            'status': 'success',
            'message': f'Distribution updated using {rule} rule',
            'statistics': stats,
            'num_updates': len(sampler.update_history)
        })
        
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': str(e)
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
    
    GET /webclient/sampler/history?limit=100
    """
    try:
        sampler = get_or_create_sampler()
        limit = int(request.GET.get('limit', 100))
        
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

