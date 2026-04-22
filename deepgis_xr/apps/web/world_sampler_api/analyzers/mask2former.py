"""
Mask2Former panoptic-segmentation analyzer branch.

Dispatched when `model_type=mask2former`. Runs Facebook's
Mask2Former checkpoint over the viewport tile and returns per-class
polygons + confidences. Heavy imports (transformers, torch, PIL,
numpy) are function-local.
"""

from django.http import JsonResponse


def _analyze_viewport_mask2former(image, location, confidence_threshold, scripts_dir):
    """Internal function to handle Mask2Former (pre-trained COCO) analysis."""
    try:
        import sys
        from pathlib import Path
        import numpy as np
        import json
        from datetime import datetime
        import torch
        import tempfile
        
        # Import zero-shot detection module (contains ZeroShotMask2Former)
        try:
            from zero_shot_detection import ZeroShotMask2Former, predictions_to_geojson
        except ImportError as e:
            return JsonResponse({
                'status': 'error',
                'message': f'Zero-Shot Detection script not found: {str(e)}',
                'suggestion': f'Ensure zero_shot_detection.py is in {scripts_dir}',
                'debug': {
                    'scripts_dir': str(scripts_dir),
                    'scripts_dir_exists': scripts_dir.exists(),
                    'zero_shot_exists': (scripts_dir / 'zero_shot_detection.py').exists() if scripts_dir.exists() else False
                }
            }, status=500)
        
        # Check GPU availability
        cuda_available = torch.cuda.is_available()
        device_info = {
            'cuda_available': cuda_available,
            'device': 'cuda' if cuda_available else 'cpu'
        }
        if cuda_available:
            device_info['gpu_name'] = torch.cuda.get_device_name(0)
            device_info['gpu_count'] = torch.cuda.device_count()
        
        # Create results directory
        mask2former_results_dir = Path('/app/deepgis_results') / 'mask2former_results'
        mask2former_results_dir.mkdir(parents=True, exist_ok=True)
        
        # Create descriptive folder name
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        lat_str = f"{location.get('lat', 0):.6f}".replace('.', 'p').replace('-', 'n')
        lon_str = f"{location.get('lon', 0):.6f}".replace('.', 'p').replace('-', 'n')
        alt_str = f"{location.get('alt', 0):.0f}m"
        folder_name = f"mask2former_{timestamp}_lat{lat_str}_lon{lon_str}_alt{alt_str}_conf{confidence_threshold:.2f}"
        session_dir = mask2former_results_dir / folder_name
        session_dir.mkdir(parents=True, exist_ok=True)
        
        # Extract session ID for report URL
        session_id = folder_name
        
        # Save query image
        query_image_path = session_dir / 'query_image.png'
        image.save(query_image_path)
        
        # Save image temporarily for processing
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp_file:
            image.save(tmp_file.name)
            tmp_path = Path(tmp_file.name)
        
        try:
            # Initialize Mask2Former detector (pre-trained COCO)
            device = 'cuda' if cuda_available else 'cpu'
            detector = ZeroShotMask2Former(confidence_threshold=confidence_threshold, device=device)
            
            # Run detection
            predictions = detector.predict(tmp_path)
            
            # Convert to GeoJSON
            geojson = predictions_to_geojson(predictions)
            
            # Save visualization (if available)
            visualization_path = None
            try:
                # Note: ZeroShotMask2Former doesn't have a visualize method like ZeroShotMaskRCNN
                # We can create a simple visualization using PIL
                from PIL import ImageDraw, ImageFont
                vis_image = image.copy()
                draw = ImageDraw.Draw(vis_image)
                
                # Try to load a font
                try:
                    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 16)
                except:
                    font = ImageFont.load_default()
                
                # Colors for different classes
                colors = [
                    (255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0),
                    (255, 0, 255), (0, 255, 255), (128, 0, 0), (0, 128, 0)
                ]
                
                # Draw bounding boxes and labels
                for i, det in enumerate(predictions['detections']):
                    color = colors[i % len(colors)]
                    bbox = det['bbox']
                    label = f"{det['class_name']}: {det['confidence']:.2f}"
                    
                    # Draw bounding box
                    draw.rectangle(bbox, outline=color, width=3)
                    
                    # Draw label background
                    text_bbox = draw.textbbox((bbox[0], bbox[1] - 20), label, font=font)
                    draw.rectangle(text_bbox, fill=color)
                    draw.text((bbox[0], bbox[1] - 20), label, fill='white', font=font)
                
                visualization_path = session_dir / 'detection_visualization.jpg'
                vis_image.save(visualization_path, quality=95)
            except Exception as viz_error:
                print(f"Warning: Could not save visualization: {viz_error}")
            
            # Save GeoJSON
            geojson_path = session_dir / 'detections.geojson'
            with open(geojson_path, 'w') as f:
                json.dump(geojson, f, indent=2)
            
            # Save metadata
            metadata = {
                'timestamp': timestamp,
                'location': location,
                'model_type': 'mask2former_coco',
                'confidence_threshold': confidence_threshold,
                'image_size': [image.width, image.height],
                'num_detections': predictions['num_detections'],
                'device_info': device_info,
                'session_dir': str(session_dir.relative_to('/app/deepgis_results'))
            }
            metadata_path = session_dir / 'metadata.json'
            with open(metadata_path, 'w') as f:
                json.dump(metadata, f, indent=2)
            
            # Prepare response with detection metadata
            detections_data = []
            for i, det in enumerate(predictions['detections']):
                detections_data.append({
                    "detection_id": i + 1,
                    "class_name": det['class_name'],
                    "class_id": det['class_id'],
                    "confidence": float(det['confidence']),
                    "bbox": [float(x) for x in det['bbox']],
                    "area": int(det.get('mask_area', 0)) if 'mask_area' in det else 0
                })
            
            return JsonResponse({
                'status': 'success',
                'num_detections': predictions['num_detections'],
                'detections': detections_data,
                'geojson': geojson,
                'location': location,
                'image_size': [image.width, image.height],
                'model_type': 'mask2former',
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
            
        finally:
            # Clean up temporary file
            if tmp_path.exists():
                tmp_path.unlink()
        
    except Exception as e:
        import traceback
        return JsonResponse({
            'status': 'error',
            'message': str(e),
            'traceback': traceback.format_exc()
        }, status=500)
