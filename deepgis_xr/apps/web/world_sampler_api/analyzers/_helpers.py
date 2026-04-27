"""
Shared helpers for the text-prompted analyzer branches.

Used only by `grounding_dino.py` and `grounded_sam.py`; kept in a
private module to avoid duplicating ~200 lines of OpenCV / Shapely /
Matplotlib plumbing between them. Each helper is pure (no Django
request plumbing, no global state) and therefore straightforward to
test in isolation once the ABC lands.

Helpers:

    _create_grounding_dino_visualization(image, detections, session_dir)
        Render the detections over `image` as a Matplotlib PNG,
        save it into `session_dir`, return its filesystem path.

    _detections_to_geojson(detections, image_width, image_height)
        Convert Grounding-DINO bounding boxes to GeoJSON in
        image-space. Callers project to geographic coordinates
        downstream.

    _masks_to_geojson_with_contours(detections, image_width, image_height)
        Convert per-instance binary masks to GeoJSON Polygon
        features via cv2.findContours. Used by grounded_sam.

    _polygons_norm_to_geojson(detections, image_width, image_height)
        Build GeoJSON polygons from pre-vectorized, normalized mask
        contours (`mask_polygons_norm`). Used by maskrcnn_rocks, where
        the upstream service already runs cv2.findContours on the GPU
        host and ships ring lists in [0, 1] image space.

    _unavailable_response(image, location, model_type, reason, ...)
        Graceful-degradation envelope returned when a remote AI
        service is missing/unreachable/overloaded. See its docstring
        for the full rationale; in short, this returns HTTP 200 with
        the same shape as a successful empty response so frontend
        code that checks `response.ok` and `result.status ===
        'success'` continues to render (as "0 detections") instead of
        throwing an error toast on every viewport change. Callers
        that want to surface an "AI offline" badge can read
        `result.degraded === true` and `result.unavailable_reason`.
"""


from django.http import JsonResponse


def _unavailable_response(
    *,
    image,
    location,
    model_type,
    reason,
    message,
    api_url=None,
    suggestion=None,
    detail=None,
    retry_after=30,
):
    """
    Build a graceful-degradation envelope for analyze-viewport.

    The original behaviour was to return ``status=503`` with
    ``{"status": "error", "message": "..."}`` whenever the remote AI
    host (e.g. ``192.168.0.232:5002``) was unreachable, the env URL
    was unset, or a request timed out. Because the frontend
    (``staticfiles/web/js/world-sampler-ui.js``) hits this endpoint
    on every viewport change, that turned a transient network blip
    or a one-off un-configured deployment into an error toast on
    every map drag — and worse, it was indistinguishable from an
    actual model crash.

    Returning an *empty success* response with a ``degraded`` flag
    instead has three properties we want:

    1. **All current call sites keep working without UI changes.**
       The two strict callers in ``world-sampler-ui.js`` check
       ``response.ok && result.status === 'success'``; both pass.
       The one already-graceful caller (SceneGraph kernel
       orchestration) treats an empty result the same as a successful
       run with no detections, so the kernel just contributes nothing
       to the fused graph that round.

    2. **AI-offline UX becomes opt-in, not forced.** Frontend code
       that *wants* to render a "remote AI unreachable" badge can
       branch on ``result.degraded`` / ``result.unavailable_reason``;
       legacy code paths see a normal empty response.

    3. **Operators still see what happened.** The server log line
       printed by the analyzer (``Cannot connect to ... at ...``) is
       unchanged, and the response body still carries the underlying
       reason, suggestion, and api_url for debugging.

    Reserved for the *unavailability* failure modes only:

    * ``not_configured``    — settings env var is unset/blank
    * ``connection_error``  — TCP refused / host unreachable
    * ``timeout``           — request exceeded its deadline

    Genuine upstream failures — HTTP 5xx from a reachable service,
    unhandled exceptions inside the analyzer — should still surface
    as a hard error so they don't get masked. Those paths
    deliberately keep their original 5xx + ``status="error"``
    response.

    Args:
        image:        PIL image (or ``None``); used only to fill
                      ``image_size`` so frontend layout code that
                      reads it doesn't divide by zero.
        location:     The ``{lat, lon, alt}`` dict echoed back to the
                      caller; pass through whatever was in the
                      request.
        model_type:   The ``model_type`` the request asked for, e.g.
                      ``'maskrcnn_rocks'`` or ``'grounding_dino'``.
        reason:       One of ``'not_configured' | 'connection_error'
                      | 'timeout'``.
        message:      Human-readable summary for logs / debug
                      surfaces; preserved from the original 5xx
                      message for continuity.
        api_url:      Optional remote URL the request was aimed at;
                      surfaced in ``device_info.api_url`` for debug.
        suggestion:   Optional operator-facing hint (e.g. "Ensure
                      the maskrcnn-rocks-api container is running on
                      the GPU host"). Echoed verbatim.
        detail:       Optional underlying error string (e.g. the
                      ``ConnectionError`` repr); preserved so logs
                      stay diagnosable.
        retry_after:  Seconds advertised in the ``Retry-After``
                      header for HTTP-aware clients. The default of
                      30s matches typical Cesium tile-load cadence.

    Returns:
        ``JsonResponse`` with status code 200 and a ``Retry-After``
        header.
    """

    img_w = getattr(image, 'width', 0) if image is not None else 0
    img_h = getattr(image, 'height', 0) if image is not None else 0

    payload = {
        'status': 'success',
        'degraded': True,
        'unavailable_reason': reason,
        'message': message,
        'num_detections': 0,
        'detections': [],
        'geojson': {'type': 'FeatureCollection', 'features': []},
        'location': location or {},
        'image_size': [img_w, img_h],
        'model_type': model_type,
        'device_info': {
            'mode': 'remote_api',
            'api_url': api_url,
            'device': 'remote_gpu',
            'available': False,
            'unavailable_reason': reason,
        },
    }
    if suggestion:
        payload['suggestion'] = suggestion
    if detail:
        payload['detail'] = detail

    response = JsonResponse(payload)
    response['Retry-After'] = str(int(retry_after))
    return response


def _create_grounding_dino_visualization(image, detections_data, session_dir):
    """Create a visualization with bounding boxes and labels."""
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
        (255, 87, 51), (51, 255, 87), (51, 87, 255), (255, 255, 51),
        (255, 51, 255), (51, 255, 255), (255, 128, 0), (128, 0, 255)
    ]
    
    for i, det in enumerate(detections_data):
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
    return visualization_path



def _detections_to_geojson(detections_data, image_width, image_height):
    """Convert detections to GeoJSON format with normalized coordinates."""
    features = []
    
    for det in detections_data:
        bbox = det['bbox']
        # Normalize coordinates to 0-1 range
        x1, y1, x2, y2 = bbox
        norm_x1 = x1 / image_width
        norm_y1 = y1 / image_height
        norm_x2 = x2 / image_width
        norm_y2 = y2 / image_height
        
        # Create polygon from bounding box
        coordinates = [[
            [norm_x1, norm_y1],
            [norm_x2, norm_y1],
            [norm_x2, norm_y2],
            [norm_x1, norm_y2],
            [norm_x1, norm_y1]  # Close the polygon
        ]]
        
        properties = {
            "detection_id": det['detection_id'],
            "class_name": det['class_name'],
            "category": det['class_name'],  # Frontend compatibility: used by displayZeroShotResults
            "confidence": det['confidence'],
            "class_id": det['detection_id'],  # Frontend compatibility: used by displayZeroShotResults
            "bbox_pixels": bbox
        }
        for optional_key in ('area', 'mask_rle', 'has_mask'):
            if optional_key in det:
                properties[optional_key] = det[optional_key]

        feature = {
            "type": "Feature",
            "geometry": {
                "type": "Polygon",
                "coordinates": coordinates
            },
            "properties": properties
        }
        features.append(feature)
    
    return {
        "type": "FeatureCollection",
        "features": features
    }


def _polygons_norm_to_geojson(detections_data, image_width, image_height):
    """
    Build a normalized GeoJSON FeatureCollection from detections that
    carry pre-vectorized mask contours.

    Each detection may include `mask_polygons_norm`, a list of rings,
    where each ring is `[[x_norm, y_norm], ...]` already in [0, 1]
    image space (the convention used by the maskrcnn-rocks service).
    Rings are conventionally ordered largest-area first; we treat
    rings[0] as the polygon exterior and the remainder as holes — the
    same shape `displayZeroShotResults` on the frontend already
    expects (`coordinates: [exterior, hole1, hole2, ...]`).

    When a detection has no usable polygons we fall back to its
    bounding box so the feature still renders. `has_mask` reflects
    whether the geometry is mask-derived (used by the frontend to
    upgrade outline / label styling).

    Args:
        detections_data: list of detection dicts with at minimum
            `detection_id`, `class_name`, `confidence`, `bbox`, and
            optionally `mask_polygons_norm` and `area`.
        image_width / image_height: pixel dims; used only for the
            bbox fallback (existing inputs are already normalized).

    Returns:
        dict — GeoJSON FeatureCollection.
    """
    features = []

    for det in detections_data:
        rings = det.get('mask_polygons_norm') or []
        usable_rings = []
        for ring in rings:
            if not ring or len(ring) < 4:
                # Need at least 3 distinct points + closure point.
                continue
            cleaned = [[float(x), float(y)] for x, y in ring]
            if cleaned[0] != cleaned[-1]:
                cleaned.append(cleaned[0])
            usable_rings.append(cleaned)

        if usable_rings:
            coordinates = usable_rings  # [exterior, hole1, hole2, ...]
            has_mask = True
        else:
            bbox = det.get('bbox') or [0.0, 0.0, image_width, image_height]
            x1, y1, x2, y2 = bbox
            coordinates = [[
                [x1 / image_width, y1 / image_height],
                [x2 / image_width, y1 / image_height],
                [x2 / image_width, y2 / image_height],
                [x1 / image_width, y2 / image_height],
                [x1 / image_width, y1 / image_height],
            ]]
            has_mask = False

        properties = {
            'detection_id': det.get('detection_id'),
            'class_name': det.get('class_name'),
            'category': det.get('class_name'),
            'confidence': det.get('confidence'),
            'class_id': det.get('detection_id'),
            'bbox_pixels': det.get('bbox', []),
            'has_mask': has_mask,
        }
        if det.get('area') is not None:
            properties['area'] = det['area']

        features.append({
            'type': 'Feature',
            'geometry': {
                'type': 'Polygon',
                'coordinates': coordinates,
            },
            'properties': properties,
        })

    return {
        'type': 'FeatureCollection',
        'features': features,
    }


def _masks_to_geojson_with_contours(detections_data, image_width, image_height):
    """
    Convert Grounded-SAM-2 detections with GeoJSON segmentation masks to normalized GeoJSON.
    
    The API returns masks already in GeoJSON MultiPolygon format with pixel coordinates.
    This function normalizes those coordinates to 0-1 range for geographic mapping.
    
    Args:
        detections_data: List of detections, each with 'mask_geojson', 'class_name', 'confidence', etc.
        image_width: Image width in pixels
        image_height: Image height in pixels
    
    Returns:
        GeoJSON FeatureCollection with normalized polygon features
    """
    features = []
    
    for det in detections_data:
        has_mask = False
        
        # Check if detection has a GeoJSON segmentation mask from API
        if 'mask_geojson' in det and det['mask_geojson'] is not None:
            mask_geojson = det['mask_geojson']
            
            # API returns GeoJSON MultiPolygon: { "type": "MultiPolygon", "coordinates": [...] }
            if mask_geojson.get('type') == 'MultiPolygon':
                mp_coordinates = mask_geojson.get('coordinates', [])
                
                if len(mp_coordinates) > 0:
                    # MultiPolygon structure: [ polygon1, polygon2, ... ]
                    # Each polygon: [ exterior_ring, hole1, hole2, ... ]
                    # Each ring: [ [x,y], [x,y], ... ]
                    
                    # Take the first polygon (usually the main segmentation region)
                    first_polygon = mp_coordinates[0]
                    
                    # Normalize all rings in this polygon
                    normalized_polygon = []
                    for ring in first_polygon:
                        norm_ring = []
                        for x, y in ring:
                            norm_x = float(x) / image_width
                            norm_y = float(y) / image_height
                            norm_ring.append([norm_x, norm_y])
                        
                        # Ensure ring is closed (first point = last point)
                        if len(norm_ring) > 0 and norm_ring[0] != norm_ring[-1]:
                            norm_ring.append(norm_ring[0])
                        
                        normalized_polygon.append(norm_ring)
                    
                    # Convert to Polygon format: [ [exterior_ring], [hole1], [hole2], ... ]
                    if len(normalized_polygon) > 0:
                        coordinates = normalized_polygon  # Preserve ring structure
                        has_mask = True
        
        # Fallback to bounding box if no mask available
        if not has_mask:
            bbox = det.get('bbox', [0, 0, image_width, image_height])
            x1, y1, x2, y2 = bbox
            # Create closed rectangle polygon (first point = last point)
            coordinates = [[
                [x1/image_width, y1/image_height],
                [x2/image_width, y1/image_height],
                [x2/image_width, y2/image_height],
                [x1/image_width, y2/image_height],
                [x1/image_width, y1/image_height]  # Close the ring
            ]]
        
        # Create GeoJSON feature
        feature = {
            "type": "Feature",
            "geometry": {
                "type": "Polygon",
                "coordinates": coordinates
            },
            "properties": {
                "detection_id": det['detection_id'],
                "class_name": det['class_name'],
                "category": det['class_name'],  # Frontend compatibility
                "confidence": det['confidence'],
                "class_id": det['detection_id'],  # Frontend compatibility
                "bbox_pixels": det.get('bbox', []),
                "has_mask": has_mask
            }
        }
        features.append(feature)
    
    return {
        "type": "FeatureCollection",
        "features": features
    }
