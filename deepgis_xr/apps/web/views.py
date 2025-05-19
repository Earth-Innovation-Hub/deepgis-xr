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

from deepgis_xr.apps.core.models import Image, CategoryType, ImageLabel, RasterImage, Labeler, CategoryLabel


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

def index(request):
    return render(request, 'web/index.html')

def label(request):
    return render(request, 'web/label.html')

def stl_viewer(request):
    """
    Renders the modular Three.js STL viewer page.
    This is a cleaner reimplementation of the 3D model viewer functionality.
    """
    return render(request, 'web/stl_viewer.html')

def label_3d(request):
    return render(request, 'web/label_3d.html')

def label_3d_dev(request):
    return render(request, 'web/label_3d_dev.html')

def map_label(request):
    return render(request, 'web/map_label.html')

def view_label(request):
    return render(request, 'web/view_label.html')

def results(request):
    return render(request, 'web/results.html')

@csrf_exempt
def get_category_info(request):
    # Return categories in the format expected by the frontend
    categories = {
        'Buildings': {
            'color': '#FF0000',
            'id': 1
        },
        'Roads': {
            'color': '#00FF00',
            'id': 2
        },
        'Water Bodies': {
            'color': '#0000FF',
            'id': 3
        }
    }
    return JsonResponse(categories)

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
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            category_name = data.get('name')
            
            # Get existing categories
            categories = {
                'Buildings': {
                    'color': '#FF0000',
                    'id': 1
                },
                'Roads': {
                    'color': '#00FF00',
                    'id': 2
                },
                'Water Bodies': {
                    'color': '#0000FF',
                    'id': 3
                }
            }
            
            # Add new category with a random color
            import random
            color = '#{:06x}'.format(random.randint(0, 0xFFFFFF))
            categories[category_name] = {
                'color': color,
                'id': len(categories) + 1
            }
            
            return JsonResponse({'status': 'success', 'category': {
                'name': category_name,
                'color': color,
                'id': len(categories)
            }})
        except json.JSONDecodeError:
            return JsonResponse({'status': 'error', 'message': 'Invalid JSON'}, status=400)
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
        
        return JsonResponse({
            'status': 'success',
            'message': raster_info
        })
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': str(e)
        }, status=500)

@csrf_exempt
def get_tileserver_layers(request):
    """Get available layers from the tileserver."""
    
    # Configure tileserver URL - use local for development
    TILESERVER_URL = 'https://localhost:8091'
    
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
        
        return JsonResponse({
            'status': 'success',
            'layers': layers,
            'tileserver': TILESERVER_URL
        })
        
    except requests.exceptions.RequestException as e:
        print(f'Tileserver error: {str(e)}')
        return JsonResponse({
            'status': 'error',
            'message': 'Could not connect to tileserver'
        }, status=503)
    except Exception as e:
        print(f'Unexpected error: {str(e)}')
        return JsonResponse({
            'status': 'error',
            'message': str(e)
        }, status=500)

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