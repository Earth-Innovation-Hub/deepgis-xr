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
"""


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
