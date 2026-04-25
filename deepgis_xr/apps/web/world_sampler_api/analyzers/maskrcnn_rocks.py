"""
MaskRCNN-Rocks instance-segmentation analyzer branch.

Dispatched when `model_type=maskrcnn_rocks`. Proxies the viewport
image to the remote `maskrcnn-rocks-api` Flask service
(`http://192.168.0.232:5002` by default), which serves rock-focused
Mask R-CNN checkpoints from `/mnt/22tb-hdd/maskrcnn/terrestrial/`.

Follows the same pattern as `grounding_dino.py`:

    * `MASKRCNN_ROCKS_API_URL` in Django settings selects the remote
      service. Local fallback is intentionally absent (the rock
      checkpoints only run on the GPU server).
    * Returns a JSON payload shaped like the other detection
      analyzers so `displayZeroShotResults()` on the frontend can
      render the results unchanged (bbox polygons, category badges,
      saved visualization JPEG, etc.).

Upstream REST contract (see `services/maskrcnn-rocks/app.py`):

    POST /api/predict      multipart  file, model_id?, score_threshold?,
                                      mask_threshold?, max_detections?,
                                      return_annotated?
    Response.predictions = { count, boxes[pixel], boxes_norm,
                             scores, labels, masks_rle,
                             masks_polygons_norm, areas }
    Response.annotated_image = "data:image/jpeg;base64,..."  (when
                                                               requested)

`masks_polygons_norm` is what we actually plot on the Cesium viewport:
the upstream service runs cv2.findContours on each binary mask and
ships back a list of rings in [0, 1] image space, ready for
projection. When that field is missing (older service builds) we
fall back to bounding-box rectangles so existing labels still draw,
but the resulting polygon is no longer pixel-precise.
"""

from django.http import JsonResponse

from ._helpers import (
    _create_grounding_dino_visualization,
    _polygons_norm_to_geojson,
)


def _analyze_viewport_maskrcnn_rocks(
    image,
    location,
    model_id,
    score_threshold,
    max_detections,
    scripts_dir,
):
    """
    Run the remote MaskRCNN-Rocks API and return a detection payload
    compatible with the other world-sampler analyzer branches.
    """
    try:
        import io
        import base64
        import json
        from pathlib import Path
        from datetime import datetime
        from PIL import Image
        from django.conf import settings
        import requests

        api_url = getattr(settings, 'MASKRCNN_ROCKS_API_URL', None)
        if not api_url or not api_url.strip():
            return JsonResponse({
                'status': 'error',
                'message': 'MaskRCNN Rocks API is not configured',
                'suggestion': (
                    'Set MASKRCNN_ROCKS_API_URL '
                    '(e.g. http://192.168.0.232:5002) in the web container '
                    'environment.'
                ),
            }, status=503)

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        lat_str = f"lat{location.get('lat', 0):.6f}".replace('.', 'p').replace('-', 'n')
        lon_str = f"lon{location.get('lon', 0):.6f}".replace('.', 'p').replace('-', 'n')
        alt_str = f"alt{int(location.get('alt', 0))}m"

        results_root = Path('/app/deepgis_results') / 'maskrcnn_rocks_results'
        results_root.mkdir(parents=True, exist_ok=True)

        folder_name = f"maskrcnn_rocks_{timestamp}_{lat_str}_{lon_str}_{alt_str}"
        session_dir = results_root / folder_name
        session_dir.mkdir(exist_ok=True)
        session_id = folder_name

        query_image_path = session_dir / 'query_image.png'
        image.save(query_image_path, format='PNG')

        print(f"🪨 Running MaskRCNN-Rocks detection...")
        print(f"   API URL:         {api_url}")
        print(f"   Model ID:        {model_id or '(service default)'}")
        print(f"   Score threshold: {score_threshold}")
        print(f"   Max detections:  {max_detections}")

        device_info = {
            'mode': 'remote_api',
            'api_url': api_url,
            'device': 'remote_gpu',
        }

        # Serialize to JPEG (same strategy as grounding_dino.py).
        img_buffer = io.BytesIO()
        if image.mode in ('RGBA', 'LA', 'P'):
            rgb_image = Image.new('RGB', image.size, (255, 255, 255))
            if image.mode == 'P':
                image = image.convert('RGBA')
            rgb_image.paste(
                image,
                mask=image.split()[-1] if image.mode == 'RGBA' else None,
            )
            rgb_image.save(img_buffer, format='JPEG', quality=95)
        else:
            image.save(img_buffer, format='JPEG', quality=95)
        img_buffer.seek(0)

        form_data = {
            'score_threshold': score_threshold,
            'max_detections': max_detections,
            'return_annotated': 'true',
        }
        if model_id:
            form_data['model_id'] = model_id

        try:
            response = requests.post(
                f"{api_url.rstrip('/')}/api/predict",
                files={'file': ('viewport.jpg', img_buffer, 'image/jpeg')},
                data=form_data,
                timeout=180,
            )
        except requests.exceptions.ConnectionError as e:
            return JsonResponse({
                'status': 'error',
                'message': f'Cannot connect to MaskRCNN Rocks API at {api_url}',
                'suggestion': 'Ensure the maskrcnn-rocks-api container is running on the GPU host',
                'debug': {'api_url': api_url, 'error': str(e)},
            }, status=503)
        except requests.exceptions.Timeout:
            return JsonResponse({
                'status': 'error',
                'message': 'MaskRCNN Rocks API request timed out',
                'suggestion': 'The image may be too large or the model is still warming up',
                'api_url': api_url,
            }, status=504)
        except Exception as e:
            import traceback
            return JsonResponse({
                'status': 'error',
                'message': f'MaskRCNN Rocks API request failed: {e}',
                'traceback': traceback.format_exc(),
                'api_url': api_url,
            }, status=500)

        if response.status_code != 200:
            error_detail = ''
            try:
                error_detail = response.json().get('error', '') or response.text[:500]
            except Exception:
                error_detail = response.text[:500] if response.text else 'No error details'
            print(f"❌ API returned {response.status_code}: {error_detail}")
            return JsonResponse({
                'status': 'error',
                'message': f'MaskRCNN Rocks API error: HTTP {response.status_code}',
                'detail': error_detail,
                'api_url': api_url,
                'suggestion': 'Check container logs: docker logs maskrcnn-rocks-api',
            }, status=502)

        api_result = response.json()
        if not api_result.get('success', False):
            err = api_result.get('error', 'Unknown error from API')
            return JsonResponse({
                'status': 'error',
                'message': f'MaskRCNN Rocks API error: {err}',
                'api_url': api_url,
            }, status=500)

        predictions = api_result.get('predictions', {}) or {}
        num_detections = int(predictions.get('count', 0) or 0)
        print(f"✓ Found {num_detections} rocks via remote API")

        # Upstream returns pixel boxes already (see services/maskrcnn-rocks/app.py).
        api_boxes = predictions.get('boxes', []) or []
        api_boxes_norm = predictions.get('boxes_norm', []) or []
        api_scores = predictions.get('scores', []) or []
        api_labels = predictions.get('labels', []) or []
        api_areas = predictions.get('areas', []) or []
        api_masks = predictions.get('masks_rle', []) or []
        api_polygons = predictions.get('masks_polygons_norm', []) or []

        img_width, img_height = image.width, image.height

        detections_data = []
        masks_with_polygons = 0
        for i in range(num_detections):
            if i < len(api_boxes) and api_boxes[i]:
                bbox = [float(v) for v in api_boxes[i]]
            elif i < len(api_boxes_norm) and api_boxes_norm[i]:
                bn = api_boxes_norm[i]
                bbox = [
                    float(bn[0]) * img_width,
                    float(bn[1]) * img_height,
                    float(bn[2]) * img_width,
                    float(bn[3]) * img_height,
                ]
            else:
                bbox = [0.0, 0.0, 0.0, 0.0]

            score = float(api_scores[i]) if i < len(api_scores) else 0.0
            label = api_labels[i] if i < len(api_labels) else 'rock'
            area = api_areas[i] if i < len(api_areas) else None
            mask_rle = api_masks[i] if i < len(api_masks) else None
            polygons_norm = (
                api_polygons[i] if i < len(api_polygons) else None
            )
            has_polygons = bool(polygons_norm)
            if has_polygons:
                masks_with_polygons += 1

            detections_data.append({
                'detection_id': i + 1,
                'class_name': label,
                'confidence': score,
                'bbox': bbox,
                'area': area,
                'mask_rle': mask_rle,
                'mask_polygons_norm': polygons_norm,
                # Reflects what we'll actually draw: True iff we have
                # vector contours to render (not just an RLE bitmap we
                # would otherwise downgrade to a bbox).
                'has_mask': has_polygons,
            })

        if num_detections > 0:
            print(
                f"  ↳ {masks_with_polygons}/{num_detections} masks have "
                f"vector contours; "
                f"{num_detections - masks_with_polygons} will fall back "
                f"to bounding boxes"
            )

        # Persist annotated JPEG from the API if it shipped one, otherwise
        # draw boxes locally to match the other analyzers' outputs.
        visualization_path = None
        annotated = api_result.get('annotated_image')
        if annotated:
            try:
                if ',' in annotated:
                    annotated = annotated.split(',', 1)[1]
                annotated_bytes = base64.b64decode(annotated)
                vis_img = Image.open(io.BytesIO(annotated_bytes))
                visualization_path = session_dir / 'detection_visualization.jpg'
                vis_img.save(visualization_path, quality=95)
            except Exception as viz_err:
                print(f"Warning: could not save annotated image from API: {viz_err}")

        if visualization_path is None and num_detections > 0:
            try:
                visualization_path = _create_grounding_dino_visualization(
                    image, detections_data, session_dir
                )
            except Exception as viz_err:
                print(f"Warning: could not render local visualization: {viz_err}")

        # Use vectorized mask contours when present (real segmentation
        # polygons on the viewport); detections without polygons fall
        # through to bbox rectangles inside the helper.
        geojson = _polygons_norm_to_geojson(
            detections_data, img_width, img_height
        )

        geojson_path = session_dir / 'detections.geojson'
        with open(geojson_path, 'w') as f:
            json.dump(geojson, f, indent=2)

        metadata = {
            'timestamp': timestamp,
            'location': location,
            'model_type': 'maskrcnn_rocks',
            'model_id_requested': model_id or None,
            'model_used': api_result.get('model') or api_result.get('model_id'),
            'score_threshold': score_threshold,
            'max_detections': max_detections,
            'image_size': [img_width, img_height],
            'num_detections': num_detections,
            'inference_ms': api_result.get('inference_ms'),
            'device_info': device_info,
            'session_dir': str(session_dir.relative_to('/app/deepgis_results')),
        }
        metadata_path = session_dir / 'metadata.json'
        with open(metadata_path, 'w') as f:
            json.dump(metadata, f, indent=2)

        return JsonResponse({
            'status': 'success',
            'num_detections': num_detections,
            'detections': detections_data,
            'geojson': geojson,
            'location': location,
            'image_size': [img_width, img_height],
            'model_type': 'maskrcnn_rocks',
            'model_id': api_result.get('model_id'),
            'inference_ms': api_result.get('inference_ms'),
            'device_info': device_info,
            'saved_to': {
                'session_dir': str(session_dir.relative_to('/app/deepgis_results')),
                'query_image': str(query_image_path.relative_to('/app/deepgis_results')),
                'visualization': (
                    str(visualization_path.relative_to('/app/deepgis_results'))
                    if visualization_path else None
                ),
                'geojson': str(geojson_path.relative_to('/app/deepgis_results')),
                'metadata': str(metadata_path.relative_to('/app/deepgis_results')),
                'host_path': str(session_dir).replace(
                    '/app/deepgis_results', './deepgis_results'
                ),
            },
            'report_url': f'/label/ai-analysis/report/{session_id}/',
        })

    except Exception as e:
        import traceback
        error_traceback = traceback.format_exc()
        print(f"\n❌ MaskRCNN Rocks Analysis Error:")
        print(f"Error message: {e}")
        print(f"Traceback:\n{error_traceback}")
        return JsonResponse({
            'status': 'error',
            'message': str(e),
            'traceback': error_traceback,
        }, status=500)
