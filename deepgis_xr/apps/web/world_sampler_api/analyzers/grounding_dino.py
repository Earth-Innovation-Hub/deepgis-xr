"""
Grounding-DINO text-prompt object-detection analyzer branch.

Dispatched when `model_type=grounding_dino`. Runs IDEA-Research's
Grounding-DINO with a free-text prompt (e.g. "tree. car. person.")
and returns detected bounding boxes + confidences, optionally with a
Matplotlib-rendered PNG overlay.

Uses two helpers from `_helpers.py`:

    _create_grounding_dino_visualization(image, detections, session_dir)
    _detections_to_geojson(detections, image_width, image_height)

Heavy imports (GroundingDINO, torch, PIL, matplotlib) are
function-local.
"""

from django.http import JsonResponse

from ._helpers import (
    _create_grounding_dino_visualization,
    _detections_to_geojson,
    _unavailable_response,
)


def _analyze_viewport_grounding_dino(
    image,
    location,
    text_prompt,
    box_threshold,
    text_threshold,
    scripts_dir,
    analysis_context=None,
):
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
        
        # Extract session ID for report URL (use folder name as session identifier)
        session_id = folder_name
        
        # Save query image
        query_image_path = session_dir / 'query_image.png'
        image.save(query_image_path, format='PNG')
        
        print(f"🔍 Running Grounding DINO detection...")
        print(f"   Text prompt: '{text_prompt}'")
        print(f"   Box threshold: {box_threshold}")
        print(f"   Text threshold: {text_threshold}")
        analysis_context = analysis_context or {}
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
                print(
                    f"⚠ Grounding DINO: cannot connect to {api_url} ({e}); "
                    f"degrading gracefully"
                )
                return _unavailable_response(
                    image=image,
                    location=location,
                    model_type='grounding_dino',
                    reason='connection_error',
                    message=f'Cannot connect to Grounding DINO API at {api_url}',
                    api_url=api_url,
                    suggestion='Ensure the Grounding DINO Docker container is running',
                    detail=str(e),
                )
            except requests.exceptions.Timeout:
                print(
                    f"⚠ Grounding DINO: request to {api_url} timed out; "
                    f"degrading gracefully"
                )
                return _unavailable_response(
                    image=image,
                    location=location,
                    model_type='grounding_dino',
                    reason='timeout',
                    message='Grounding DINO API request timed out',
                    api_url=api_url,
                    suggestion='The image may be too large or the server is under heavy load',
                    retry_after=60,
                )
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
            'analysis_context': analysis_context,
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
            'analysis_context': analysis_context,
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
