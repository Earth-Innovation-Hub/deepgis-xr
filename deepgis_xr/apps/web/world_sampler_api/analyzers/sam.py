"""
Segment Anything Model (SAM) analyzer branch for analyze_viewport.

Dispatched when `model_type=sam`. Uses
`segment_anything.SamAutomaticMaskGenerator` against an RGB tile
captured from the Cesium viewport; returns mask polygons as GeoJSON
in image-space (the caller, `http.analyze_viewport`, converts back
to geographic coordinates using the tile extent).

All heavyweight imports (torch, segment_anything, PIL, numpy, GDAL)
are kept inside the function body to preserve the original lazy-load
behaviour — loading this module must not pull torch into the Django
web process on boot.
"""

from django.http import JsonResponse


def _analyze_viewport_sam(image, location, model_type, min_area, scripts_dir):
    """Internal function to handle SAM analysis."""
    try:
        import sys
        from pathlib import Path
        import numpy as np
        import json
        from datetime import datetime
        import importlib
        import torch
        from PIL import Image
        from django.conf import settings
        
        # Check if SAM library is available FIRST (before importing the wrapper)
        try:
            from segment_anything import sam_model_registry, SamAutomaticMaskGenerator
            sam_available = True
        except ImportError as import_err:
            sam_available = False
            return JsonResponse({
                'status': 'error',
                'message': 'Segment Anything library not installed',
                'suggestion': 'Install with: pip install git+https://github.com/facebookresearch/segment-anything.git',
                'note': 'This package must be installed in the Docker container. Add to requirements.txt and rebuild.',
                'debug': {
                    'import_error': str(import_err),
                    'scripts_dir': str(scripts_dir)
                }
            }, status=500)
        
        # Now import the wrapper (it will work since SAM is available)
        try:
            # Force reload the module to ensure SAM_AVAILABLE is updated
            import importlib
            if 'segment_anything_rocks' in sys.modules:
                importlib.reload(sys.modules['segment_anything_rocks'])
            from segment_anything_rocks import SegmentAnythingRocks
        except ImportError as e:
            return JsonResponse({
                'status': 'error',
                'message': f'Segment Anything Model script not found: {str(e)}',
                'suggestion': f'Ensure segment_anything_rocks.py is in {scripts_dir}',
                'debug': {
                    'scripts_dir': str(scripts_dir),
                    'scripts_dir_exists': scripts_dir.exists(),
                    'segment_anything_rocks_exists': (scripts_dir / 'segment_anything_rocks.py').exists() if scripts_dir.exists() else False
                }
            }, status=500)
        
        # Check GPU availability
        import torch
        cuda_available = torch.cuda.is_available()
        device_info = {
            'cuda_available': cuda_available,
            'device': 'cuda' if cuda_available else 'cpu'
        }
        if cuda_available:
            device_info['gpu_name'] = torch.cuda.get_device_name(0)
            device_info['gpu_count'] = torch.cuda.device_count()
        
        # Initialize SAM
        try:
            if cuda_available:
                segmenter = SegmentAnythingRocks(model_type=model_type, device='cuda')
            else:
                segmenter = SegmentAnythingRocks(model_type=model_type, device='cpu')
        except Exception as e:
            # Fallback to CPU if CUDA fails
            if cuda_available:
                try:
                    segmenter = SegmentAnythingRocks(model_type=model_type, device='cpu')
                    device_info['device'] = 'cpu'  # Update device info
                    device_info['cuda_failed'] = str(e)
                except Exception as e2:
                    error_msg = str(e2)
                # Check if it's the SAM_AVAILABLE check
                if 'SAM_AVAILABLE' in error_msg or 'Segment Anything not installed' in error_msg:
                    # Force reload and try again
                    import importlib
                    if 'segment_anything_rocks' in sys.modules:
                        importlib.reload(sys.modules['segment_anything_rocks'])
                    try:
                        segmenter = SegmentAnythingRocks(model_type=model_type, device='cpu')
                    except Exception as e3:
                        return JsonResponse({
                            'status': 'error',
                            'message': f'Failed to initialize SAM after reload: {str(e3)}',
                            'suggestion': 'Restart Django server to clear module cache',
                            'debug': {
                                'original_error': error_msg,
                                'reload_error': str(e3)
                            }
                        }, status=500)
                else:
                    return JsonResponse({
                        'status': 'error',
                        'message': f'Failed to initialize SAM: {error_msg}',
                        'debug': {
                            'model_type': model_type,
                            'tried_cuda': True,
                            'tried_cpu': True
                        }
                    }, status=500)
        
        # Create organized directory structure for saving results
        from django.conf import settings
        from datetime import datetime
        
        # Use shared deepgis_results folder (mounted from host)
        # This allows direct access to results from the host filesystem
        sam_results_dir = Path('/app/deepgis_results') / 'sam_results'
        sam_results_dir.mkdir(parents=True, exist_ok=True)
        
        # Create descriptive folder name with timestamp and location
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        lat_str = f"{location.get('lat', 0):.6f}".replace('.', 'p').replace('-', 'n')
        lon_str = f"{location.get('lon', 0):.6f}".replace('.', 'p').replace('-', 'n')
        alt_str = f"{location.get('alt', 0):.0f}m"
        folder_name = f"sam_{timestamp}_lat{lat_str}_lon{lon_str}_alt{alt_str}_model{model_type}"
        session_dir = sam_results_dir / folder_name
        session_dir.mkdir(parents=True, exist_ok=True)
        
        # Extract session ID for report URL (use folder name as session identifier)
        session_id = folder_name
        
        # Save original query image
        query_image_path = session_dir / 'query_image.png'
        image.save(query_image_path)
        
        # Save image temporarily for SAM processing
        import tempfile
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp_file:
            image.save(tmp_file.name)
            tmp_path = Path(tmp_file.name)
        
        try:
            # Run segmentation
            masks, processed_image = segmenter.segment_image(tmp_path)
            
            # Filter by minimum area
            filtered_masks = [m for m in masks if m['area'] >= min_area]
            
            # Limit number of segments to prevent response size issues
            # Sort by quality (predicted_iou) and take top N
            MAX_SEGMENTS = 200  # Reasonable limit for viewport display
            if len(filtered_masks) > MAX_SEGMENTS:
                # Sort by quality (predicted_iou * stability_score) and take best
                filtered_masks.sort(key=lambda m: m.get('predicted_iou', 0) * m.get('stability_score', 0), reverse=True)
                filtered_masks = filtered_masks[:MAX_SEGMENTS]
                print(f"Limited segments from {len(masks)} to {MAX_SEGMENTS} top-quality segments")
            
            # Use SAM's built-in export_to_geojson method
            geojson = segmenter.export_to_geojson(filtered_masks, image.size)
            
            # Simplify GeoJSON polygons to reduce response size
            # This reduces coordinate points while maintaining shape
            MAX_COORDS_PER_POLYGON = 100  # Maximum coordinate points per polygon
            
            simplified_features = []
            for feature in geojson.get('features', []):
                try:
                    coords = feature['geometry']['coordinates'][0]  # Get polygon coordinates
                    
                    # If polygon has too many points, simplify by sampling
                    if len(coords) > MAX_COORDS_PER_POLYGON:
                        # Sample every Nth point to reduce size
                        step = max(1, len(coords) // MAX_COORDS_PER_POLYGON)
                        simplified_coords = coords[::step]
                        
                        # Ensure polygon is closed (first point = last point)
                        if len(simplified_coords) > 0 and simplified_coords[0] != simplified_coords[-1]:
                            simplified_coords.append(simplified_coords[0])
                        
                        # Update feature with simplified coordinates
                        simplified_feature = {
                            'type': feature['type'],
                            'geometry': {
                                'type': feature['geometry']['type'],
                                'coordinates': [simplified_coords]
                            },
                            'properties': feature.get('properties', {})
                        }
                        simplified_features.append(simplified_feature)
                    else:
                        # Keep original if small enough
                        simplified_features.append(feature)
                except Exception as e:
                    # If simplification fails, use original
                    print(f"Warning: Could not simplify polygon: {e}")
                    simplified_features.append(feature)
            
            geojson['features'] = simplified_features
            
            # Log response size estimate
            import sys
            geojson_size = sys.getsizeof(json.dumps(geojson))
            print(f"GeoJSON size: ~{geojson_size / 1024:.1f} KB ({len(simplified_features)} features)")
            
            # Save visualization with masks overlay
            visualization_path = None
            try:
                visualization = segmenter.visualize_masks(processed_image, filtered_masks)
                visualization_path = session_dir / 'segmentation_visualization.jpg'
                visualization.save(visualization_path, quality=95)
            except Exception as viz_error:
                print(f"Warning: Could not save visualization: {viz_error}")
            
            # Save GeoJSON
            geojson_path = session_dir / 'segments.geojson'
            with open(geojson_path, 'w') as f:
                json.dump(geojson, f, indent=2)
            
            # Save metadata
            metadata = {
                'timestamp': timestamp,
                'location': location,
                'model_type': model_type,
                'min_area': min_area,
                'image_size': [image.width, image.height],
                'num_segments': len(filtered_masks),
                'device_info': device_info,
                'session_dir': str(session_dir.relative_to('/app/deepgis_results'))
            }
            metadata_path = session_dir / 'metadata.json'
            with open(metadata_path, 'w') as f:
                json.dump(metadata, f, indent=2)
            
            # Save individual mask images (optional, for large numbers of segments)
            if len(filtered_masks) <= 50:  # Only save individual masks if reasonable number
                masks_dir = session_dir / 'individual_masks'
                masks_dir.mkdir(exist_ok=True)
                for i, mask_data in enumerate(filtered_masks):
                    mask = mask_data['segmentation']
                    mask_array = (mask.astype(np.uint8) * 255)
                    mask_image = Image.fromarray(mask_array)
                    mask_path = masks_dir / f'mask_{i+1:04d}_area{mask_data["area"]}.png'
                    mask_image.save(mask_path)
            
            # Prepare response with segment metadata (without base64 masks to keep response small)
            # The frontend only needs the GeoJSON for visualization, not the individual mask images
            segments_data = []
            for i, mask_data in enumerate(filtered_masks):
                segments_data.append({
                    "segment_id": i + 1,
                    "area": int(mask_data['area']),
                    "bbox": [int(x) for x in mask_data['bbox']],
                    "predicted_iou": float(mask_data.get('predicted_iou', 0.0)),
                    "stability_score": float(mask_data.get('stability_score', 0.0))
                    # Note: Removed base64-encoded mask images to keep response size manageable
                    # Individual mask images are saved to disk in individual_masks/ folder if needed
                })
            
            # Extract session ID for report URL (use folder name as session identifier)
            session_id = folder_name
            
            return JsonResponse({
                'status': 'success',
                'num_segments': len(filtered_masks),
                'segments': segments_data,
                'geojson': geojson,
                'location': location,
                'image_size': [image.width, image.height],
                'model_type': model_type,
                'device_info': device_info,  # Include GPU/CPU info
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
        error_traceback = traceback.format_exc()
        print(f"\n❌ SAM Analysis Error:")
        print(f"Error message: {str(e)}")
        print(f"Traceback:\n{error_traceback}")
        return JsonResponse({
            'status': 'error',
            'message': str(e),
            'traceback': error_traceback
        }, status=500)
