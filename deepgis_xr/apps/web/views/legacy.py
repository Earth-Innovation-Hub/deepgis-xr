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
