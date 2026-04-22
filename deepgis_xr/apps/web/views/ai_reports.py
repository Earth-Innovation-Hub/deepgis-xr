"""
AI analysis report rendering & asset serving.

Moved out of the legacy `views.py` monolith in the Tier B refactor.
Serves query images, model visualisations, and GeoJSON results produced
by the AI analysis pipelines (SAM, Mask2Former, YOLOv8, Grounding DINO,
Grounded SAM 2, zero-shot Mask R-CNN). The filesystem layout under
`/app/deepgis_results/<model>_results/<session_id>/` is the source of
truth; these endpoints are pure read handlers.

Public handlers:
    ai_analysis_report(request, session_id)          HTML report page
    serve_analysis_geojson(request, session_id)      JSON (with image dims)
    serve_analysis_image(request, session_id, image_type)   PNG / JPEG

`generate_analysis_summary` is a helper re-exported for backwards
compatibility; it produces the human-readable markdown summary embedded
in the report template context.
"""

from django.shortcuts import render

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

