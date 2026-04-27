"""
Grounded-SAM (text-prompt instance segmentation) analyzer branch.

Dispatched when `model_type=grounded_sam`. Chains Grounding-DINO
(text-prompted detection) with SAM (segmentation) to produce
text-queryable instance masks. This is the main vegetation /
building-footprint analyzer used by the frontend.

Uses one helper from `_helpers.py`:

    _masks_to_geojson_with_contours(detections, width, height)

which converts per-instance binary masks to GeoJSON polygons via
OpenCV contour extraction. Heavy imports (GroundingDINO,
segment_anything, torch, cv2, PIL, numpy) are function-local.
"""

from django.http import JsonResponse

from ._helpers import _masks_to_geojson_with_contours, _unavailable_response


def _analyze_viewport_grounded_sam(image, location, text_prompt, box_threshold, text_threshold, scripts_dir):
    """
    Internal function to handle Grounded-SAM-2 (detection + segmentation) analysis.
    
    Calls remote Grounded-SAM-2 API for combined detection and instance segmentation.
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
        api_url = getattr(settings, 'GROUNDED_SAM_API_URL', None)
        if not api_url or api_url.strip() == '':
            return _unavailable_response(
                image=image,
                location=location,
                model_type='grounded_sam',
                reason='not_configured',
                message='Grounded-SAM API URL not configured',
                suggestion='Set GROUNDED_SAM_API_URL environment variable',
            )
        
        # Create organized directory structure for saving results
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        lat_str = f"lat{location.get('lat', 0):.6f}".replace('.', 'p').replace('-', 'n')
        lon_str = f"lon{location.get('lon', 0):.6f}".replace('.', 'p').replace('-', 'n')
        alt_str = f"alt{int(location.get('alt', 0))}m"
        
        grounded_sam_results_dir = Path('/app/deepgis_results') / 'grounded_sam_results'
        grounded_sam_results_dir.mkdir(parents=True, exist_ok=True)
        
        # Create session folder
        folder_name = f"grounded_sam_{timestamp}_{lat_str}_{lon_str}_{alt_str}"
        session_dir = grounded_sam_results_dir / folder_name
        session_dir.mkdir(exist_ok=True)
        
        # Extract session ID for report URL (use folder name as session identifier)
        session_id = folder_name
        
        # Save query image
        query_image_path = session_dir / 'query_image.png'
        image.save(query_image_path, format='PNG')
        
        print(f"🎯 Running Grounded-SAM-2 detection + segmentation...")
        print(f"   Text prompt: '{text_prompt}'")
        print(f"   Box threshold: {box_threshold}")
        print(f"   Text threshold: {text_threshold}")
        print(f"   API URL: {api_url}")
        
        # Convert PIL image to JPEG bytes for API
        img_buffer = io.BytesIO()
        if image.mode in ('RGBA', 'LA', 'P'):
            rgb_image = Image.new('RGB', image.size, (255, 255, 255))
            if image.mode == 'P':
                image = image.convert('RGBA')
            rgb_image.paste(image, mask=image.split()[-1] if image.mode == 'RGBA' else None)
            rgb_image.save(img_buffer, format='JPEG', quality=95)
        else:
            image.save(img_buffer, format='JPEG', quality=95)
        img_buffer.seek(0)
        
        device_info = {
            'mode': 'remote_api',
            'api_url': api_url,
            'device': 'remote_gpu'
        }
        
        try:
            # Call Grounded-SAM-2 API with GeoJSON mask format
            print(f"   Sending request to {api_url}/detect")
            print(f"   Image size: {image.width}x{image.height}")
            
            response = requests.post(
                f"{api_url.rstrip('/')}/detect",
                files={'image': ('viewport.jpg', img_buffer, 'image/jpeg')},
                data={
                    'text_prompt': text_prompt,
                    'box_threshold': box_threshold,
                    'text_threshold': text_threshold,
                    'mask_format': 'geojson',  # Request GeoJSON-formatted masks for Cesium
                    'simplify_tolerance': 0.01  # Simplify polygons for performance
                },
                timeout=180  # 3 minute timeout (segmentation takes longer)
            )
            
            if response.status_code != 200:
                error_detail = ""
                try:
                    error_json = response.json()
                    error_detail = error_json.get('error', str(error_json))
                except:
                    error_detail = response.text[:500] if response.text else "No error details"
                
                print(f"❌ API returned {response.status_code}: {error_detail}")
                return JsonResponse({
                    'status': 'error',
                    'message': f'Grounded-SAM API error: HTTP {response.status_code}',
                    'detail': error_detail,
                    'api_url': api_url
                }, status=502)
            
            api_result = response.json()
            
            if not api_result.get('success', False):
                error_msg = api_result.get('error', 'Unknown error from API')
                print(f"❌ API returned error: {error_msg}")
                return JsonResponse({
                    'status': 'error',
                    'message': f'Grounded-SAM API error: {error_msg}',
                    'api_url': api_url
                }, status=500)
            
            results = api_result.get('results', {})
            num_detections = results.get('num_detections', 0)
            detections = results.get('detections', [])
            print(f"✓ API response received: {num_detections} detections")
            
        except requests.exceptions.ConnectionError as e:
            print(
                f"⚠ Grounded-SAM: cannot connect to {api_url} ({e}); "
                f"degrading gracefully"
            )
            return _unavailable_response(
                image=image,
                location=location,
                model_type='grounded_sam',
                reason='connection_error',
                message=f'Cannot connect to Grounded-SAM API at {api_url}',
                api_url=api_url,
                suggestion='Ensure the Grounded-SAM-2 Docker container is running',
                detail=str(e),
            )
        except requests.exceptions.Timeout:
            print(
                f"⚠ Grounded-SAM: request to {api_url} timed out; "
                f"degrading gracefully"
            )
            return _unavailable_response(
                image=image,
                location=location,
                model_type='grounded_sam',
                reason='timeout',
                message='Grounded-SAM API request timed out',
                api_url=api_url,
                suggestion='Segmentation takes longer - wait or reduce image size',
                retry_after=90,
            )
        
        # Parse detections and convert to our format
        img_width = image.width
        img_height = image.height
        
        detections_data = []
        for i, det in enumerate(detections):
            label = det.get('label', 'object')
            confidence = det.get('confidence', 0.0)
            box = det.get('box', [0, 0, 0, 0])  # [x1, y1, x2, y2] in pixels
            
            # Extract GeoJSON mask if available
            # API returns masks as MultiPolygon GeoJSON when mask_format='geojson'
            mask_geojson = det.get('mask', None)  # GeoJSON MultiPolygon from SAM2 API
            
            detection_dict = {
                "detection_id": i + 1,
                "class_name": label,
                "confidence": float(confidence),
                "bbox": [float(x) for x in box]
            }
            
            # Add GeoJSON mask if present
            if mask_geojson is not None:
                detection_dict['mask_geojson'] = mask_geojson
            
            detections_data.append(detection_dict)
        
        # Save annotated image from API if available
        visualization_path = None
        output_image_url = api_result.get('output_image')
        if output_image_url:
            try:
                # Download the annotated image from API
                result_response = requests.get(f"{api_url.rstrip('')}{output_image_url}", timeout=30)
                if result_response.status_code == 200:
                    visualization_path = session_dir / 'segmentation_visualization.jpg'
                    with open(visualization_path, 'wb') as f:
                        f.write(result_response.content)
                    print(f"✓ Saved annotated image from API")
            except Exception as viz_error:
                print(f"Warning: Could not download annotated image: {viz_error}")
        
        # Create GeoJSON from detections with segmentation masks
        # API provides masks in GeoJSON MultiPolygon format - normalize to 0-1 coordinates
        geojson = _masks_to_geojson_with_contours(detections_data, img_width, img_height)
        
        # Log mask usage statistics
        masks_found = sum(1 for det in detections_data if 'mask_geojson' in det and det['mask_geojson'] is not None)
        if masks_found > 0:
            print(f"✓ Using {masks_found}/{num_detections} GeoJSON segmentation masks from API")
        else:
            print(f"⚠ No segmentation masks found, using bounding boxes as polygons")
        
        # Save GeoJSON
        geojson_path = session_dir / 'detections.geojson'
        with open(geojson_path, 'w') as f:
            json.dump(geojson, f, indent=2)
        
        # Save metadata
        metadata = {
            "timestamp": timestamp,
            "model": "grounded_sam",
            "model_name": "Grounded-SAM-2",
            "text_prompt": text_prompt,
            "box_threshold": box_threshold,
            "text_threshold": text_threshold,
            "num_detections": num_detections,
            "location": location,
            "image_size": [img_width, img_height],
            "device_info": device_info
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
            'image_size': [img_width, img_height],
            'model_type': 'grounded_sam',
            'text_prompt': text_prompt,
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
        print(f"\n❌ Grounded-SAM Analysis Error:")
        print(f"Error message: {str(e)}")
        print(f"Traceback:\n{error_traceback}")
        return JsonResponse({
            'status': 'error',
            'message': str(e),
            'traceback': error_traceback
        }, status=500)
