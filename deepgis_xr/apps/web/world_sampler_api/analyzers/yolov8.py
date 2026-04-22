"""
YOLOv8 object-detection analyzer branch.

Dispatched when `model_type=yolov8`. Runs an Ultralytics YOLOv8
checkpoint over the viewport tile; supports a `class_filter` so the
client can restrict results to e.g. only vehicles or only buildings.
Heavy imports (ultralytics, torch, PIL, numpy) are function-local.
"""

from django.http import JsonResponse


def _analyze_viewport_yolov8(image, location, confidence_threshold, yolo_model, class_filter, scripts_dir):
    """Internal function to handle YOLOv8 object detection analysis."""
    try:
        import sys
        from pathlib import Path
        import numpy as np
        import json
        from datetime import datetime
        import torch
        from PIL import Image, ImageDraw, ImageFont
        from django.conf import settings
        
        # Ensure scripts directory is in path
        if str(scripts_dir) not in sys.path:
            sys.path.insert(0, str(scripts_dir))
        
        # Import the YOLO detector
        try:
            from yolo_detection import YOLODetector, COCO_CLASSES
        except ImportError as e:
            return JsonResponse({
                'status': 'error',
                'message': f'YOLOv8 detection script not found: {str(e)}',
                'suggestion': 'Install ultralytics: pip install ultralytics',
                'debug': {
                    'scripts_dir': str(scripts_dir),
                    'sys_path': sys.path[:5],
                    'yolo_detection_exists': (scripts_dir / 'yolo_detection.py').exists() if scripts_dir.exists() else False
                }
            }, status=500)
        
        # Check GPU availability
        cuda_available = torch.cuda.is_available()
        device_info = {'cuda_available': cuda_available}
        
        if cuda_available:
            device_info['device'] = 'cuda'
            device_info['gpu_name'] = torch.cuda.get_device_name(0)
            device_info['gpu_memory'] = f'{torch.cuda.get_device_properties(0).total_memory / 1024**3:.1f} GB'
        else:
            device_info['device'] = 'cpu'
        
        # Initialize detector
        device = 'cuda' if cuda_available else 'cpu'
        try:
            detector = YOLODetector(model_type=yolo_model, device=device, model_dir='/app/models')
        except Exception as e:
            return JsonResponse({
                'status': 'error',
                'message': f'Failed to initialize YOLOv8: {str(e)}',
                'suggestion': 'Make sure ultralytics is properly installed',
                'device_info': device_info
            }, status=500)
        
        # Create organized directory structure for saving results
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        lat_str = f"lat{location.get('lat', 0):.6f}".replace('.', 'p').replace('-', 'n')
        lon_str = f"lon{location.get('lon', 0):.6f}".replace('.', 'p').replace('-', 'n')
        alt_str = f"alt{int(location.get('alt', 0))}m"
        
        yolo_results_dir = Path('/app/deepgis_results') / 'yolov8_results'
        yolo_results_dir.mkdir(parents=True, exist_ok=True)
        
        # Create session folder
        folder_name = f"yolov8_{timestamp}_{lat_str}_{lon_str}_{alt_str}"
        session_dir = yolo_results_dir / folder_name
        session_dir.mkdir(exist_ok=True)
        
        # Extract session ID for report URL (use folder name as session identifier)
        session_id = folder_name
        
        # Save query image
        query_image_path = session_dir / 'query_image.png'
        image.save(query_image_path, format='PNG')
        
        # Parse class filter if provided
        class_names = None
        if class_filter and class_filter.strip():
            class_names = [c.strip() for c in class_filter.split(',') if c.strip()]
        
        try:
            print(f"🔍 Running YOLOv8 detection...")
            print(f"   Model: {yolo_model}")
            print(f"   Confidence: {confidence_threshold}")
            print(f"   Class filter: {class_names if class_names else 'All classes'}")
            
            # Run detection
            detections = detector.detect(
                image,
                confidence=confidence_threshold,
                class_names=class_names
            )
            
            num_detections = detections['num_detections']
            print(f"✓ Found {num_detections} objects")
            
            # Convert to GeoJSON
            geojson = detector.to_geojson(
                detections,
                image.width,
                image.height,
                viewport_bounds=None  # No geo bounds for now
            )
            
            # Create visualization
            visualization_path = None
            try:
                vis_image = detector.visualize(image, detections)
                visualization_path = session_dir / 'detection_visualization.jpg'
                vis_image.save(visualization_path, quality=95)
            except Exception as viz_error:
                print(f"Warning: Could not save visualization: {viz_error}")
            
            # Save GeoJSON
            geojson_path = session_dir / 'detections.geojson'
            with open(geojson_path, 'w') as f:
                json.dump(geojson, f, indent=2)
            
            # Session ID matches folder name for report lookup
            session_id = folder_name
            
            # Save metadata
            metadata = {
                'timestamp': timestamp,
                'location': location,
                'model_type': yolo_model,
                'confidence_threshold': confidence_threshold,
                'class_filter': class_filter if class_filter else None,
                'image_size': [image.width, image.height],
                'num_detections': num_detections,
                'device_info': device_info,
                'session_dir': str(session_dir.relative_to('/app/deepgis_results'))
            }
            metadata_path = session_dir / 'metadata.json'
            with open(metadata_path, 'w') as f:
                json.dump(metadata, f, indent=2)
            
            # Prepare response with detection metadata
            detections_data = []
            for i in range(num_detections):
                bbox = detections['boxes'][i] if len(detections['boxes']) > i else [0, 0, 0, 0]
                detections_data.append({
                    "detection_id": i + 1,
                    "class_name": detections['class_names'][i] if len(detections['class_names']) > i else 'unknown',
                    "class_id": int(detections['class_ids'][i]) if len(detections['class_ids']) > i else -1,
                    "confidence": float(detections['scores'][i]) if len(detections['scores']) > i else 0.0,
                    "bbox": [float(x) for x in bbox]
                })
            
            return JsonResponse({
                'status': 'success',
                'num_detections': num_detections,
                'detections': detections_data,
                'geojson': geojson,
                'location': location,
                'image_size': [image.width, image.height],
                'model_type': 'yolov8',
                'yolo_model': yolo_model,
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
            
        except Exception as detection_error:
            import traceback
            return JsonResponse({
                'status': 'error',
                'message': f'YOLOv8 detection failed: {str(detection_error)}',
                'traceback': traceback.format_exc(),
                'device_info': device_info
            }, status=500)
        
    except Exception as e:
        import traceback
        return JsonResponse({
            'status': 'error',
            'message': str(e),
            'traceback': traceback.format_exc()
        }, status=500)
