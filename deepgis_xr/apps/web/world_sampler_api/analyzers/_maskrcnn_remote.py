"""
Shared "run a remote Mask R-CNN service" helper for the world-sampler
analyzer branches that point at the family of containers built from
``services/maskrcnn-rocks/``.

Background
----------

`maskrcnn_rocks.py` and `maskrcnn_house.py` were the first two analyzer
branches that proxied to a remote ``maskrcnn-rocks:latest`` Docker
container. They are nearly identical — same upstream REST contract,
same JPEG re-encoding, same response decoding, same on-disk artefact
layout — but each duplicates ~250 lines of plumbing because the
original split was done before the Analyzer ABC refactor was
sequenced. Their docstrings explicitly call out the deferred merge:

    The duplication is deliberate for now. Both branches will be
    refactored into a shared ``_run_remote_maskrcnn_branch(family,
    api_url, label_fallback, results_subdir, ...)`` helper when the
    deferred Analyzer ABC lands.

When the third sibling (``hypolith``) wanted in, that promise stopped
scaling — six new branches × ~250 lines = ~1.5 k lines of pure
copy-paste. Instead this module crystallises the **plumbing** in one
place and lets each new branch be a ~30-line wrapper that fills in
the cosmetics (settings key, fallback label, results subdir,
container hint, etc.).

Existing ``maskrcnn_rocks`` and ``maskrcnn_house`` are deliberately
left untouched: they ship working code in production today and the
Analyzer-ABC refactor will fold them in as part of a larger surgery.
This helper is private (`_maskrcnn_remote.py`, leading underscore)
specifically so its signature can evolve without breaking external
callers.

Upstream REST contract (see ``services/maskrcnn-rocks/app.py``)
---------------------------------------------------------------

    POST /api/predict      multipart  file, model_id?, score_threshold?,
                                      mask_threshold?, max_detections?,
                                      return_annotated?
    Response.predictions = { count, boxes[pixel], boxes_norm,
                             scores, labels, masks_rle,
                             masks_polygons_norm, areas }
    Response.annotated_image = "data:image/jpeg;base64,..."
                               (when ``return_annotated=true``)

``masks_polygons_norm`` is what we actually plot on the Cesium
viewport: the upstream service runs ``cv2.findContours`` on each
binary mask and ships back a list of rings in [0, 1] image space,
ready for projection. When that field is missing (older service
builds) we fall back to bounding-box rectangles so existing labels
still draw, but the resulting polygon is no longer pixel-precise.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from django.http import JsonResponse


@dataclass(frozen=True)
class RemoteMaskRCNNBranch:
    """
    Identity of one remote Mask R-CNN analyzer branch.

    Everything that varies between the per-service branches lives in
    here. The actual HTTP plumbing, JSON decoding, and on-disk
    artefact layout are shared (see ``run_remote_maskrcnn_branch``).
    """

    model_type: str
    """``model_type`` value the frontend POSTs to trigger this branch
    (e.g. ``maskrcnn_hypolith``). Echoed back in the response and
    written into ``metadata.json`` for the AI-analysis report viewer.
    """

    settings_key: str
    """Django settings attribute the helper reads to find the remote
    service URL (e.g. ``MASKRCNN_HYPOLITH_API_URL``). Falsy/missing
    values fall back to ``settings.MASKRCNN_API_URL`` (the unified
    service) before surfacing a graceful ``not_configured`` envelope.
    """

    display_label: str
    """Human-readable name used in error messages and logs (e.g.
    ``MaskRCNN Hypolith``).
    """

    fallback_label: str
    """Per-detection class label used when the upstream service does
    not return one in ``predictions.labels[i]`` (e.g. ``hypolith``).
    Should match the dominant ``DEFAULT_LABEL_NAME`` configured on
    the container so frontend grouping stays stable across branches.
    """

    results_subdir: str
    """Subdirectory under ``/app/deepgis_results/`` where this branch
    writes session artefacts (e.g. ``maskrcnn_hypolith_results``).
    Each branch gets its own subdir so the AI-analysis report viewer
    can scope listings per model family.
    """

    folder_prefix: str
    """Prefix used to name each per-request session folder inside
    ``results_subdir`` (e.g. ``maskrcnn_hypolith``). The full folder
    name appends a timestamp + lat/lon/alt suffix.
    """

    container_name: str
    """Compose container name shown in the "check container logs"
    suggestion when an HTTP error escapes the remote service (e.g.
    ``maskrcnn-hypolith-api``).
    """

    suggested_default_url: str
    """Best-guess default URL surfaced in the configuration error
    message when ``settings_key`` is unset (e.g.
    ``http://192.168.0.232:5004``).
    """

    default_model_id: Optional[str] = None
    """Family-default checkpoint id from the upstream service registry
    (e.g. ``gobabeb_hero_e0011`` for the hypolith family). Only used
    when the request resolves to the **unified** ``MASKRCNN_API_URL``
    endpoint and the caller did not supply an explicit ``model_id``;
    in that case the helper injects this id into the form payload so
    the unified container picks the right checkpoint for the family.
    Ignored on the legacy per-family path (``settings_key`` set), where
    each container already has its own ``DEFAULT_MODEL_ID`` env var.
    """

    log_emoji: str = "🤖"
    """Single-character glyph prefixed to the start-of-run log line.
    Cosmetic only — drop or change without breaking anything.
    """


def resolve_remote_maskrcnn_url(branch: 'RemoteMaskRCNNBranch'):
    """
    Resolve which remote-MaskRCNN URL this branch should hit.

    Precedence:

    1. ``settings.<branch.settings_key>`` (the legacy per-family URL,
       e.g. ``settings.MASKRCNN_HYPOLITH_API_URL``). If set, this wins
       — the operator has explicitly pinned this family to a dedicated
       container instance, so honour it. The helper does NOT inject
       a default model_id on this path because the per-family
       container already runs with its own ``DEFAULT_MODEL_ID`` env
       var; injecting another one would override the operator's
       choice.

    2. ``settings.MASKRCNN_API_URL`` (the unified URL, fronting one
       container that exposes the full registry). If set and the
       per-family URL is unset, route there. The helper will inject
       ``branch.default_model_id`` into the request payload when the
       caller did not pass an explicit ``model_id``, so the unified
       container picks the right checkpoint for this family.

    3. Neither set — return ``(None, None)``. The caller surfaces a
       graceful ``not_configured`` envelope.

    This precedence is intentional. It lets an operator roll the
    unified container out one family at a time: drop the per-family
    URL, set the unified URL globally, and the family migrates with
    no other code change. Setting both is also fine — the per-family
    URL takes precedence so a stuck rollback is one env-var edit.

    Returns:
        (url_or_none, model_id_default_or_none)

        ``url_or_none`` is the resolved remote URL (or None).
        ``model_id_default_or_none`` is the family default checkpoint
        id to inject when the caller didn't pass one — only non-None
        on the unified path; always None on the per-family path.
    """
    from django.conf import settings as _settings

    per_family = getattr(_settings, branch.settings_key, None)
    if per_family and per_family.strip():
        return per_family, None

    unified = getattr(_settings, 'MASKRCNN_API_URL', None)
    if unified and unified.strip():
        return unified, branch.default_model_id

    return None, None


def run_remote_maskrcnn_branch(
    branch: RemoteMaskRCNNBranch,
    *,
    image,
    location,
    model_id,
    score_threshold,
    max_detections,
    scripts_dir,  # noqa: ARG001 - accepted for signature parity with
                  # the other analyzer branches; the remote MaskRCNN
                  # path doesn't read from the local scripts dir.
):
    """
    Execute one remote-MaskRCNN analyze-viewport request.

    Wraps the same end-to-end behaviour that ``maskrcnn_rocks.py`` and
    ``maskrcnn_house.py`` implement inline: validate config, render
    the viewport image to JPEG, POST it to the remote service, decode
    the prediction payload, save artefacts (query image, annotated
    visualization, GeoJSON, metadata.json), and return a JSON
    response shaped like the other analyzer branches.

    Caller is one of the per-service branches under
    ``analyzers/maskrcnn_*.py``; see ``RemoteMaskRCNNBranch`` for the
    fields each caller customises.
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

        from ._helpers import (
            _create_grounding_dino_visualization,
            _polygons_norm_to_geojson,
            _unavailable_response,
        )

        # Resolve the remote URL through the unified-aware helper so
        # operators can flip MASKRCNN_API_URL on as the consolidation
        # rollout progresses without touching code. ``unified_model_id``
        # is non-None only when we routed to the unified URL; in that
        # case we inject it as the form-data ``model_id`` so the
        # unified container picks this family's default checkpoint
        # (rather than the unified container's global default, which
        # would otherwise apply across all families).
        api_url, unified_model_id = resolve_remote_maskrcnn_url(branch)
        if not api_url:
            return _unavailable_response(
                image=image,
                location=location,
                model_type=branch.model_type,
                reason='not_configured',
                message=f'{branch.display_label} API is not configured',
                suggestion=(
                    f'Set {branch.settings_key} '
                    f'(e.g. {branch.suggested_default_url}) or set '
                    f'MASKRCNN_API_URL to a unified maskrcnn container '
                    f'in the web container environment.'
                ),
            )

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        lat_str = (
            f"lat{location.get('lat', 0):.6f}"
            .replace('.', 'p').replace('-', 'n')
        )
        lon_str = (
            f"lon{location.get('lon', 0):.6f}"
            .replace('.', 'p').replace('-', 'n')
        )
        alt_str = f"alt{int(location.get('alt', 0))}m"

        results_root = Path('/app/deepgis_results') / branch.results_subdir
        results_root.mkdir(parents=True, exist_ok=True)

        folder_name = (
            f"{branch.folder_prefix}_{timestamp}_"
            f"{lat_str}_{lon_str}_{alt_str}"
        )
        session_dir = results_root / folder_name
        session_dir.mkdir(exist_ok=True)
        session_id = folder_name

        query_image_path = session_dir / 'query_image.png'
        image.save(query_image_path, format='PNG')

        print(
            f"{branch.log_emoji} Running {branch.display_label} detection..."
        )
        print(f"   API URL:         {api_url}")
        print(f"   Model ID:        {model_id or '(service default)'}")
        print(f"   Score threshold: {score_threshold}")
        print(f"   Max detections:  {max_detections}")

        device_info = {
            'mode': 'remote_api',
            'api_url': api_url,
            'device': 'remote_gpu',
        }

        # Same JPEG serialisation strategy as the existing rocks/house
        # branches: keep RGB, flatten alpha onto white, JPEG q=95.
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
        # Caller's explicit model_id wins; otherwise, on the unified
        # path, fall back to the family default declared on the
        # RemoteMaskRCNNBranch. On the legacy per-family path
        # (unified_model_id is None) we inject nothing — the per-family
        # container's ``DEFAULT_MODEL_ID`` env var already encodes the
        # right choice.
        effective_model_id = model_id or unified_model_id
        if effective_model_id:
            form_data['model_id'] = effective_model_id

        try:
            response = requests.post(
                f"{api_url.rstrip('/')}/api/predict",
                files={'file': ('viewport.jpg', img_buffer, 'image/jpeg')},
                data=form_data,
                timeout=180,
            )
        except requests.exceptions.ConnectionError as e:
            print(
                f"⚠ {branch.display_label}: cannot connect to {api_url} "
                f"({e}); degrading gracefully"
            )
            return _unavailable_response(
                image=image,
                location=location,
                model_type=branch.model_type,
                reason='connection_error',
                message=(
                    f'Cannot connect to {branch.display_label} API at '
                    f'{api_url}'
                ),
                api_url=api_url,
                suggestion=(
                    f'Ensure the {branch.container_name} container is '
                    f'running on the GPU host'
                ),
                detail=str(e),
            )
        except requests.exceptions.Timeout:
            print(
                f"⚠ {branch.display_label}: request to {api_url} timed out; "
                f"degrading gracefully"
            )
            return _unavailable_response(
                image=image,
                location=location,
                model_type=branch.model_type,
                reason='timeout',
                message=f'{branch.display_label} API request timed out',
                api_url=api_url,
                suggestion=(
                    'The image may be too large or the model is still '
                    'warming up'
                ),
                retry_after=60,
            )
        except Exception as e:
            import traceback
            return JsonResponse({
                'status': 'error',
                'message': (
                    f'{branch.display_label} API request failed: {e}'
                ),
                'traceback': traceback.format_exc(),
                'api_url': api_url,
            }, status=500)

        if response.status_code != 200:
            error_detail = ''
            try:
                error_detail = (
                    response.json().get('error', '') or response.text[:500]
                )
            except Exception:
                error_detail = (
                    response.text[:500]
                    if response.text else 'No error details'
                )
            print(f"❌ API returned {response.status_code}: {error_detail}")
            return JsonResponse({
                'status': 'error',
                'message': (
                    f'{branch.display_label} API error: '
                    f'HTTP {response.status_code}'
                ),
                'detail': error_detail,
                'api_url': api_url,
                'suggestion': (
                    f'Check container logs: '
                    f'docker logs {branch.container_name}'
                ),
            }, status=502)

        api_result = response.json()
        if not api_result.get('success', False):
            err = api_result.get('error', 'Unknown error from API')
            return JsonResponse({
                'status': 'error',
                'message': f'{branch.display_label} API error: {err}',
                'api_url': api_url,
            }, status=500)

        predictions = api_result.get('predictions', {}) or {}
        num_detections = int(predictions.get('count', 0) or 0)
        print(
            f"✓ Found {num_detections} {branch.fallback_label} "
            f"detections via remote API"
        )

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
            label = (
                api_labels[i]
                if i < len(api_labels)
                else branch.fallback_label
            )
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
                'has_mask': has_polygons,
            })

        if num_detections > 0:
            print(
                f"  ↳ {masks_with_polygons}/{num_detections} masks have "
                f"vector contours; "
                f"{num_detections - masks_with_polygons} will fall back "
                f"to bounding boxes"
            )

        visualization_path = None
        annotated = api_result.get('annotated_image')
        if annotated:
            try:
                if ',' in annotated:
                    annotated = annotated.split(',', 1)[1]
                annotated_bytes = base64.b64decode(annotated)
                vis_img = Image.open(io.BytesIO(annotated_bytes))
                visualization_path = (
                    session_dir / 'detection_visualization.jpg'
                )
                vis_img.save(visualization_path, quality=95)
            except Exception as viz_err:
                print(
                    f"Warning: could not save annotated image from API: "
                    f"{viz_err}"
                )

        if visualization_path is None and num_detections > 0:
            try:
                visualization_path = _create_grounding_dino_visualization(
                    image, detections_data, session_dir
                )
            except Exception as viz_err:
                print(
                    f"Warning: could not render local visualization: "
                    f"{viz_err}"
                )

        geojson = _polygons_norm_to_geojson(
            detections_data, img_width, img_height
        )

        geojson_path = session_dir / 'detections.geojson'
        with open(geojson_path, 'w') as f:
            json.dump(geojson, f, indent=2)

        metadata = {
            'timestamp': timestamp,
            'location': location,
            'model_type': branch.model_type,
            'model_id_requested': model_id or None,
            'model_used': (
                api_result.get('model') or api_result.get('model_id')
            ),
            'score_threshold': score_threshold,
            'max_detections': max_detections,
            'image_size': [img_width, img_height],
            'num_detections': num_detections,
            'inference_ms': api_result.get('inference_ms'),
            'device_info': device_info,
            'session_dir': str(
                session_dir.relative_to('/app/deepgis_results')
            ),
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
            'model_type': branch.model_type,
            'model_id': api_result.get('model_id'),
            'inference_ms': api_result.get('inference_ms'),
            'device_info': device_info,
            'saved_to': {
                'session_dir': str(
                    session_dir.relative_to('/app/deepgis_results')
                ),
                'query_image': str(
                    query_image_path.relative_to('/app/deepgis_results')
                ),
                'visualization': (
                    str(
                        visualization_path.relative_to('/app/deepgis_results')
                    )
                    if visualization_path else None
                ),
                'geojson': str(
                    geojson_path.relative_to('/app/deepgis_results')
                ),
                'metadata': str(
                    metadata_path.relative_to('/app/deepgis_results')
                ),
                'host_path': str(session_dir).replace(
                    '/app/deepgis_results', './deepgis_results'
                ),
            },
            'report_url': f'/label/ai-analysis/report/{session_id}/',
        })

    except Exception as e:
        import traceback
        error_traceback = traceback.format_exc()
        print(f"\n❌ {branch.display_label} Analysis Error:")
        print(f"Error message: {e}")
        print(f"Traceback:\n{error_traceback}")
        return JsonResponse({
            'status': 'error',
            'message': str(e),
            'traceback': error_traceback,
        }, status=500)
