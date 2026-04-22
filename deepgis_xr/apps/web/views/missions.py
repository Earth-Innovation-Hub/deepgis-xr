"""
Mission planning API endpoints.

Moved out of the legacy `views.py` monolith in the Tier B refactor.
Routes (`label/api/missions/…`) live in `deepgis_xr/apps/web/urls.py`
and are rebound through `views/__init__.py`, so the module path in
`urls.py` is unchanged (`views.list_missions`, `views.create_mission`, …).
"""

import json

from django.db import models
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from deepgis_xr.apps.core.models import Mission, MissionWaypoint, Vehicle


@csrf_exempt
def list_missions(request):
    """List all missions for the current user"""
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Authentication required', 'authenticated': False}, status=401)
    
    if request.method != 'GET':
        return JsonResponse({'error': 'GET required'}, status=405)
    
    try:
        missions = Mission.objects.filter(created_by=request.user)
        return JsonResponse({
            'status': 'success',
            'missions': [
                {
                    'id': m.id,
                    'name': m.name,
                    'description': m.description,
                    'mission_type': m.mission_type,
                    'status': m.status,
                    'vehicle_id': m.vehicle.id if m.vehicle else None,
                    'vehicle_name': m.vehicle.name if m.vehicle else None,
                    'num_waypoints': m.num_waypoints,
                    'default_altitude': m.default_altitude,
                    'default_speed': m.default_speed,
                    'return_to_home': m.return_to_home,
                    'created_at': m.created_at.isoformat(),
                    'updated_at': m.updated_at.isoformat(),
                }
                for m in missions
            ]
        })
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
def create_mission(request):
    """Create a new mission"""
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Authentication required', 'authenticated': False}, status=401)
    
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)
    
    try:
        data = json.loads(request.body)
        
        # Get vehicle if provided
        vehicle = None
        if data.get('vehicle_id'):
            try:
                vehicle = Vehicle.objects.get(id=data['vehicle_id'], owner=request.user)
            except Vehicle.DoesNotExist:
                return JsonResponse({'error': 'Vehicle not found'}, status=404)
        
        # Create mission
        mission = Mission.objects.create(
            name=data.get('name', 'Untitled Mission'),
            description=data.get('description', ''),
            mission_type=data.get('mission_type', 'CUSTOM'),
            vehicle=vehicle,
            default_altitude=data.get('default_altitude', 50.0),
            default_speed=data.get('default_speed'),
            return_to_home=data.get('return_to_home', True),
            waypoints={'type': 'FeatureCollection', 'features': []},
            created_by=request.user
        )
        
        return JsonResponse({
            'status': 'success',
            'mission': {
                'id': mission.id,
                'name': mission.name,
                'description': mission.description,
                'mission_type': mission.mission_type,
                'status': mission.status,
                'vehicle_id': mission.vehicle.id if mission.vehicle else None,
                'vehicle_name': mission.vehicle.name if mission.vehicle else None,
                'num_waypoints': mission.num_waypoints,
                'default_altitude': mission.default_altitude,
                'default_speed': mission.default_speed,
                'return_to_home': mission.return_to_home,
                'created_at': mission.created_at.isoformat(),
                'updated_at': mission.updated_at.isoformat(),
            }
        }, status=201)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
def get_mission(request, mission_id):
    """Get mission details including waypoints"""
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Authentication required', 'authenticated': False}, status=401)
    
    if request.method != 'GET':
        return JsonResponse({'error': 'GET required'}, status=405)
    
    try:
        mission = Mission.objects.get(id=mission_id, created_by=request.user)
        
        # Get waypoints
        waypoints = mission.waypoint_items.all().order_by('sequence')
        waypoint_list = [wp.to_geojson() for wp in waypoints]
        
        return JsonResponse({
            'status': 'success',
            'mission': {
                'id': mission.id,
                'name': mission.name,
                'description': mission.description,
                'mission_type': mission.mission_type,
                'status': mission.status,
                'vehicle_id': mission.vehicle.id if mission.vehicle else None,
                'vehicle_name': mission.vehicle.name if mission.vehicle else None,
                'num_waypoints': mission.num_waypoints,
                'default_altitude': mission.default_altitude,
                'default_speed': mission.default_speed,
                'return_to_home': mission.return_to_home,
                'waypoints': {
                    'type': 'FeatureCollection',
                    'features': waypoint_list
                },
                'created_at': mission.created_at.isoformat(),
                'updated_at': mission.updated_at.isoformat(),
            }
        })
    except Mission.DoesNotExist:
        return JsonResponse({'error': 'Mission not found'}, status=404)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
def update_mission(request, mission_id):
    """Update mission details"""
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Authentication required', 'authenticated': False}, status=401)
    
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)
    
    try:
        mission = Mission.objects.get(id=mission_id, created_by=request.user)
        data = json.loads(request.body)
        
        # Update fields
        if 'name' in data:
            mission.name = data['name']
        if 'description' in data:
            mission.description = data['description']
        if 'mission_type' in data:
            mission.mission_type = data['mission_type']
        if 'status' in data:
            mission.status = data['status']
        if 'default_altitude' in data:
            mission.default_altitude = data['default_altitude']
        if 'default_speed' in data:
            mission.default_speed = data['default_speed']
        if 'return_to_home' in data:
            mission.return_to_home = data['return_to_home']
        if 'vehicle_id' in data:
            if data['vehicle_id']:
                try:
                    mission.vehicle = Vehicle.objects.get(id=data['vehicle_id'], owner=request.user)
                except Vehicle.DoesNotExist:
                    return JsonResponse({'error': 'Vehicle not found'}, status=404)
            else:
                mission.vehicle = None
        
        mission.save()
        
        return JsonResponse({
            'status': 'success',
            'mission': {
                'id': mission.id,
                'name': mission.name,
                'status': mission.status,
            }
        })
    except Mission.DoesNotExist:
        return JsonResponse({'error': 'Mission not found'}, status=404)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
def delete_mission(request, mission_id):
    """Delete a mission"""
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Authentication required', 'authenticated': False}, status=401)
    
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)
    
    try:
        mission = Mission.objects.get(id=mission_id, created_by=request.user)
        mission.delete()
        return JsonResponse({'status': 'success', 'message': 'Mission deleted'})
    except Mission.DoesNotExist:
        return JsonResponse({'error': 'Mission not found'}, status=404)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
def add_waypoint(request, mission_id):
    """Add a waypoint to a mission"""
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Authentication required', 'authenticated': False}, status=401)
    
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)
    
    try:
        mission = Mission.objects.get(id=mission_id, created_by=request.user)
        data = json.loads(request.body)
        
        # Get next sequence number
        max_sequence = mission.waypoint_items.aggregate(
            max_seq=models.Max('sequence')
        )['max_seq'] or 0
        sequence = max_sequence + 1
        
        # Create waypoint
        waypoint = MissionWaypoint.objects.create(
            mission=mission,
            sequence=sequence,
            latitude=data['latitude'],
            longitude=data['longitude'],
            altitude=data.get('altitude', mission.default_altitude),
            waypoint_type=data.get('waypoint_type', 'WAYPOINT'),
            command=data.get('command', 16),  # MAV_CMD_NAV_WAYPOINT
            param1=data.get('param1', 0.0),
            param2=data.get('param2', 0.0),
            param3=data.get('param3', 0.0),
            param4=data.get('param4', 0.0),
            speed=data.get('speed', mission.default_speed),
            yaw=data.get('yaw'),
        )
        
        return JsonResponse({
            'status': 'success',
            'waypoint': waypoint.to_geojson()
        }, status=201)
    except Mission.DoesNotExist:
        return JsonResponse({'error': 'Mission not found'}, status=404)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
def remove_waypoint(request, mission_id, waypoint_id):
    """Remove a waypoint from a mission"""
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Authentication required', 'authenticated': False}, status=401)
    
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)
    
    try:
        mission = Mission.objects.get(id=mission_id, created_by=request.user)
        waypoint = MissionWaypoint.objects.get(id=waypoint_id, mission=mission)
        
        # Get sequence of deleted waypoint
        deleted_sequence = waypoint.sequence
        
        # Delete waypoint
        waypoint.delete()
        
        # Renumber remaining waypoints
        waypoints_to_renumber = mission.waypoint_items.filter(sequence__gt=deleted_sequence)
        for wp in waypoints_to_renumber:
            wp.sequence -= 1
            wp.save()
        
        return JsonResponse({'status': 'success', 'message': 'Waypoint removed'})
    except Mission.DoesNotExist:
        return JsonResponse({'error': 'Mission not found'}, status=404)
    except MissionWaypoint.DoesNotExist:
        return JsonResponse({'error': 'Waypoint not found'}, status=404)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)
