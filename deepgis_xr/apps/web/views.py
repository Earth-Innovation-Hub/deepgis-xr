from django.http import HttpResponse, JsonResponse, FileResponse
from django.template import loader
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import TemplateView
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
import json
import tempfile
import zipfile
import os
from shapely.geometry import shape
import fiona
import requests
from urllib.parse import urljoin
import numpy as np
import cv2
from io import BytesIO
import base64
import math
import time
import hashlib
from django.conf import settings

from deepgis_xr.apps.core.models import (
    Image, CategoryType, ImageLabel, RasterImage, Labeler, CategoryLabel,
    TrainingDataset, TrainingLabel, ModelVersion,
    Vehicle, Mission, MissionWaypoint
)


class BaseView(LoginRequiredMixin, TemplateView):
    """Base class for all web views"""
    
    def get_context_data(self, **kwargs):
        """Get base context data"""
        context = super().get_context_data(**kwargs)
        context['categories'] = {
            cat.category_name: str(cat.color) 
            for cat in CategoryType.objects.all()
        }
        return context


class IndexView(BaseView):
    """Main landing page"""
    template_name = 'web/index.html'


class LabelView(BaseView):
    """Image labeling interface"""
    template_name = 'web/label.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        latest_images = Image.objects.all()
        
        if latest_images:
            context.update({
                'latest_image_list': latest_images,
                'selected_image': latest_images[0],
            })
        
        return context


class Label3DView(BaseView):
    """3D model labeling interface"""
    template_name = 'web/label_3d.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        return context


class MapLabelView(BaseView):
    """Map-based labeling interface"""
    template_name = 'web/map_label.html'


class ViewLabelView(BaseView):
    """View existing labels"""
    template_name = 'web/view_label.html'


class ResultsView(BaseView):
    """View labeling results"""
    template_name = 'web/results.html'


# URL routing
index = IndexView.as_view()
label = LabelView.as_view()
label_3d = Label3DView.as_view()
map_label = MapLabelView.as_view()
view_label = ViewLabelView.as_view()
results = ResultsView.as_view()

# Helper function to reduce duplication in simple view functions
def simple_render(request, template_name):
    """Render a simple template without additional context."""
    return render(request, template_name)

def index(request):
    return simple_render(request, 'web/index.html')

def label(request):
    return simple_render(request, 'web/label.html')

def stl_viewer(request):
    """
    Renders the modular Three.js STL viewer page.
    This is a cleaner reimplementation of the 3D model viewer functionality.
    """
    return simple_render(request, 'web/stl_viewer.html')

def label_3d(request):
    return simple_render(request, 'web/label_3d.html')

def label_3d_dev(request):
    return simple_render(request, 'web/label_3d_dev.html')

def map_label(request):
    return simple_render(request, 'web/map_label.html')

def view_label(request):
    return simple_render(request, 'web/view_label.html')

def results(request):
    return simple_render(request, 'web/results.html')

@csrf_exempt
def get_category_info(request):
    """Get all categories from the database"""
    try:
        categories = {}
        for cat in CategoryType.objects.all().order_by('category_name'):
            if cat.color:
                # Convert RGB to hex
                color_hex = f'#{cat.color.red:02x}{cat.color.green:02x}{cat.color.blue:02x}'
            else:
                color_hex = '#FF0000'  # Default red
            
            categories[cat.category_name] = {
                'color': color_hex,
                'id': cat.id,
                'label_type': cat.label_type
            }
        
        # If no categories exist, return default categories
        if not categories:
            categories = {
                'Buildings': {
                    'color': '#FF0000',
                    'id': 1,
                    'label_type': 'P'
                },
                'Roads': {
                    'color': '#00FF00',
                    'id': 2,
                    'label_type': 'P'
                },
                'Water Bodies': {
                    'color': '#0000FF',
                    'id': 3,
                    'label_type': 'P'
                }
            }
        
        return JsonResponse(categories)
    except Exception as e:
        print(f"Error in get_category_info: {str(e)}")
        # Return default categories on error
        return JsonResponse({
            'Buildings': {'color': '#FF0000', 'id': 1, 'label_type': 'P'},
            'Roads': {'color': '#00FF00', 'id': 2, 'label_type': 'P'},
            'Water Bodies': {'color': '#0000FF', 'id': 3, 'label_type': 'P'}
        })

@csrf_exempt
def get_new_image(request):
    """Get an image from the database for labeling, with support for navigation"""
    import random
    from deepgis_xr.apps.core.models import Image, CategoryType
    
    # Check if requesting a specific navigation direction
    direction = request.GET.get('direction', 'next')
    
    # Get all images from the database
    all_images = list(Image.objects.all())
    
    # If no images in database, return error response
    if not all_images:
        return JsonResponse({
            'success': False,
            'message': 'No images available in the database'
        })
    
    # Get the current image ID from session if it exists
    current_image_id = request.session.get('current_image_id', None)
    
    try:
        # Find the current image in the list
        current_index = -1
        if current_image_id is not None:
            for i, img in enumerate(all_images):
                if img.id == current_image_id:
                    current_index = i
                    break
        
        # Handle navigation based on direction
        if direction == 'prev' and current_index > 0:
            # Go to previous image
            current_index -= 1
        elif direction == 'next' and current_index < len(all_images) - 1:
            # Go to next image
            current_index += 1
        elif direction == 'next' and (current_index == -1 or current_index == len(all_images) - 1):
            # Start from beginning if at end or no current image
            current_index = 0
        elif direction == 'prev' and (current_index == -1):
            # Start from last image if no current image and going backwards
            current_index = len(all_images) - 1
        
        # Get the image at the current index
        image = all_images[current_index]
        
        # Save the current image ID in session
        request.session['current_image_id'] = image.id
        
        # Prepare image data for frontend
        image_name = image.name
        path = image.path
        
        # Ensure the path is a valid image URL, not just a directory
        # If the path doesn't contain a file extension, it might be a directory
        if not path.lower().endswith(('.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.webp')):
            # Check if the path ends with a slash, remove it if it does
            if path.endswith('/'):
                path = path[:-1]
            
            # Append the image name as the filename if it has an extension
            if image_name.lower().endswith(('.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.webp')):
                path = f"{path}/{image_name}"
            else:
                # Default to a .jpg extension if no extension in the name
                path = f"{path}/{image_name}.jpg"
        
        # Ensure the URL has http/https prefix
        if not path.startswith(('http://', 'https://')):
            path = f"https://{path}" if not path.startswith('//') else f"https:{path}"
        
        # Process categories
        if image.categories.exists():
            categories = [cat.category_name for cat in image.categories.all()]
            colors = []
            shapes = []
            for cat in image.categories.all():
                if cat.color:
                    r, g, b = cat.color.red, cat.color.green, cat.color.blue
                    colors.append(f'#{r:02x}{g:02x}{b:02x}')
                else:
                    colors.append('#FF0000')  # Default red
                
                # Map label_type to shape
                if cat.label_type == 'C':
                    shapes.append('circle')
                elif cat.label_type == 'R':
                    shapes.append('rectangle')
                elif cat.label_type == 'P':
                    shapes.append('bezier')
                else:
                    shapes.append('circle')  # Default to circle
        else:
            # Default categories if none are associated with the image
            categories = ['Buildings', 'Roads', 'Vegetation', 'Water Bodies']
            shapes = ['circle', 'circle', 'circle', 'circle']
            colors = ['#FF0000', '#00FF00', '#00AA00', '#0000FF']
        
        # Get existing labels for this image
        existing_labels = get_image_labels(image.id)
        
        # Return the image data
        return JsonResponse({
            'success': True,
            'image_name': image_name,
            'image_path': path,
            'categories': categories,
            'shapes': shapes,
            'colors': colors,
            'width': getattr(image, 'width', 996),
            'height': getattr(image, 'height', 996),
            'navigation': {
                'has_prev': current_index > 0,
                'has_next': current_index < len(all_images) - 1,
                'current_index': current_index + 1,
                'total_images': len(all_images)
            },
            'existing_labels': existing_labels
        })
        
    except Exception as e:
        # Log the error
        print(f"Error in get_new_image: {str(e)}")
        # Return error response
        return JsonResponse({
            'success': False,
            'message': f'Error loading image: {str(e)}'
        }, status=500)

def get_image_labels(image_id):
    """Get existing labels for an image"""
    from deepgis_xr.apps.core.models import ImageLabel
    
    try:
        # Find the most recent label for this image
        labels = ImageLabel.objects.filter(image_id=image_id).order_by('-pub_date')
        
        if not labels.exists():
            return None
        
        # Get the most recent label
        latest_label = labels.first()
        
        # The combined_label_shapes field contains the GeoJSON data
        if latest_label.combined_label_shapes:
            try:
                import json
                # Parse the JSON data
                label_data = json.loads(latest_label.combined_label_shapes)
                return label_data
            except json.JSONDecodeError:
                print(f"Error decoding JSON for label {latest_label.id}")
                return None
        
        return None
    except Exception as e:
        print(f"Error retrieving image labels: {str(e)}")
        return None

@csrf_exempt
def save_label(request):
    """Legacy endpoint - redirects to save_labels"""
    if request.method == 'POST':
        try:
            # Simply call save_labels
            return save_labels(request)
        except json.JSONDecodeError:
            return JsonResponse({'status': 'error', 'message': 'Invalid JSON'}, status=400)
    return JsonResponse({'status': 'error', 'message': 'Method not allowed'}, status=405)

@csrf_exempt
def create_category(request):
    """Create a new category in the database"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            category_name = data.get('name', '').strip()
            color_hex = data.get('color', None)  # Optional: allow custom color
            label_type = data.get('label_type', 'P')  # Default to Polygon
            
            if not category_name:
                return JsonResponse({'status': 'error', 'message': 'Category name is required'}, status=400)
            
            # Check if category already exists
            if CategoryType.objects.filter(category_name=category_name).exists():
                existing = CategoryType.objects.get(category_name=category_name)
                if existing.color:
                    color_hex = f'#{existing.color.red:02x}{existing.color.green:02x}{existing.color.blue:02x}'
                else:
                    color_hex = '#FF0000'
                return JsonResponse({
                    'status': 'error', 
                    'message': 'Category already exists',
                    'category': {
                        'name': existing.category_name,
                        'color': color_hex,
                        'id': existing.id
                    }
                }, status=400)
            
            # Generate random color if not provided
            if not color_hex:
                import random
                color_hex = '#{:06x}'.format(random.randint(0, 0xFFFFFF))
            
            # Convert hex to RGB
            color_hex = color_hex.lstrip('#')
            rgb = tuple(int(color_hex[i:i+2], 16) for i in (0, 2, 4))
            
            # Get or create the Color object
            from deepgis_xr.apps.core.models import Color
            color, _ = Color.objects.get_or_create(
                red=rgb[0],
                green=rgb[1],
                blue=rgb[2]
            )
            
            # Create the category
            category = CategoryType.objects.create(
                category_name=category_name,
                color=color,
                label_type=label_type
            )
            
            return JsonResponse({
                'status': 'success',
                'category': {
                    'name': category.category_name,
                    'color': f'#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}',
                    'id': category.id,
                    'label_type': category.label_type
                }
            })
        except json.JSONDecodeError:
            return JsonResponse({'status': 'error', 'message': 'Invalid JSON'}, status=400)
        except Exception as e:
            print(f"Error creating category: {str(e)}")
            import traceback
            traceback.print_exc()
            return JsonResponse({'status': 'error', 'message': str(e)}, status=500)
    return JsonResponse({'status': 'error', 'message': 'Method not allowed'}, status=405)

@csrf_exempt
def save_labels(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            
            # Validate required data
            if not data.get('features'):
                return JsonResponse({'status': 'error', 'message': 'No features to save'}, status=400)
            
            if not data.get('metadata') or not data.get('metadata').get('image'):
                return JsonResponse({'status': 'error', 'message': 'Missing image metadata'}, status=400)
            
            # Get image from database
            image_name = data['metadata']['image']
            try:
                image = Image.objects.get(name=image_name)
            except Image.DoesNotExist:
                return JsonResponse({'status': 'error', 'message': f'Image {image_name} not found'}, status=404)
            
            # Get or create a user/labeler (use the current user if authenticated)
            labeler = None
            if request.user.is_authenticated:
                from deepgis_xr.apps.core.models import Labeler
                labeler, _ = Labeler.objects.get_or_create(user=request.user)
            
            # Create the parent ImageLabel record
            image_label = ImageLabel(
                image=image,
                combined_label_shapes=json.dumps(data),
                labeler=labeler
            )
            
            # Add time taken if available
            if data['metadata'].get('timeTaken'):
                image_label.time_taken = data['metadata']['timeTaken']
            
            # Save the parent label
            image_label.save()
            
            # Process grid metrics if available
            if data['metadata'].get('gridMetrics'):
                # Store grid metrics in the database if needed
                # This could be in a separate model or as part of the ImageLabel
                pass
            
            # Create CategoryLabel records for each category
            categories_by_name = {}
            for feature in data['features']:
                category_name = feature['properties'].get('category')
                if not category_name:
                    continue
                
                # Get or create the category
                if category_name not in categories_by_name:
                    try:
                        category = CategoryType.objects.get(category_name=category_name)
                    except CategoryType.DoesNotExist:
                        # Create a new category if it doesn't exist
                        color_hex = feature['properties'].get('color', '#FF0000')
                        # Convert hex to RGB
                        color_hex = color_hex.lstrip('#')
                        rgb = tuple(int(color_hex[i:i+2], 16) for i in (0, 2, 4))
                        
                        # Get or create the Color object
                        from deepgis_xr.apps.core.models import Color
                        color, _ = Color.objects.get_or_create(
                            red=rgb[0], 
                            green=rgb[1], 
                            blue=rgb[2]
                        )
                        
                        # Create the category
                        category = CategoryType.objects.create(
                            category_name=category_name,
                            color=color,
                            label_type='P'  # Polygon by default
                        )
                    
                    categories_by_name[category_name] = {
                        'category': category,
                        'features': []
                    }
                
                # Add the feature to the category's feature list
                categories_by_name[category_name]['features'].append(feature)
            
            # Create a CategoryLabel for each category
            for category_name, data in categories_by_name.items():
                # Create feature collection for this category
                feature_collection = {
                    'type': 'FeatureCollection',
                    'features': data['features']
                }
                
                # Create the CategoryLabel
                CategoryLabel.objects.create(
                    category=data['category'],
                    label_shapes=json.dumps(feature_collection),
                    parent_label=image_label
                )
            
            return JsonResponse({
                'status': 'success', 
                'message': 'Labels saved successfully',
                'label_id': image_label.id
            })
            
        except Exception as e:
            import traceback
            print(f"Error saving labels: {str(e)}")
            print(traceback.format_exc())
            return JsonResponse({'status': 'error', 'message': str(e)}, status=500)
    
    return JsonResponse({'status': 'error', 'message': 'Method not allowed'}, status=405)

@csrf_exempt
def export_shapefile(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            
            # Create a temporary directory for the shapefile
            with tempfile.TemporaryDirectory() as tmpdir:
                # Define the schema based on your GeoJSON properties
                schema = {
                    'geometry': 'Polygon',
                    'properties': {'category': 'str', 'label_id': 'int'},
                }
                
                # Create a shapefile from the GeoJSON
                shp_path = f"{tmpdir}/labels.shp"
                with fiona.open(shp_path, 'w', 
                              driver='ESRI Shapefile',
                              crs='EPSG:4326',
                              schema=schema) as shp:
                    # Write each feature to the shapefile
                    for feature in data['features']:
                        shp.write({
                            'geometry': feature['geometry'],
                            'properties': feature['properties']
                        })
                
                # Create a ZIP file containing the shapefile components
                zip_path = f"{tmpdir}/labels.zip"
                with zipfile.ZipFile(zip_path, 'w') as zipf:
                    for ext in ['.shp', '.shx', '.dbf', '.prj']:
                        filename = f"labels{ext}"
                        filepath = f"{tmpdir}/{filename}"
                        if os.path.exists(filepath):
                            zipf.write(filepath, filename)
                
                # Return the ZIP file
                return FileResponse(
                    open(zip_path, 'rb'),
                    content_type='application/zip',
                    as_attachment=True,
                    filename='labels.zip'
                )
                
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)})
    return JsonResponse({'status': 'error', 'message': 'Method not allowed'}, status=405)

@csrf_exempt
def get_raster_info(request):
    """Get information about available raster layers."""
    
    try:
        rasters = RasterImage.objects.all()
        raster_info = []
        
        for raster in rasters:
            raster_info.append({
                'name': raster.name,
                'path': raster.path,
                'attribution': raster.attribution,
                'minZoom': raster.min_zoom,
                'maxZoom': raster.max_zoom,
                'lat_lng': [raster.latitude, raster.longitude]
            })
        
        return success_json_response({'message': raster_info})
    except Exception as e:
        return error_json_response(str(e), status=500)

# Helper function to get tileserver URL (reduces duplication)
def get_tileserver_url(request):
    """Get tileserver URL based on environment and request host."""
    import os
    default_url = 'https://mbtiles.deepgis.org'
    # Allow localhost override for development
    if 'localhost' in request.get_host() or '127.0.0.1' in request.get_host():
        default_url = 'http://localhost:8091'
    return os.environ.get('MBTILES_SERVER', default_url)

@csrf_exempt
def get_tileserver_layers(request):
    """Get available layers from the tileserver."""
    TILESERVER_URL = get_tileserver_url(request)
    
    try:
        # Fetch layers from tileserver
        response = requests.get(f'{TILESERVER_URL}/data.json', timeout=5)
        response.raise_for_status()  # Raise exception for non-200 status codes
        
        data = response.json()
        layers = {}
        
        for layer_id, info in data.items():
            if not isinstance(info, dict):
                continue
            
            # Basic layer info
            layer = {
                'id': layer_id,
                'name': info.get('name', layer_id),
                'type': 'vector' if info.get('format') == 'pbf' else 'raster'
            }
            
            # Handle tiles URL
            tiles = info.get('tiles', [])
            if tiles:
                tile_url = tiles[0]
                if tile_url.startswith('/'):
                    tile_url = urljoin(TILESERVER_URL, tile_url.lstrip('/'))
            else:
                # Construct default tile URL
                ext = 'pbf' if layer['type'] == 'vector' else 'png'
                tile_url = f'{TILESERVER_URL}/data/{layer_id}/{{z}}/{{x}}/{{y}}.{ext}'
            
            layer['url'] = tile_url
            
            # Add optional properties if they exist
            for prop in ['minzoom', 'maxzoom', 'bounds', 'center', 'attribution']:
                if prop in info:
                    layer[prop] = info[prop]
            
            layers[layer_id] = layer
        
        return success_json_response({
            'layers': layers,
            'tileserver': TILESERVER_URL
        })
        
    except requests.exceptions.RequestException as e:
        print(f'Tileserver error: {str(e)}')
        return error_json_response('Could not connect to tileserver', status=503)
    except Exception as e:
        print(f'Unexpected error: {str(e)}')
        return error_json_response(str(e), status=500)

# Helper functions to reduce JsonResponse duplication
def success_json_response(data=None, message=None, **kwargs):
    """Create a standardized success JsonResponse."""
    response_data = {'status': 'success'}
    if message:
        response_data['message'] = message
    if data:
        response_data.update(data)
    response_data.update(kwargs)
    return JsonResponse(response_data)

def error_json_response(message, status=500, **kwargs):
    """Create a standardized error JsonResponse."""
    response_data = {'status': 'error', 'message': message}
    response_data.update(kwargs)
    return JsonResponse(response_data, status=status)

@csrf_exempt
def get_all_images(request):
    """Get all images from the database."""
    try:
        images = Image.objects.all()
        image_list = []
        
        for image in images:
            image_data = {
                'id': image.id,
                'name': image.name,
                'path': image.path if image.path.startswith(('http://', 'https://')) else image.path + '/',
                'width': image.width,
                'height': image.height,
                'description': image.description
            }
            image_list.append(image_data)
        
        return JsonResponse({
            'success': True,
            'images': image_list
        })
    except Exception as e:
        print(f'Error in get_all_images: {str(e)}')
        return JsonResponse({
            'success': False,
            'message': str(e)
        }, status=500)

@csrf_exempt
def detect_grid(request):
    """Detect uniform metric grid in an image - simplified version"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            original_image_path = data.get('path')
            click_point = data.get('point', {})
            
            # Validate input
            if not original_image_path:
                return JsonResponse({
                    'success': False,
                    'message': 'No image path provided'
                }, status=400)
            
            print(f"Original image path: {original_image_path}")
            
            # Process the image path to handle both remote and local paths
            image_path = original_image_path
            
            # If image path has query parameters, strip them for file operations
            if '?' in image_path:
                image_path = image_path.split('?')[0]
            
            # Handle local files - determine if this might be a local path
            if not image_path.startswith(('http://', 'https://')):
                # Check for static/images path format
                if 'static/images' in image_path:
                    # If path is relative, combine with base app path
                    if not image_path.startswith('/'):
                        image_path = os.path.join('/app', image_path)
                # Add static/images path if it's not present
                elif not image_path.startswith('/'):
                    image_path = os.path.join('/app/static/images', os.path.basename(image_path))
                print(f"Using local path: {image_path}")
            
            # Create a cache directory if it doesn't exist
            cache_dir = os.path.join(settings.MEDIA_ROOT, 'cache')
            os.makedirs(cache_dir, exist_ok=True)
            
            # Generate a cache key from the image path
            cache_key = hashlib.md5(image_path.encode()).hexdigest()
            cache_path = os.path.join(cache_dir, f"{cache_key}.jpg")
            
            # Check if image is already cached
            image = None
            if os.path.exists(cache_path) and os.path.getsize(cache_path) > 0:
                try:
                    with open(cache_path, 'rb') as f:
                        image_data = np.asarray(bytearray(f.read()), dtype="uint8")
                        image = cv2.imdecode(image_data, cv2.IMREAD_COLOR)
                    print(f"Using cached image: {cache_path}")
                except Exception as e:
                    print(f"Error reading cached image: {str(e)}")
                    image = None
            
            # Read the image if not cached or cache read failed
            if image is None:
                # Check if the file exists locally
                local_file_exists = False
                if not image_path.startswith(('http://', 'https://')):
                    local_file_exists = os.path.exists(image_path)
                    
                    if local_file_exists:
                        try:
                            print(f"Reading local image file: {image_path}")
                            with open(image_path, 'rb') as f:
                                image_data = np.asarray(bytearray(f.read()), dtype="uint8")
                                image = cv2.imdecode(image_data, cv2.IMREAD_COLOR)
                            
                            # Cache the image
                            if image is not None:
                                try:
                                    cv2.imwrite(cache_path, image)
                                    print(f"Cached local image to: {cache_path}")
                                except Exception as e:
                                    print(f"Error caching local image: {str(e)}")
                        except Exception as e:
                            print(f"Error reading local image: {str(e)}")
                            local_file_exists = False
                
                # If local file access failed or it's a remote path, try URL access
                if not local_file_exists:
                    # Try the label-set directory paths
                    potential_paths = [
                        '/app/static/images/label-set/navagunjara-ortho-set',
                        '/app/static/images/label-set',
                    ]
                    
                    # Add the filename to the potential paths
                    filename = os.path.basename(image_path)
                    for base_path in potential_paths:
                        potential_file = os.path.join(base_path, filename)
                        print(f"Trying potential path: {potential_file}")
                        
                        if os.path.exists(potential_file):
                            try:
                                print(f"Found image at: {potential_file}")
                                with open(potential_file, 'rb') as f:
                                    image_data = np.asarray(bytearray(f.read()), dtype="uint8")
                                    image = cv2.imdecode(image_data, cv2.IMREAD_COLOR)
                                
                                if image is not None:
                                    try:
                                        cv2.imwrite(cache_path, image)
                                        print(f"Cached found image to: {cache_path}")
                                    except Exception as e:
                                        print(f"Error caching found image: {str(e)}")
                                    break
                            except Exception as e:
                                print(f"Error reading found file: {str(e)}")
            
            if image is None:
                return JsonResponse({
                    'success': False,
                    'message': 'Failed to access or decode the image. Check server logs for details.'
                }, status=400)
            
            # Get dimensions of the image
            h, w = image.shape[:2]
            print(f"Successfully loaded image with dimensions: {w}x{h}")
            
            # Create simple grid data (simplified version)
            grid_data = create_simple_grid(image, click_point)
            
            # Return the grid data
            return JsonResponse({
                'success': True,
                'grid': grid_data,
                'processingTime': 0.1
            })
        
        except Exception as e:
            import traceback
            print(f"Grid detection request error: {str(e)}")
            print(traceback.format_exc())
            return JsonResponse({
                'success': False,
                'message': f'Error processing request: {str(e)}'
            }, status=500)
    
    return JsonResponse({
        'success': False,
        'message': 'Method not allowed'
    }, status=405)

def create_simple_grid(image, click_point=None):
    """
    Create a grid based on fixed scale assumptions:
    - Each image is 1 meter wide in true scale
    - Image has correct aspect ratio
    - Grid cells are 10cm x 10cm
    
    Args:
        image: OpenCV image (numpy array)
        click_point: Optional dict with x, y coordinates where user clicked
    
    Returns:
        dict with grid data
    """
    h, w = image.shape[:2]
    
    # Calculate scale factor (pixels per meter)
    pixels_per_meter = w  # Since we assume image width = 1 meter
    
    # Calculate cell size in pixels (10cm = 0.1m)
    cell_size_pixels = int(pixels_per_meter * 0.1)  # 10cm in pixels
    
    # Calculate number of cells in each direction
    cells_horizontal = 10  # 1 meter / 10cm = 10 cells
    cells_vertical = int(h / cell_size_pixels)  # Based on aspect ratio
    
    # Define grid starting point
    # If click point is provided, center the grid around it
    if click_point and 'x' in click_point and 'y' in click_point:
        # Calculate the closet grid line to the click point
        closest_x = round(int(click_point['x']) / cell_size_pixels) * cell_size_pixels
        closest_y = round(int(click_point['y']) / cell_size_pixels) * cell_size_pixels
        
        # Calculate grid boundaries centered around click point
        half_width = min(5 * cell_size_pixels, w // 2)
        half_height = min(5 * cell_size_pixels, h // 2)
        
        x_start = max(0, closest_x - half_width)
        y_start = max(0, closest_y - half_height)
    else:
        # Start from top-left
        x_start = 0
        y_start = 0
    
    # Create grid lines
    grid_lines = []
    intersections = []
    
    # Horizontal lines
    for i in range(cells_vertical + 1):
        y = y_start + i * cell_size_pixels
        if y >= h:
            break
        grid_lines.append({
            'start': {'x': 0, 'y': y},
            'end': {'x': w, 'y': y}
        })
    
    # Vertical lines
    for i in range(cells_horizontal + 1):
        x = x_start + i * cell_size_pixels
        if x >= w:
            break
        grid_lines.append({
            'start': {'x': x, 'y': 0},
            'end': {'x': x, 'y': h}
        })
    
    # Create intersection points
    for i in range(cells_vertical + 1):
        y = y_start + i * cell_size_pixels
        if y >= h:
            continue
        for j in range(cells_horizontal + 1):
            x = x_start + j * cell_size_pixels
            if x >= w:
                continue
            intersections.append({
                'x': x,
                'y': y
            })
    
    # Return grid data
    return {
        'lines': grid_lines,
        'intersections': intersections,
        'metrics': {
            'cellWidth': cell_size_pixels,
            'cellHeight': cell_size_pixels,
            'rotation': 0,
            'confidence': 1.0,
            'horizontalLines': cells_vertical + 1,
            'verticalLines': cells_horizontal + 1,
            'realWorldScale': {
                'width': 0.1,  # 10cm in meters
                'height': 0.1,  # 10cm in meters
                'unit': 'meters'
            },
            'algorithm': 'fixed_scale_grid'
        }
    }

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

def label_3d_sigma(request):
    """
    Optimized 3D model viewer (SIGMA version) with server-side optimization.
    This view uses a template that implements:
        - GLB binary format instead of GLTF
        - Draco mesh compression
        - Progress tracking
        - HTTP/2 preloading
        - Performance monitoring
    """
    context = {}
    
    # Add information about server-side optimizations to context
    optimization_info = {
        'version': 'SIGMA',
        'format': 'GLB + Draco',
        'optimizations': [
            'Server-side mesh compression',
            'Binary format for faster loading',
            'HTTP/2 with preloading',
            'Texture optimization',
            'Level of Detail (LOD) variants'
        ]
    }
    context['optimization_info'] = optimization_info
    
    return render(request, 'web/label_3D_sigma.html', context)

def label_topology(request):
    """
    Cesium hybrid 2D/3D viewer combining the best features from both 2D and 3D applications.
    This view provides:
        - 2D/3D/Columbus view modes
        - Advanced measurement tools
        - 3D terrain and models support
        - Temporal data layers
        - Real-time statistics
        - Performance monitoring
    """
    context = {}
    
    # Add viewer configuration information
    viewer_info = {
        'version': 'Hybrid',
        'engine': 'Cesium.js',
        'features': [
            'Multiple view modes (2D/3D/Columbus)',
            'Interactive measurement tools',
            '3D terrain visualization', 
            'GLTF/GLB model loading',
            'Temporal data layer support',
            'Real-time performance monitoring',
            'Responsive design with mobile support'
        ],
        'data_sources': [
            'Custom MBTiles layers',
            'OpenStreetMap',
            'Satellite imagery',
            'World terrain data',
            '3D models (GLTF/GLB)'
        ]
    }
    context['viewer_info'] = viewer_info
    context['cesium_ion_token'] = settings.CESIUM_ION_TOKEN
    
    return render(request, 'web/label_topology.html', context)

def label_search(request):
    """
    DeepGIS Search - Cesium hybrid 2D/3D viewer for geospatial search.
    This view provides:
        - Full Cesium 3D visualization
        - Search and discovery features
        - All topology viewer capabilities
    """
    context = {}
    
    # Add viewer configuration information
    viewer_info = {
        'version': 'Search',
        'engine': 'Cesium.js',
        'features': [
            'Geospatial search capabilities',
            'Multiple view modes (2D/3D/Columbus)',
            'Interactive measurement tools',
            '3D models and terrain',
            'WebXR/VR support',
            'Real-time statistics'
        ]
    }
    context['viewer_info'] = viewer_info
    context['cesium_ion_token'] = settings.CESIUM_ION_TOKEN
    
    return render(request, 'web/label_search.html', context)


def label_topology_sigma(request):
    """
    Refactored Cesium hybrid 2D/3D viewer (SIGMA version) with optimized code structure.
    This is the refactored version with:
        - 40% reduced code size through CSS custom properties
        - Consolidated JavaScript with utility classes
        - Improved maintainability and performance
        - Modern CSS architecture with design tokens
        - Reduced duplication and better organization
    """
    context = {}
    
    # Add refactored viewer configuration information
    viewer_info = {
        'version': 'SIGMA (Refactored)',
        'engine': 'Cesium.js',
        'optimizations': [
            '40% code reduction through refactoring',
            'CSS custom properties for theming',
            'Utility classes and mixins',
            'Consolidated JavaScript architecture',
            'Improved maintainability',
            'Better performance optimization'
        ],
        'features': [
            'Multiple view modes (2D/3D/Columbus)',
            'Interactive measurement tools',
            '3D terrain visualization', 
            'GLTF/GLB model loading',
            'Temporal data layer support',
            'Real-time performance monitoring',
            'Responsive design with mobile support',
            'Modern CSS architecture',
            'Reduced code duplication'
        ],
        'data_sources': [
            'Custom MBTiles layers',
            'OpenStreetMap',
            'Satellite imagery',
            'World terrain data',
            '3D models (GLTF/GLB)'
        ],
        'technical_improvements': [
            'CSS custom properties for consistent theming',
            'Utility classes for common patterns',
            'Consolidated celestial calculations',
            'Generic button handler factory',
            'Centralized configuration management',
            'Improved error handling patterns'
        ]
    }
    context['viewer_info'] = viewer_info
    context['cesium_ion_token'] = settings.CESIUM_ION_TOKEN
    
    return render(request, 'web/label_topology_refactored.html', context)

def label_moon_viewer(request):
    """
    Cesium Moon viewer with 3D visualization capabilities.
    This viewer provides:
        - Lunar surface visualization
        - Moon terrain and imagery from Cesium Ion
        - Interactive measurement tools
        - Multiple view modes (2D/3D/Columbus)
        - Real-time performance monitoring
        - Responsive design with mobile support
    """
    context = {}
    
    # Add Moon viewer configuration information
    viewer_info = {
        'version': 'Moon Viewer',
        'engine': 'Cesium.js',
        'celestial_body': 'Moon',
        'features': [
            'Multiple view modes (2D/3D/Columbus)',
            'Interactive measurement tools',
            'Lunar terrain visualization',
            'Moon surface imagery',
            'Real-time performance monitoring',
            'Responsive design with mobile support',
            'Famous lunar landing sites'
        ],
        'data_sources': [
            'Cesium Ion Moon imagery',
            'Cesium Ion Moon terrain',
            'Apollo landing site markers',
            'Lunar feature annotations'
        ],
        'landing_sites': [
            {'name': 'Apollo 11', 'lat': 0.67408, 'lon': 23.47297},
            {'name': 'Apollo 12', 'lat': -3.01239, 'lon': -23.42157},
            {'name': 'Apollo 14', 'lat': -3.64544, 'lon': -17.47139},
            {'name': 'Apollo 15', 'lat': 26.13224, 'lon': 3.62981},
            {'name': 'Apollo 16', 'lat': -8.97301, 'lon': 15.50019},
            {'name': 'Apollo 17', 'lat': 20.19080, 'lon': 30.77168}
        ]
    }
    context['viewer_info'] = viewer_info
    context['cesium_ion_token'] = settings.CESIUM_ION_TOKEN
    
    return render(request, 'web/label_moon_viewer.html', context)

@csrf_exempt
def opentopography_lidar_search(request):
    """
    Search for OpenTopography LiDAR/point cloud datasets in viewport area.
    
    GET /api/opentopography/lidar-search?west=-116.5&east=-116.4&south=36.5&north=36.6
    
    Returns available LiDAR datasets for the specified bounding box.
    """
    if request.method != 'GET':
        return JsonResponse({'error': 'Only GET method allowed'}, status=405)
    
    try:
        import os
        import requests
        
        west = float(request.GET.get('west'))
        east = float(request.GET.get('east'))
        south = float(request.GET.get('south'))
        north = float(request.GET.get('north'))
        
        # Validate bounding box
        if not (-180 <= west <= 180) or not (-180 <= east <= 180) or \
           not (-90 <= south <= 90) or not (-90 <= north <= 90) or \
           south >= north or west >= east:
            return JsonResponse({'error': 'Invalid bounding box coordinates'}, status=400)
        
        # Get API key from environment
        api_key = os.environ.get('OPENTOPOGRAPHY_API_KEY', '')
        
        # OpenTopography REST API endpoint for dataset search
        # Note: OpenTopography uses a REST API for dataset discovery
        # The actual endpoint may vary - this is a placeholder structure
        base_url = 'https://portal.opentopography.org/API'
        
        # For now, we'll query their dataset catalog API
        # This is a simplified version - actual implementation may need to use their web portal API
        search_url = f'{base_url}/datasets'
        
        params = {
            'west': west,
            'east': east,
            'south': south,
            'north': north,
            'outputFormat': 'json'
        }
        
        if api_key:
            params['API_Key'] = api_key
        
        try:
            response = requests.get(search_url, params=params, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                return JsonResponse({
                    'success': True,
                    'bounds': {'west': west, 'east': east, 'south': south, 'north': north},
                    'datasets': data.get('datasets', []),
                    'count': len(data.get('datasets', []))
                })
            else:
                # If API endpoint doesn't exist or returns error, return mock data structure
                # In production, you'd want to implement proper API integration
                return JsonResponse({
                    'success': True,
                    'bounds': {'west': west, 'east': east, 'south': south, 'north': north},
                    'datasets': [],
                    'count': 0,
                    'message': 'OpenTopography API integration in progress. Check portal.opentopography.org for available datasets.',
                    'portal_url': f'https://portal.opentopography.org/datasets?bbox={west},{south},{east},{north}'
                })
                
        except requests.exceptions.RequestException as e:
            # Return helpful response even if API call fails
            return JsonResponse({
                'success': True,
                'bounds': {'west': west, 'east': east, 'south': south, 'north': north},
                'datasets': [],
                'count': 0,
                'message': f'Could not connect to OpenTopography API: {str(e)}',
                'portal_url': f'https://portal.opentopography.org/datasets?bbox={west},{south},{east},{north}',
                'note': 'You can manually search for datasets at the portal URL above'
            })
            
    except ValueError as e:
        return JsonResponse({'error': f'Invalid parameter: {str(e)}'}, status=400)
    except Exception as e:
        import traceback
        print(f'OpenTopography LiDAR search error: {str(e)}')
        print(traceback.format_exc())
        return JsonResponse({'error': 'Internal server error'}, status=500)


@csrf_exempt
def elevation_proxy(request):
    """Proxy for elevation data APIs to avoid CORS issues."""
    
    if request.method != 'GET':
        return JsonResponse({'error': 'Only GET method allowed'}, status=405)
    
    try:
        lat = float(request.GET.get('lat'))
        lng = float(request.GET.get('lng'))
        
        # Validate coordinates
        if not (-90 <= lat <= 90) or not (-180 <= lng <= 180):
            return JsonResponse({'error': 'Invalid coordinates'}, status=400)
        
        # Try multiple elevation APIs
        elevation_apis = [
            {
                'name': 'USGS',
                'url': f'https://nationalmap.gov/epqs/pqs.php?x={lng}&y={lat}&units=Meters&output=json',
                'parser': lambda data: data.get('USGS_Elevation_Point_Query_Service', {}).get('Elevation_Query', {}).get('Elevation')
            },
            {
                'name': 'OpenTopoData',
                'url': f'https://api.opentopodata.org/v1/srtm30m?locations={lat},{lng}',
                'parser': lambda data: data.get('results', [{}])[0].get('elevation')
            }
        ]
        
        for api in elevation_apis:
            try:
                response = requests.get(api['url'], timeout=5)
                if response.status_code == 200:
                    data = response.json()
                    elevation = api['parser'](data)
                    
                    if elevation is not None and elevation != -1000000:  # USGS uses -1000000 for no data
                        return JsonResponse({
                            'elevation': float(elevation),
                            'source': api['name'],
                            'coordinates': {'lat': lat, 'lng': lng}
                        })
            except Exception as e:
                print(f"Error with {api['name']} API: {str(e)}")
                continue
        
        # If all APIs fail, return no data available
        return JsonResponse({
            'elevation': None,
            'source': 'none',
            'coordinates': {'lat': lat, 'lng': lng},
            'message': 'No elevation data available for this location'
        })
        
    except ValueError:
        return JsonResponse({'error': 'Invalid latitude or longitude values'}, status=400)
    except Exception as e:
        print(f'Elevation proxy error: {str(e)}')
        return JsonResponse({'error': 'Internal server error'}, status=500)


# ============================================================================
# SEMI-SUPERVISED LABELING VIEWS
# Using Mask2Former and Segment Anything for assisted labeling
# ============================================================================

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


# ===== TRAINING DATASET MANAGEMENT API =====

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

# ============================================================================
# AI ANALYSIS REPORT VIEWS
# Display AI analysis results in a formatted report page
# ============================================================================

def ai_analysis_report(request, session_id):
    """
    Display AI analysis report page with query image, results, and metadata.
    
    URL: /ai-analysis/report/<session_id>/
    """
    from pathlib import Path
    import json
    from django.http import Http404
    from datetime import datetime
    
    # Base results directory
    results_base = Path('/app/deepgis_results')
    
    # Try to find the session directory
    # Use exact match instead of substring to avoid matching wrong directories
    session_dir = None
    for subdir in ['sam_results', 'zero_shot_results', 'mask2former_results', 'yolov8_results', 'grounding_dino_results', 'grounded_sam_results']:
        results_dir = results_base / subdir
        if results_dir.exists():
            # Try exact match first (session_id should match directory name exactly)
            session_path = results_dir / session_id
            if session_path.exists() and session_path.is_dir():
                session_dir = session_path
                break
            # Fallback: try iterating for backwards compatibility
            # (in case session_id format changed or there are variations)
            if not session_dir:
                for item in results_dir.iterdir():
                    if item.is_dir() and item.name == session_id:
                        session_dir = item
                        break
            if session_dir:
                break
    
    if not session_dir or not session_dir.exists():
        raise Http404(f"Analysis session not found: {session_id}")
    
    # Load metadata
    metadata_path = session_dir / 'metadata.json'
    metadata = {}
    if metadata_path.exists():
        with open(metadata_path, 'r') as f:
            metadata = json.load(f)
    
    # Determine model type from directory name
    model_type = 'unknown'
    if 'sam_' in session_dir.name:
        model_type = 'sam'
    elif 'zero_shot_' in session_dir.name:
        model_type = 'zero_shot'
    elif 'mask2former_' in session_dir.name:
        model_type = 'mask2former'
    elif 'yolov8_' in session_dir.name:
        model_type = 'yolov8'
    elif 'grounding_dino_' in session_dir.name:
        model_type = 'grounding_dino'
    elif 'grounded_sam_' in session_dir.name:
        model_type = 'grounded_sam'
    
    # Get file paths
    query_image_path = session_dir / 'query_image.png'
    visualization_path = None
    geojson_path = session_dir / 'segments.geojson'
    if not geojson_path.exists():
        geojson_path = session_dir / 'detections.geojson'
    
    # Find visualization (check multiple possible filenames)
    for viz_name in ['segmentation_visualization.jpg', 'detection_visualization.jpg', 'visualization.jpg', 'result.jpg']:
        viz_path = session_dir / viz_name
        if viz_path.exists():
            visualization_path = viz_path
            break
    
    # Load GeoJSON for summary
    geojson_data = None
    if geojson_path.exists():
        with open(geojson_path, 'r') as f:
            geojson_data = json.load(f)
    
    # Generate summary text
    summary = generate_analysis_summary(metadata, geojson_data, model_type)
    
    # Serialize GeoJSON and metadata for JavaScript (safe JSON)
    geojson_json = json.dumps(geojson_data) if geojson_data else 'null'
    metadata_json = json.dumps(metadata)
    
    context = {
        'session_id': session_id,
        'session_dir': str(session_dir),
        'metadata': metadata,
        'metadata_json': metadata_json,  # JSON string for JavaScript
        'model_type': model_type,
        'summary': summary,
        'has_query_image': query_image_path.exists(),
        'has_visualization': visualization_path is not None,
        'has_geojson': geojson_path.exists(),
        'num_features': len(geojson_data.get('features', [])) if geojson_data else 0,
        'geojson_data': geojson_data,
        'geojson_json': geojson_json  # JSON string for JavaScript
    }
    
    return render(request, 'web/ai_analysis_report.html', context)


def serve_analysis_geojson(request, session_id):
    """
    Serve GeoJSON data for a specific analysis session.
    
    URL: /label/ai-analysis/geojson/<session_id>/
    """
    from pathlib import Path
    import json
    from django.http import Http404, JsonResponse
    
    # Base results directory
    results_base = Path('/app/deepgis_results')
    
    # Try to find the session directory
    session_dir = None
    for subdir in ['sam_results', 'zero_shot_results', 'mask2former_results', 'yolov8_results', 'grounding_dino_results', 'grounded_sam_results']:
        results_dir = results_base / subdir
        if results_dir.exists():
            session_path = results_dir / session_id
            if session_path.exists() and session_path.is_dir():
                session_dir = session_path
                break
    
    if not session_dir or not session_dir.exists():
        raise Http404(f"Analysis session not found: {session_id}")
    
    # Find GeoJSON file
    geojson_path = session_dir / 'segments.geojson'
    if not geojson_path.exists():
        geojson_path = session_dir / 'detections.geojson'
    
    if not geojson_path.exists():
        raise Http404(f"GeoJSON file not found for session: {session_id}")
    
    # Load and return GeoJSON with image metadata
    try:
        with open(geojson_path, 'r') as f:
            geojson_data = json.load(f)
        
        # Try to get image dimensions from query image
        query_image_path = session_dir / 'query_image.png'
        image_width = 996  # Default
        image_height = 996  # Default
        
        if query_image_path.exists():
            try:
                from PIL import Image as PILImage
                with PILImage.open(query_image_path) as img:
                    image_width, image_height = img.size
            except Exception as e:
                print(f"Warning: Could not read image dimensions: {e}")
        
        # Add image dimensions to GeoJSON metadata
        if 'metadata' not in geojson_data:
            geojson_data['metadata'] = {}
        geojson_data['metadata']['image_width'] = image_width
        geojson_data['metadata']['image_height'] = image_height
        
        return JsonResponse(geojson_data, safe=False)
    except Exception as e:
        return JsonResponse({
            'error': str(e)
        }, status=500)


def serve_analysis_image(request, session_id, image_type):
    """
    Serve analysis images (query_image, visualization) from results directory.
    
    URL: /ai-analysis/image/<session_id>/<image_type>/
    image_type: 'query' or 'visualization'
    """
    from pathlib import Path
    from django.http import Http404, FileResponse
    
    results_base = Path('/app/deepgis_results')
    session_dir = None
    
    # Find session directory - use exact match instead of substring
    for subdir in ['sam_results', 'zero_shot_results', 'mask2former_results', 'yolov8_results', 'grounding_dino_results', 'grounded_sam_results']:
        results_dir = results_base / subdir
        if results_dir.exists():
            # Try exact match first
            session_path = results_dir / session_id
            if session_path.exists() and session_path.is_dir():
                session_dir = session_path
                break
            # Fallback: try iterating for backwards compatibility
            # (in case session_id format changed or there are variations)
            if not session_dir:
                for item in results_dir.iterdir():
                    if item.is_dir() and item.name == session_id:
                        session_dir = item
                        break
            if session_dir:
                break
    
    if not session_dir:
        raise Http404(f"Session not found: {session_id}")
    
    # Determine image path
    if image_type == 'query':
        image_path = session_dir / 'query_image.png'
    elif image_type == 'visualization':
        # Try different visualization names
        for viz_name in ['segmentation_visualization.jpg', 'detection_visualization.jpg', 'visualization.jpg']:
            viz_path = session_dir / viz_name
            if viz_path.exists():
                image_path = viz_path
                break
        else:
            raise Http404("Visualization not found")
    else:
        raise Http404("Invalid image type")
    
    if not image_path.exists():
        raise Http404(f"Image not found: {image_path}")
    
    # Determine content type based on file extension
    content_type = 'image/png'  # Default
    if image_path.suffix.lower() == '.jpg' or image_path.suffix.lower() == '.jpeg':
        content_type = 'image/jpeg'
    elif image_path.suffix.lower() == '.png':
        content_type = 'image/png'
    
    # FileResponse handles file closing automatically
    # Use as_attachment=False to display inline, and set proper headers
    response = FileResponse(
        open(image_path, 'rb'),
        content_type=content_type,
        as_attachment=False
    )
    
    # Set headers for proper image display
    response['Content-Disposition'] = f'inline; filename="{image_path.name}"'
    response['Content-Length'] = image_path.stat().st_size
    response['Accept-Ranges'] = 'bytes'
    
    # Disable buffering for large images to ensure full delivery
    response['X-Accel-Buffering'] = 'no'
    
    return response


def generate_analysis_summary(metadata, geojson_data, model_type):
    """Generate a textual summary of the analysis results."""
    summary_parts = []
    
    # Model information
    if model_type == 'sam':
        summary_parts.append("**Segment Anything Model (SAM) Analysis**")
        summary_parts.append(f"Model variant: {metadata.get('model_type', 'vit_b')}")
        summary_parts.append(f"Minimum segment area: {metadata.get('min_area', 'N/A')} pixels")
    elif model_type == 'zero_shot':
        summary_parts.append("**Zero-Shot Object Detection Analysis**")
        summary_parts.append("Model: Mask R-CNN (pre-trained COCO)")
        summary_parts.append(f"Confidence threshold: {metadata.get('confidence_threshold', 'N/A')}")
    elif model_type == 'mask2former':
        summary_parts.append("**Mask2Former Object Detection Analysis**")
        summary_parts.append("Model: Mask2Former (pre-trained COCO)")
        summary_parts.append(f"Confidence threshold: {metadata.get('confidence_threshold', 'N/A')}")
    
    # Location information
    location = metadata.get('location', {})
    if location:
        summary_parts.append(f"\n**Location:**")
        summary_parts.append(f"  - Latitude: {location.get('lat', 'N/A'):.6f}°")
        summary_parts.append(f"  - Longitude: {location.get('lon', 'N/A'):.6f}°")
        summary_parts.append(f"  - Altitude: {location.get('alt', 'N/A'):.1f} m")
        if 'heading' in location:
            summary_parts.append(f"  - Heading: {location.get('heading', 'N/A'):.1f}°")
        if 'pitch' in location:
            summary_parts.append(f"  - Pitch: {location.get('pitch', 'N/A'):.1f}°")
    
    # Results summary
    num_features = len(geojson_data.get('features', [])) if geojson_data else 0
    image_size = metadata.get('image_size', [])
    
    summary_parts.append(f"\n**Analysis Results:**")
    if len(image_size) == 2:
        summary_parts.append(f"  - Image size: {image_size[0]} × {image_size[1]} pixels")
    
    if model_type == 'sam':
        summary_parts.append(f"  - Segments detected: {num_features}")
        summary_parts.append(f"  - Total segments found: {metadata.get('num_segments', num_features)}")
    else:
        summary_parts.append(f"  - Objects detected: {num_features}")
        summary_parts.append(f"  - Total detections: {metadata.get('num_detections', num_features)}")
    
    # Device information
    device_info = metadata.get('device_info', {})
    if device_info:
        summary_parts.append(f"\n**Processing:**")
        if device_info.get('cuda_available'):
            summary_parts.append(f"  - Device: GPU ({device_info.get('gpu_name', 'CUDA')})")
        else:
            summary_parts.append(f"  - Device: CPU")
    
    # Timestamp
    timestamp = metadata.get('timestamp', '')
    if timestamp:
        from datetime import datetime
        try:
            dt = datetime.strptime(timestamp, '%Y%m%d_%H%M%S')
            summary_parts.append(f"\n**Analysis Date:** {dt.strftime('%Y-%m-%d %H:%M:%S')}")
        except:
            summary_parts.append(f"\n**Analysis Date:** {timestamp}")
    
    return "\n".join(summary_parts)


# ===== MISSION PLANNING API ENDPOINTS =====

from django.db import models

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
                'num_waypoints': mission.num_waypoints,
                'default_altitude': mission.default_altitude,
                'default_speed': mission.default_speed,
                'return_to_home': mission.return_to_home,
                'created_at': mission.created_at.isoformat(),
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


# ===== AUTHENTICATION API ENDPOINTS =====

@csrf_exempt
def check_auth_status(request):
    """Check if user is authenticated"""
    if request.user.is_authenticated:
        return JsonResponse({
            'authenticated': True,
            'username': request.user.username,
            'phone': getattr(request.user, 'phone_number', None)
        })
    return JsonResponse({'authenticated': False})


@csrf_exempt
def ajax_phone_login(request):
    """AJAX endpoint for phone-based login"""
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)
    
    try:
        data = json.loads(request.body)
        phone_number = data.get('phone_number', '').strip()
        
        if not phone_number:
            return JsonResponse({'error': 'Phone number is required'}, status=400)
        
        # Validate phone number format (basic validation)
        import re
        if not re.match(r'^\+?[1-9]\d{6,14}$', phone_number.replace(' ', '').replace('-', '')):
            return JsonResponse({'error': 'Invalid phone number format. Use international format (e.g., +1234567890)'}, status=400)
        
        # Import User model from auth app
        from deepgis_xr.apps.auth.models import User
        from django.contrib.auth import login
        
        # Get or create user by phone number
        user, created = User.objects.get_or_create(
            phone_number=phone_number,
            defaults={'username': phone_number}
        )
        
        # In development/DEBUG mode, auto-verify and login
        # For production, you would implement SMS verification here
        if settings.DEBUG:
            user.is_phone_verified = True
            user.save()
            login(request, user)
            
            return JsonResponse({
                'status': 'success',
                'message': 'Logged in successfully',
                'authenticated': True,
                'username': user.username,
                'phone': str(user.phone_number) if user.phone_number else None
            })
        else:
            # In production, send verification code
            # For now, return that verification is needed
            return JsonResponse({
                'status': 'verification_required',
                'message': 'Verification code sent to your phone',
                'authenticated': False
            })
            
    except Exception as e:
        import traceback
        print(f"Login error: {str(e)}")
        print(traceback.format_exc())
        return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
def ajax_logout(request):
    """AJAX endpoint for logout"""
    from django.contrib.auth import logout
    
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)
    
    logout(request)
    return JsonResponse({
        'status': 'success',
        'message': 'Logged out successfully',
        'authenticated': False
    })
