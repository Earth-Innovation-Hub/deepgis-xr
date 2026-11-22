"""
YOLO analyzer branch.

Dispatched when `model_type=yolov8`; the name stays for existing clients.
The viewport capture goes to the ultralytics-api service
(``settings.ULTRALYTICS_API_URL``), which runs one of:

* YOLO26 (``yolo26n-seg`` .. ``yolo26x-seg``): the 80 COCO classes, with
  ``class_filter`` restricting by name.
* YOLOE-26 (``yoloe-26s-seg`` ..): open vocabulary; ``class_filter`` is
  the list of things to find.
* SAM 3 (``sam3``): concept segmentation from the same list.

Old ``yolov8*`` ids map to the YOLO26 model of the same size. Masks come
back as normalized outer rings and are drawn one polygon per ring.
"""

import io
import json
from datetime import datetime
from pathlib import Path

from django.http import JsonResponse

from ._helpers import _polygons_norm_to_geojson, _unavailable_response

RESULTS_ROOT = Path('/app/deepgis_results')
RESULTS_SUBDIR = 'yolov8_results'
DEFAULT_MODEL = 'yolo26x-seg'
REQUEST_TIMEOUT_S = 240


def _session_dir(location):
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    lat_str = f"lat{location.get('lat', 0):.6f}".replace('.', 'p').replace('-', 'n')
    lon_str = f"lon{location.get('lon', 0):.6f}".replace('.', 'p').replace('-', 'n')
    alt_str = f"alt{int(location.get('alt', 0))}m"
    folder = RESULTS_ROOT / RESULTS_SUBDIR / f"yolov8_{timestamp}_{lat_str}_{lon_str}_{alt_str}"
    folder.mkdir(parents=True, exist_ok=True)
    return folder, timestamp


def _draw(image, detections):
    from PIL import ImageDraw

    canvas = image.convert('RGB').copy()
    draw = ImageDraw.Draw(canvas)
    w, h = canvas.size
    for det in detections:
        rings = det.get('mask_polygons_norm') or []
        for ring in rings:
            draw.line([(x * w, y * h) for x, y in ring], fill=(16, 185, 129), width=2)
        if not rings:
            draw.rectangle(det['bbox'], outline=(16, 185, 129), width=2)
        x1, y1 = det['bbox'][:2]
        draw.text((x1 + 2, max(0, y1 - 12)), f"{det['class_name']} {det['confidence']:.2f}", fill=(255, 255, 255))
    return canvas


def _analyze_viewport_yolov8(image, location, confidence_threshold, yolo_model, class_filter, scripts_dir):
    """Run a YOLO-family model on the ultralytics-api service."""
    import requests
    from django.conf import settings

    location = location or {}
    model_id = (yolo_model or '').strip() or DEFAULT_MODEL
    api_url = (getattr(settings, 'ULTRALYTICS_API_URL', None) or '').strip()
    if not api_url:
        return _unavailable_response(
            image=image,
            location=location,
            model_type='yolov8',
            reason='not_configured',
            message='ULTRALYTICS_API_URL is not set',
            suggestion='Point ULTRALYTICS_API_URL at the ultralytics-api service',
        )

    buffer = io.BytesIO()
    image.convert('RGB').save(buffer, format='JPEG', quality=95)
    buffer.seek(0)
    try:
        response = requests.post(
            f"{api_url.rstrip('/')}/api/predict",
            files={'file': ('viewport.jpg', buffer, 'image/jpeg')},
            data={
                'model': model_id,
                'classes': class_filter or '',
                'confidence': confidence_threshold,
            },
            timeout=REQUEST_TIMEOUT_S,
        )
    except requests.exceptions.ConnectionError as err:
        print(f"⚠ YOLO: cannot connect to {api_url} ({err})")
        return _unavailable_response(
            image=image,
            location=location,
            model_type='yolov8',
            reason='connection_error',
            message=f'Cannot connect to the YOLO service at {api_url}',
            api_url=api_url,
            suggestion='Ensure the ultralytics-api container is running',
            detail=str(err),
        )
    except requests.exceptions.Timeout:
        print(f"⚠ YOLO: request to {api_url} timed out")
        return _unavailable_response(
            image=image,
            location=location,
            model_type='yolov8',
            reason='timeout',
            message='YOLO service request timed out',
            api_url=api_url,
            suggestion='Try a smaller model or a smaller viewport',
            retry_after=120,
        )

    try:
        body = response.json()
    except ValueError:
        body = {'error': response.text[:500]}
    if response.status_code == 503 and body.get('reason') == 'weights_missing':
        return _unavailable_response(
            image=image,
            location=location,
            model_type='yolov8',
            reason='weights_missing',
            message=body.get('error') or f'{model_id} weights are missing',
            api_url=api_url,
            suggestion=f'Place the {model_id} weights in the ultralytics-api weights directory',
        )
    if response.status_code != 200 or not body.get('success'):
        return JsonResponse({
            'status': 'error',
            'message': f"YOLO: {body.get('error') or f'HTTP {response.status_code}'}",
            'detail': body,
        }, status=400 if response.status_code == 400 else 502)

    detections = body.get('detections') or []
    width, height = image.width, image.height
    geojson = _polygons_norm_to_geojson(detections, width, height)
    served_model = body.get('model') or model_id

    session_dir, timestamp = _session_dir(location)
    session_id = session_dir.name
    query_image_path = session_dir / 'query_image.png'
    image.save(query_image_path, format='PNG')
    geojson_path = session_dir / 'detections.geojson'
    geojson_path.write_text(json.dumps(geojson))
    visualization_path = session_dir / 'detection_visualization.jpg'
    try:
        _draw(image, detections).save(visualization_path, quality=90)
    except Exception as err:
        print(f"Warning: could not save the YOLO visualization: {err}")
        visualization_path = None

    device_info = {
        'mode': 'remote_api',
        'device': body.get('device'),
        'cuda_available': bool(body.get('cuda_available')),
        'gpu_name': body.get('gpu_name'),
        'inference_ms': body.get('inference_ms'),
    }
    metadata = {
        'timestamp': timestamp,
        'location': location,
        'model_type': served_model,
        'family': body.get('family'),
        'confidence_threshold': confidence_threshold,
        'class_filter': class_filter or None,
        'classes': body.get('classes') or [],
        'unknown_classes': body.get('unknown_classes') or [],
        'image_size': [width, height],
        'num_detections': len(detections),
        'device_info': device_info,
        'session_dir': str(session_dir.relative_to(RESULTS_ROOT)),
    }
    metadata_path = session_dir / 'metadata.json'
    metadata_path.write_text(json.dumps(metadata, indent=2))

    return JsonResponse({
        'status': 'success',
        'num_detections': len(detections),
        'detections': [
            {key: det.get(key) for key in ('detection_id', 'class_name', 'class_id', 'confidence', 'bbox', 'area', 'mask_polygons_norm')}
            for det in detections
        ],
        'geojson': geojson,
        'location': location,
        'image_size': [width, height],
        'model_type': 'yolov8',
        'yolo_model': served_model,
        'family': body.get('family'),
        'unknown_classes': body.get('unknown_classes') or [],
        'device_info': device_info,
        'saved_to': {
            'session_dir': str(session_dir.relative_to(RESULTS_ROOT)),
            'query_image': str(query_image_path.relative_to(RESULTS_ROOT)),
            'visualization': str(visualization_path.relative_to(RESULTS_ROOT)) if visualization_path else None,
            'geojson': str(geojson_path.relative_to(RESULTS_ROOT)),
            'metadata': str(metadata_path.relative_to(RESULTS_ROOT)),
        },
        'report_url': f'/label/ai-analysis/report/{session_id}/',
    })

