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

