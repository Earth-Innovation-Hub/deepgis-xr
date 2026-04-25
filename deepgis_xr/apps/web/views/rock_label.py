"""
Rock Mask R-CNN labeling views.

Implements two complementary annotation workflows that both feed the same
400×400 .npy training corpus:

  Workflow A — "Correct AI predictions"
      Entry: AI Analysis Report → Edit in 2D
      URL  : /label/rocks/edit/<session_id>/
      The editor loads the saved query_image.png from
      /app/deepgis_results/<model>_results/<session_id>/, overlays any
      detections.geojson / segments.geojson predictions as editable vector
      polygons, and lets the user drag a 400×400 window anywhere on the
      image to capture a tile.

  Workflow B — "Generate new labels on Cesium"
      Entry: label_search.html → HUD "Label Rocks" button
      URL  : /label/rocks/capture/  (POST {lat, lon, alt, image_b64})
             → returns {session_id} → page redirects to the same editor.
      No predictions are pre-loaded; user draws everything from scratch.

Save endpoint (shared):
      /label/rocks/edit/<session_id>/save-tile/  (POST)

On save, each 400×400 tile is rasterized into a single .npy with shape
(400, 400, 3 + N) — the exact on-disk format read by Zhiang's c3.py
training Dataset (`backbone.body.conv1.weight.shape[1] == 3` channel
RGB + N per-instance binary masks at 0/255). Corpus root:

    /app/deepgis_results/rock_corpus/<dataset_id>/

When the dataset crosses ``min_tiles_for_training``, the endpoint flips
``TrainingDataset.status`` to ``'ready'`` and drops a single-line
RETRAIN_READY sentinel file in the corpus directory. A separate trainer
script (run on the GPU host on tesseract) polls for this sentinel and
fine-tunes from the bishop_ntl_rgb_e0049 checkpoint.
"""

from __future__ import annotations

import base64
import io
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import numpy as np
from PIL import Image as PILImage

from django.contrib.auth.decorators import login_required
from django.http import Http404, JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt

from deepgis_xr.apps.core.models import (
    CategoryLabel, CategoryType, Color, Image, ImageLabel, Labeler,
    TrainingDataset, TrainingLabel,
)


log = logging.getLogger(__name__)


# Where AI analysis sessions live on disk.
RESULTS_BASE = Path('/app/deepgis_results')
# Subfolders that ai_reports.py + the analyzers write into. Order
# matters: more-specific prefixes first.
RESULTS_SUBDIRS = (
    'maskrcnn_rocks_results',
    'grounded_sam_results',
    'grounding_dino_results',
    'mask2former_results',
    'yolov8_results',
    'zero_shot_results',
    'sam_results',
    'rock_capture_results',  # capture-only sessions from Workflow B
)
# Where saved tiles + sentinels live.
CORPUS_BASE = RESULTS_BASE / 'rock_corpus'

# Training tile geometry expected by services/maskrcnn-rocks/model.py
# and by Zhiang's c3.py training Dataset.
TILE_SIZE = 400
ROCK_DATASET_KIND = 'rock_maskrcnn'

# Default category palette. The first entry is the fallback when no model
# type could be inferred and the user hasn't picked anything yet. The
# editor surfaces these as "quick chips" before falling back to a
# free-text category name.
DEFAULT_CATEGORIES = [
    'rock', 'building', 'vegetation', 'water', 'road',
    'vehicle', 'sand', 'shadow', 'other',
]

# Per-category colour seeds (R, G, B). Anything not listed gets a stable
# hash-derived hue so unknown categories still come out distinct on the
# canvas.
CATEGORY_PALETTE = {
    'rock':       (245, 158,  11),
    'building':   ( 59, 130, 246),
    'vegetation': ( 34, 197,  94),
    'water':      (  6, 182, 212),
    'road':       (148, 163, 184),
    'vehicle':    (236,  72, 153),
    'sand':       (250, 204,  21),
    'shadow':     ( 71,  85, 105),
    'other':      (168,  85, 247),
    'unknown':    (239,  68,  68),
}


def _infer_model_type(session_id: str, predictions: Optional[dict]) -> str:
    """Return one of: 'sam', 'maskrcnn_rocks', 'mask2former', 'yolov8',
    'grounding_dino', 'grounded_sam', 'rockcapture', 'unknown'.

    SAM is class-agnostic — the editor uses this to force the user
    through a category picker. MaskRCNN ships predictions with a
    category that's editable but pre-filled.
    """
    sid = session_id.lower()
    for prefix in (
        'maskrcnn_rocks', 'grounded_sam', 'grounding_dino',
        'mask2former', 'yolov8', 'zero_shot', 'rockcapture',
    ):
        if sid.startswith(prefix):
            return prefix
    if sid.startswith('sam_'):
        return 'sam'
    # Fall back to inspecting the first feature's `model` property.
    if predictions:
        for feat in predictions.get('features', []) or []:
            mdl = ((feat.get('properties') or {}).get('model') or '').lower()
            if 'segment_anything' in mdl or 'sam' in mdl:
                return 'sam'
            if 'mask_rcnn' in mdl or 'maskrcnn' in mdl:
                return 'maskrcnn_rocks'
            break
    return 'unknown'


def _default_category_for_model(model_type: str) -> str:
    """Return the category to pre-fill new polygons with.

    SAM has no inherent class so we use empty string and the editor
    forces the user to pick one. Other models default to whatever the
    underlying network was trained for.
    """
    if model_type == 'maskrcnn_rocks':
        return 'rock'
    if model_type in ('grounding_dino', 'grounded_sam'):
        return ''  # text-prompted; varies per query
    if model_type in ('rockcapture',):
        return 'rock'
    return ''  # SAM, unknown, etc.


def _category_from_props(props: dict) -> str:
    """Pull the per-feature category off a GeoJSON properties dict.

    Tries the most-specific keys first. SAM returns nothing, hence the
    empty-string fallback (which the editor flags as "needs category").
    """
    if not props:
        return ''
    for key in ('category', 'class_name', 'class', 'label', 'name'):
        v = props.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ''


# ---------------------------------------------------------------------------
# Session lookup helpers (mirrors views/ai_reports.py logic)
# ---------------------------------------------------------------------------

def _find_session_dir(session_id: str) -> Optional[Path]:
    for sub in RESULTS_SUBDIRS:
        candidate = RESULTS_BASE / sub / session_id
        if candidate.exists() and candidate.is_dir():
            return candidate
    return None


def _load_predictions(session_dir: Path) -> Optional[dict]:
    """Return GeoJSON predictions if the session has any, else None."""
    for fname in ('segments.geojson', 'detections.geojson'):
        path = session_dir / fname
        if path.exists():
            try:
                with open(path) as f:
                    return json.load(f)
            except Exception as exc:  # pragma: no cover
                log.warning("Failed to read %s: %s", path, exc)
    return None


def _load_metadata(session_dir: Path) -> dict:
    path = session_dir / 'metadata.json'
    if not path.exists():
        return {}
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Rasterization: polygon list → (H, W, N) uint8 mask stack
# ---------------------------------------------------------------------------

def _rasterize_polygons(
    polygons_xy: List[List[List[float]]],
    width: int,
    height: int,
) -> np.ndarray:
    """Burn each polygon (in pixel coordinates) into its own binary slice.

    ``polygons_xy`` is a list of polygons; each polygon is a list of [x, y]
    vertex pairs. Returns ``np.uint8`` of shape ``(height, width, N)`` with
    values ∈ {0, 255}.

    Uses Pillow ``ImageDraw.polygon`` which is already a hard dependency
    of the web container — no need to pull cv2 in here.
    """
    from PIL import ImageDraw

    if not polygons_xy:
        return np.zeros((height, width, 0), dtype=np.uint8)

    masks = np.zeros((height, width, len(polygons_xy)), dtype=np.uint8)
    for i, poly in enumerate(polygons_xy):
        if len(poly) < 3:
            continue
        flat = [(float(x), float(y)) for x, y in poly]
        layer = PILImage.new('L', (width, height), 0)
        ImageDraw.Draw(layer).polygon(flat, fill=255)
        masks[:, :, i] = np.asarray(layer, dtype=np.uint8)
    return masks


def _crop_image_array(
    arr: np.ndarray,
    x: int, y: int, w: int, h: int,
    image_w: int, image_h: int,
) -> np.ndarray:
    """Crop a (H, W, ...) array to the requested rect; pad with zeros if
    the rect runs past the image edge so the output is always exactly
    (h, w, ...). Lets the user drop a tile box on a corner of the image
    without having to clamp it themselves."""
    out_shape = (h, w) + arr.shape[2:]
    out = np.zeros(out_shape, dtype=arr.dtype)

    src_x0 = max(0, x)
    src_y0 = max(0, y)
    src_x1 = min(image_w, x + w)
    src_y1 = min(image_h, y + h)
    if src_x1 <= src_x0 or src_y1 <= src_y0:
        return out

    dst_x0 = src_x0 - x
    dst_y0 = src_y0 - y
    dst_x1 = dst_x0 + (src_x1 - src_x0)
    dst_y1 = dst_y0 + (src_y1 - src_y0)
    out[dst_y0:dst_y1, dst_x0:dst_x1] = arr[src_y0:src_y1, src_x0:src_x1]
    return out


# ---------------------------------------------------------------------------
# Page renderer (Workflow A entry)
# ---------------------------------------------------------------------------

def rock_label_edit(request, session_id: str):
    """Render the canvas editor for a given AI/capture session."""
    session_dir = _find_session_dir(session_id)
    if session_dir is None:
        raise Http404(f"Analysis session not found: {session_id}")

    query_image_path = session_dir / 'query_image.png'
    if not query_image_path.exists():
        raise Http404(f"query_image.png missing for session {session_id}")

    with PILImage.open(query_image_path) as img:
        image_width, image_height = img.size

    metadata = _load_metadata(session_dir)
    predictions = _load_predictions(session_dir)
    model_type = _infer_model_type(session_id, predictions)
    default_category = _default_category_for_model(model_type)

    # Pre-compute predictions as a flat list of {points, category}
    # objects in image-pixel coordinates so the JS doesn't have to know
    # about GeoJSON quirks (Polygon vs MultiPolygon, normalized vs pixel,
    # SAM's missing class_name, etc.).
    #
    # The maskrcnn_rocks analyser (via _polygons_norm_to_geojson) writes
    # coordinates normalized to [0, 1] of the source image. SAM and most
    # other branches do the same. If max abs value is <= 1.5 we treat
    # the ring as normalized and scale by (W, H); otherwise we assume
    # the ring is already in pixel space (older sessions sometimes were).
    initial_polygons = []
    if predictions and predictions.get('features'):
        for feat in predictions['features']:
            geom = feat.get('geometry') or {}
            gtype = geom.get('type')
            coords = geom.get('coordinates') or []
            if gtype == 'Polygon':
                rings = coords
            elif gtype == 'MultiPolygon':
                rings = [r for poly in coords for r in poly]
            else:
                continue
            cat_from_props = _category_from_props(feat.get('properties') or {})
            poly_category = cat_from_props or default_category
            for ring in rings:
                xy = [[float(c[0]), float(c[1])] for c in ring if len(c) >= 2]
                if len(xy) < 3:
                    continue
                max_abs = max(max(abs(p[0]), abs(p[1])) for p in xy)
                if max_abs <= 1.5:
                    xy = [[p[0] * image_width, p[1] * image_height] for p in xy]
                initial_polygons.append({
                    'points': xy,
                    'category': poly_category,
                })

    # Derive a default dataset name from the session timestamp / location
    # so the user has something to accept without typing.
    location = metadata.get('location') or {}
    default_dataset_name = "Bishop rocks corpus"
    if location.get('lat') is not None and location.get('lon') is not None:
        default_dataset_name = (
            f"Rocks @ {location['lat']:.4f},{location['lon']:.4f}"
        )

    # Categories the editor offers as quick chips: defaults first, then
    # any other categories already in the database (likely from a prior
    # editing session) appended uniquely. Free-text names still work.
    extra_cats = list(
        CategoryType.objects
        .exclude(category_name__in=DEFAULT_CATEGORIES)
        .order_by('category_name')
        .values_list('category_name', flat=True)[:20]
    )
    category_chips = DEFAULT_CATEGORIES + extra_cats

    context = {
        'session_id': session_id,
        'image_url': f'/label/ai-analysis/image/{session_id}/query/',
        'image_width': image_width,
        'image_height': image_height,
        'tile_size': TILE_SIZE,
        'has_predictions': bool(initial_polygons),
        'initial_polygons_json': json.dumps(initial_polygons),
        'metadata': metadata,
        'metadata_json': json.dumps(metadata),
        'default_dataset_name': default_dataset_name,
        'model_type': model_type,
        'default_category': default_category,
        'category_chips_json': json.dumps(category_chips),
        'category_palette_json': json.dumps({
            name: list(rgb) for name, rgb in CATEGORY_PALETTE.items()
        }),
    }
    return render(request, 'web/rock_label_edit.html', context)


# ---------------------------------------------------------------------------
# Capture endpoint (Workflow B entry — Cesium → editor)
# ---------------------------------------------------------------------------

@csrf_exempt
def rock_label_capture(request):
    """Receive a Cesium viewport screenshot and create a fresh session.

    POST JSON: {image_b64, lat, lon, alt, heading?, pitch?}
    Returns:   {session_id}

    The frontend then redirects the user to /label/rocks/edit/<session_id>/.
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)
    try:
        payload = json.loads(request.body)
    except Exception as exc:
        return JsonResponse({'error': f'bad JSON: {exc}'}, status=400)

    image_b64 = payload.get('image_b64') or ''
    if image_b64.startswith('data:'):
        image_b64 = image_b64.split(',', 1)[-1]
    if not image_b64:
        return JsonResponse({'error': 'image_b64 required'}, status=400)

    try:
        png_bytes = base64.b64decode(image_b64)
        pil = PILImage.open(io.BytesIO(png_bytes)).convert('RGB')
    except Exception as exc:
        return JsonResponse({'error': f'cannot decode image: {exc}'}, status=400)

    timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
    lat = payload.get('lat')
    lon = payload.get('lon')
    alt = payload.get('alt')

    def _coord_token(v):
        if v is None:
            return 'na'
        s = f"{v:.6f}".replace('-', 'n').replace('.', 'p')
        return s

    session_id = (
        f"rockcapture_{timestamp}"
        f"_lat{_coord_token(lat)}_lon{_coord_token(lon)}_alt{_coord_token(alt)}"
    )

    session_dir = RESULTS_BASE / 'rock_capture_results' / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    pil.save(session_dir / 'query_image.png', 'PNG')

    metadata = {
        'session_id': session_id,
        'timestamp': timestamp,
        'image_size': [pil.size[0], pil.size[1]],
        'image_width': pil.size[0],
        'image_height': pil.size[1],
        'location': {
            'lat': lat, 'lon': lon, 'alt': alt,
            'heading': payload.get('heading'), 'pitch': payload.get('pitch'),
        },
        'source': 'cesium_label_capture',
    }
    with open(session_dir / 'metadata.json', 'w') as f:
        json.dump(metadata, f, indent=2)

    return JsonResponse({
        'success': True,
        'session_id': session_id,
        'edit_url': f'/label/rocks/edit/{session_id}/',
    })


# ---------------------------------------------------------------------------
# Tile save (the only write path for both workflows)
# ---------------------------------------------------------------------------

def _get_or_create_dataset(user, name: str, min_tiles: int) -> TrainingDataset:
    """Return the user's rock dataset matching ``name``, creating it
    in 'draft' state if missing. Two users can't share a name (the model
    enforces ``unique=True`` on ``name``), so we suffix when needed."""
    candidate = name
    suffix = 1
    while TrainingDataset.objects.filter(name=candidate).exclude(created_by=user).exists():
        suffix += 1
        candidate = f"{name} #{suffix}"

    dataset, _ = TrainingDataset.objects.get_or_create(
        name=candidate,
        created_by=user,
        defaults={
            'kind': ROCK_DATASET_KIND,
            'min_tiles_for_training': min_tiles,
            'description': 'Rock Mask R-CNN training tiles (400×400, RGB + N masks).',
        },
    )
    # If the dataset already existed but for a different kind, refuse —
    # the caller picked the wrong dataset.
    if dataset.kind != ROCK_DATASET_KIND:
        raise ValueError(
            f"Dataset {dataset.name!r} exists with kind={dataset.kind!r}; "
            f"refusing to mix rock tiles into it."
        )
    return dataset


def _stable_rgb_for_category(name: str) -> tuple[int, int, int]:
    """Return a deterministic RGB triple for a category name, falling
    back to a hash-based hue when the name isn't in CATEGORY_PALETTE."""
    if name in CATEGORY_PALETTE:
        return CATEGORY_PALETTE[name]
    import hashlib
    import colorsys
    h = int(hashlib.md5(name.encode('utf-8')).hexdigest()[:8], 16) / 0xFFFFFFFF
    r, g, b = colorsys.hsv_to_rgb(h, 0.65, 0.92)
    return int(r * 255), int(g * 255), int(b * 255)


def _get_or_create_category(name: str) -> CategoryType:
    """Look up or create a CategoryType for ``name``. Used to be hardcoded
    to 'rock' — now we honour whatever the user picked per polygon."""
    name = (name or 'unknown').strip() or 'unknown'
    cat = CategoryType.objects.filter(category_name=name).first()
    if cat:
        return cat
    r, g, b = _stable_rgb_for_category(name)
    color, _ = Color.objects.get_or_create(red=r, green=g, blue=b)
    return CategoryType.objects.create(
        category_name=name, color=color, label_type='P'
    )


def _maybe_drop_sentinel(dataset: TrainingDataset, corpus_dir: Path) -> bool:
    """Flip status to 'ready' and drop a sentinel once the threshold is met.

    Returns True if the sentinel was newly created in this call.
    """
    if dataset.status != 'draft':
        return False
    if dataset.num_annotations < dataset.min_tiles_for_training:
        return False

    sentinel = corpus_dir / 'RETRAIN_READY'
    fresh = not sentinel.exists()
    if fresh:
        sentinel.write_text(
            f"dataset_id={dataset.id}\n"
            f"name={dataset.name}\n"
            f"num_tiles={dataset.num_annotations}\n"
            f"min_tiles_for_training={dataset.min_tiles_for_training}\n"
            f"created_at={datetime.utcnow().isoformat()}Z\n"
        )
    dataset.status = 'ready'
    dataset.save(update_fields=['status', 'updated_at'])
    return fresh


@csrf_exempt
def rock_label_save_tile(request, session_id: str):
    """Persist one 400×400 tile of labels into the training corpus.

    POST JSON:
        tile:           {x, y, w, h}      pixel rect on the source image
        polygons:       [[[x,y], ...], ...]  in pixel coordinates of the source
        dataset_name:   str               (creates if missing)
        dataset_id:     int (optional)    (used in preference to dataset_name)
        min_tiles:      int (optional)    (only honored when creating)
        corrections:    dict (optional)   metadata about the editor session

    Response:
        {success, tile_path, image_label_id, training_label_id,
         dataset: {id, name, num_annotations, status},
         retrain_sentinel_dropped: bool}
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'login required'}, status=401)

    session_dir = _find_session_dir(session_id)
    if session_dir is None:
        return JsonResponse({'error': f'session not found: {session_id}'}, status=404)
    query_image_path = session_dir / 'query_image.png'
    if not query_image_path.exists():
        return JsonResponse({'error': 'query_image.png missing'}, status=404)

    try:
        data = json.loads(request.body)
    except Exception as exc:
        return JsonResponse({'error': f'bad JSON: {exc}'}, status=400)

    tile = data.get('tile') or {}
    try:
        tx = int(round(float(tile['x'])))
        ty = int(round(float(tile['y'])))
        tw = int(round(float(tile.get('w', TILE_SIZE))))
        th = int(round(float(tile.get('h', TILE_SIZE))))
    except (KeyError, TypeError, ValueError) as exc:
        return JsonResponse({'error': f'tile rect required: {exc}'}, status=400)

    polygons_src = data.get('polygons') or []
    if not isinstance(polygons_src, list):
        return JsonResponse({'error': 'polygons must be a list'}, status=400)

    # The editor sends polygons as either:
    #   new : [{points: [[x,y], ...], category: "rock"}, ...]
    #   old : [[[x,y], ...], ...]                        (legacy clients)
    #
    # Translate to tile-local coordinates and drop anything whose
    # centroid sits outside the 400x400 tile box. Categories the user
    # didn't pick fall back to the request-level default category and
    # finally to 'unknown' so we never silently lose a label.
    request_default_cat = (data.get('default_category') or '').strip()
    polys_local: List[List[List[float]]] = []
    cats_local: List[str] = []
    dropped_no_cat = 0
    for entry in polygons_src:
        if isinstance(entry, dict):
            poly = entry.get('points') or []
            poly_cat = (entry.get('category') or '').strip()
        else:
            poly = entry
            poly_cat = ''
        if not isinstance(poly, list) or len(poly) < 3:
            continue
        try:
            xs = [float(p[0]) for p in poly]
            ys = [float(p[1]) for p in poly]
        except (TypeError, ValueError, IndexError):
            continue
        cx = sum(xs) / len(xs)
        cy = sum(ys) / len(ys)
        if not (tx <= cx < tx + tw and ty <= cy < ty + th):
            continue
        cat_name = poly_cat or request_default_cat
        if not cat_name:
            # Caller wanted strict mode. Track and drop.
            dropped_no_cat += 1
            if data.get('strict_categories'):
                continue
            cat_name = 'unknown'
        polys_local.append([[xs[i] - tx, ys[i] - ty] for i in range(len(xs))])
        cats_local.append(cat_name)

    # Read the source image and crop the tile (zero-padded if the
    # rect runs past the edge so we always emit an exact 400×400 .npy).
    with PILImage.open(query_image_path) as img:
        img_w, img_h = img.size
        rgb = np.asarray(img.convert('RGB'), dtype=np.uint8)

    rgb_tile = _crop_image_array(rgb, tx, ty, tw, th, img_w, img_h)
    masks = _rasterize_polygons(polys_local, tw, th)

    if rgb_tile.shape[:2] != (th, tw):
        # Defensive: should never happen.
        return JsonResponse({'error': 'tile crop shape mismatch'}, status=500)

    # Stack RGB (3 ch) + masks (N ch) along the last axis.
    stacked = (
        np.concatenate([rgb_tile, masks], axis=-1)
        if masks.shape[-1] > 0
        else rgb_tile
    )

    # Resolve the dataset (existing-by-id wins over name).
    dataset_id = data.get('dataset_id')
    dataset_name = (data.get('dataset_name') or '').strip()
    min_tiles = int(data.get('min_tiles') or 50)

    try:
        if dataset_id:
            dataset = TrainingDataset.objects.get(
                id=int(dataset_id), created_by=request.user
            )
            if dataset.kind != ROCK_DATASET_KIND:
                return JsonResponse(
                    {'error': f'dataset {dataset_id} is not kind=rock_maskrcnn'},
                    status=400,
                )
        else:
            if not dataset_name:
                return JsonResponse({'error': 'dataset_name or dataset_id required'}, status=400)
            dataset = _get_or_create_dataset(request.user, dataset_name, min_tiles)
    except TrainingDataset.DoesNotExist:
        return JsonResponse({'error': f'dataset {dataset_id} not found'}, status=404)
    except ValueError as exc:
        return JsonResponse({'error': str(exc)}, status=400)

    corpus_dir = CORPUS_BASE / str(dataset.id)
    corpus_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S_%f')
    tile_filename = f"{session_id}__x{tx}_y{ty}_w{tw}_h{th}__{timestamp}.npy"
    tile_path = corpus_dir / tile_filename
    np.save(tile_path, stacked)

    # Persist a sidecar JSON listing the per-channel category in mask-
    # channel order. The .npy stays a plain (H, W, 3+N) RGB+masks tensor
    # so single-class trainers (e.g. Zhiang's c3.py) keep working
    # unchanged; multi-class trainers read the sidecar to look up the
    # class id for each instance channel.
    sidecar_path = tile_path.with_suffix('.categories.json')
    sidecar_payload = {
        'tile': {'x': tx, 'y': ty, 'w': tw, 'h': th},
        'session_id': session_id,
        'image_size': [img_w, img_h],
        'rgb_channels': 3,
        'instance_channels': len(cats_local),
        'categories': cats_local,
        'created_at': datetime.utcnow().isoformat() + 'Z',
    }
    with open(sidecar_path, 'w') as fh:
        json.dump(sidecar_payload, fh, indent=2)

    # Mirror the on-disk tile into the legacy ImageLabel/CategoryLabel
    # plumbing so the existing dataset-detail panels (and Mask2Former
    # pipeline downstream of TrainingLabel) keep working unchanged.
    image, _ = Image.objects.get_or_create(
        name=tile_filename,
        path=str(tile_path),
        defaults={
            'description': f'Rock training tile from session {session_id}',
            'source_id': _ensure_image_source_id(),
            'width': tw,
            'height': th,
        },
    )

    # Group polygons by category so the legacy CategoryLabel rows still
    # reflect the multi-class breakdown the user selected on the canvas.
    by_category: dict[str, list[list[list[float]]]] = {}
    for poly, cat_name in zip(polys_local, cats_local):
        by_category.setdefault(cat_name, []).append(poly)

    for cat_name in by_category:
        image.categories.add(_get_or_create_category(cat_name))

    # Encode the polygons as a GeoJSON FeatureCollection in TILE-LOCAL
    # pixel coordinates so the same record can later regenerate the .npy.
    feature_collection = {
        'type': 'FeatureCollection',
        'features': [
            {
                'type': 'Feature',
                'properties': {'category': cat},
                'geometry': {
                    'type': 'Polygon',
                    'coordinates': [poly + [poly[0]]],  # closed ring
                },
            }
            for poly, cat in zip(polys_local, cats_local)
        ],
    }
    labeler, _ = Labeler.objects.get_or_create(user=request.user)
    image_label = ImageLabel.objects.create(
        image=image,
        combined_label_shapes=json.dumps(feature_collection),
        labeler=labeler,
    )
    for cat_name, polys in by_category.items():
        cat = _get_or_create_category(cat_name)
        per_cat_collection = {
            'type': 'FeatureCollection',
            'features': [
                {
                    'type': 'Feature',
                    'properties': {'category': cat_name},
                    'geometry': {
                        'type': 'Polygon',
                        'coordinates': [poly + [poly[0]]],
                    },
                }
                for poly in polys
            ],
        }
        CategoryLabel.objects.create(
            category=cat,
            label_shapes=json.dumps(per_cat_collection),
            parent_label=image_label,
        )

    training_label = TrainingLabel.objects.create(
        dataset=dataset,
        image_label=image_label,
        source_prediction_id=session_id,
        corrections_made={
            'tile': {'x': tx, 'y': ty, 'w': tw, 'h': th},
            'num_polygons': len(polys_local),
            'polygons_dropped_outside_tile': len(polygons_src) - len(polys_local),
            'polygons_dropped_missing_category': dropped_no_cat,
            'category_counts': {k: len(v) for k, v in by_category.items()},
            'editor': data.get('corrections') or {},
        },
    )

    sentinel_dropped = _maybe_drop_sentinel(dataset, corpus_dir)

    return JsonResponse({
        'success': True,
        'tile_path': str(tile_path),
        'tile_filename': tile_filename,
        'sidecar_path': str(sidecar_path),
        'num_polygons': len(polys_local),
        'category_counts': {k: len(v) for k, v in by_category.items()},
        'image_label_id': image_label.id,
        'training_label_id': training_label.id,
        'dataset': {
            'id': dataset.id,
            'name': dataset.name,
            'num_annotations': dataset.num_annotations,
            'min_tiles_for_training': dataset.min_tiles_for_training,
            'status': dataset.status,
        },
        'retrain_sentinel_dropped': sentinel_dropped,
    })


def _ensure_image_source_id() -> int:
    """Return the ID of an 'AI rock corpus' ImageSourceType, creating once."""
    from deepgis_xr.apps.core.models import ImageSourceType
    src, _ = ImageSourceType.objects.get_or_create(
        description='ai_rock_corpus',
    )
    return src.id


# ---------------------------------------------------------------------------
# Light JSON listing — used by the editor sidebar to populate a dropdown
# of existing rock datasets the user owns. Mirrors training_datasets.list_*
# but filters on kind='rock_maskrcnn' so the rock UI never accidentally
# writes into a Mask2Former dataset.
# ---------------------------------------------------------------------------

@login_required
def rock_category_list(request):
    """Return the merged list of categories for the editor sidebar.

    Defaults always come first (in the same order as DEFAULT_CATEGORIES)
    so the user sees a consistent palette; custom categories the user
    has typed previously are appended uniquely. Each entry includes a
    palette colour the JS uses to stroke the polygon.
    """
    if request.method != 'GET':
        return JsonResponse({'error': 'GET required'}, status=405)

    all_db = list(
        CategoryType.objects.values_list('category_name', flat=True)
    )
    seen = set()
    ordered = []
    for name in DEFAULT_CATEGORIES + sorted(all_db):
        if name in seen or not name:
            continue
        seen.add(name)
        r, g, b = _stable_rgb_for_category(name)
        ordered.append({'name': name, 'rgb': [r, g, b]})

    return JsonResponse({'categories': ordered})


@login_required
def rock_dataset_list(request):
    if request.method != 'GET':
        return JsonResponse({'error': 'GET required'}, status=405)
    qs = TrainingDataset.objects.filter(
        created_by=request.user, kind=ROCK_DATASET_KIND
    ).order_by('-updated_at')
    return JsonResponse({
        'datasets': [
            {
                'id': d.id,
                'name': d.name,
                'description': d.description,
                'num_annotations': d.num_annotations,
                'min_tiles_for_training': d.min_tiles_for_training,
                'status': d.status,
                'updated_at': d.updated_at.isoformat(),
            }
            for d in qs
        ],
    })
