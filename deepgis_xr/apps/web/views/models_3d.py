"""
3D (STL) model serving endpoints.

Moved out of the legacy `views.py` monolith in the Tier B refactor.
These two handlers back the STL viewer and the labeler's "pick a
model" dropdown.

Public handlers:
    get_3d_model      GET  /webclient/get3DModel
                      (returns the raw STL via FileResponse,
                       looked up by ?model_id= or defaults to the first
                       file under MEDIA_ROOT/stl_models/)
    list_stl_models   GET  /webclient/getSTLModels
                      (JSON listing of STL files under
                       STATIC_ROOT/models/stl/, falling back through
                       STATICFILES_DIRS and BASE_DIR/static/…)

The filesystem conventions encoded here (`MEDIA_ROOT/stl_models`,
`STATIC_ROOT/models/stl`) are the same the existing templates and
frontend bundles expect.
"""

import os

from django.conf import settings
from django.http import FileResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt


@csrf_exempt
def get_3d_model(request):
    """
    Endpoint to retrieve STL models for 3D labeling
    """
    try:
        # Get model_id from request if provided
        model_id = request.GET.get('model_id')
        
        # For now, we'll serve a sample/default STL file
        # In a real implementation, you'd look up the model by ID
        
        # Path to the STL files directory - adjust this to your actual directory
        stl_dir = os.path.join(settings.MEDIA_ROOT, 'stl_models')
        
        # If model_id is provided, get that specific file, otherwise use a default
        if model_id:
            stl_path = os.path.join(stl_dir, f"{model_id}.stl")
            # Check if the file exists
            if not os.path.exists(stl_path):
                return JsonResponse({
                    'success': False,
                    'message': f'Model with ID {model_id} not found'
                }, status=404)
        else:
            # If no specific model requested, get the first STL file in the directory
            if not os.path.exists(stl_dir):
                os.makedirs(stl_dir, exist_ok=True)
                return JsonResponse({
                    'success': False,
                    'message': 'No STL models available'
                }, status=404)
                
            stl_files = [f for f in os.listdir(stl_dir) if f.endswith('.stl')]
            if not stl_files:
                return JsonResponse({
                    'success': False,
                    'message': 'No STL models available'
                }, status=404)
                
            stl_path = os.path.join(stl_dir, stl_files[0])
        
        # Return the STL file
        return FileResponse(open(stl_path, 'rb'), content_type='application/octet-stream')
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'Error retrieving 3D model: {str(e)}'
        }, status=500)

@csrf_exempt
def list_stl_models(request):
    """Get a list of available STL models from the static/models/stl directory"""
    try:
        # Path to the STL models directory
        stl_dir = os.path.join(settings.STATIC_ROOT, 'models', 'stl')
        
        # If STATIC_ROOT is not set or the directory doesn't exist, try with STATICFILES_DIRS
        if not os.path.exists(stl_dir):
            for static_dir in settings.STATICFILES_DIRS:
                test_path = os.path.join(static_dir, 'models', 'stl')
                if os.path.exists(test_path):
                    stl_dir = test_path
                    break
        
        # Fallback to local static directory
        if not os.path.exists(stl_dir):
            stl_dir = os.path.join(settings.BASE_DIR, 'static', 'models', 'stl')
        
        # Check if directory exists
        if not os.path.exists(stl_dir):
            return JsonResponse({
                'success': False,
                'message': f'STL directory not found at {stl_dir}',
                'models': []
            })
        
        # List all STL files in the directory
        stl_files = []
        for file in os.listdir(stl_dir):
            if file.lower().endswith('.stl'):
                # Remove the .stl extension for display
                model_name = os.path.splitext(file)[0]
                stl_files.append({
                    'id': model_name,
                    'name': model_name.replace('_', ' ').title(),  # Format for display
                    'file': file
                })
        
        return JsonResponse({
            'success': True,
            'message': f'Found {len(stl_files)} STL models',
            'models': stl_files
        })
    
    except Exception as e:
        import traceback
        print(f"Error listing STL models: {str(e)}")
        print(traceback.format_exc())
        return JsonResponse({
            'success': False,
            'message': f'Error listing STL models: {str(e)}',
            'models': []
        }, status=500)
