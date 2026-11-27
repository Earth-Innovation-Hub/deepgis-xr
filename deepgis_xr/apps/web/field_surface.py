"""What a field reading's keyframe shows under the spectrometer's patch.

The spectrometer and the laser look along the camera axis, so the patch they measured is a
circle in the keyframe: centred where the product's footprint says (``u``, ``v`` from the
left and top) and ``frac_w`` of the image width across. SAM 3 segments the keyframe by the
concepts in ``CLASSES`` (the ultralytics-api service the map captures use), each pixel takes
the most confident mask over it, and the label is the surface that fills at least half of
the patch, else ``mixed``.

A standing rover sends the same view many times. A reading whose view matches a labelled one
(no speed, minutes apart, the same laser range and aim, and keyframes that look alike) takes
that label instead of a new segmentation. The match is made against the reading that was
segmented, not against a copy of it, so a slowly turning rover does not carry a label along.

The label is stored on the reading as ``surface``:
{'label', 'share', 'shares': {surface: share of the patch}, 'centre' (the surface under the
 laser's spot, when a mask covers it), 'patch': [u, v, frac_w], 'model', and either 'n_masks'
 and 'ms' or 'from' (the reading it was copied from)}.
"""

import io
import logging
import math
import os
import threading
from collections import OrderedDict
from datetime import timedelta
from pathlib import Path

import numpy as np
from django.conf import settings

log = logging.getLogger(__name__)

MODEL = "sam3"
CLASSES = ("fence", "wall", "hedge", "grass", "tree", "house", "pavement", "gravel", "car", "sky")
MIN_CONFIDENCE = 0.35
REQUEST_TIMEOUT_S = 120
CANVAS_W = 160
DEFAULT_FRAC_W = 0.2      # a 14 degree cone in a 61 degree wide image
MIN_SHARE = 0.5
SAME_VIEW_MAX_MIN = 60.0  # between a reading and the segmented one it copies
SAME_VIEW_AIM_DEG = 3.0
SAME_VIEW_RANGE_M = 0.3
SAME_VIEW_SPEED_MPS = 0.3
# Keyframes of one standing view correlate at 0.997 or more from one reading to the next and
# fall to about 0.94 in 40 minutes as the light moves; consecutive frames of a moving rover
# sit near 0.45 (stored readings, 2026-11-27).
SAME_VIEW_LIKENESS = 0.95
SAME_VIEW_TRIES = 8
THUMB = (32, 24)
KEEP_THUMBS = 64
_THUMBS = OrderedDict()
_THUMB_LOCK = threading.Lock()


def patch_of(reading):
    """(u, v, frac_w) of the spectrometer's patch in the keyframe."""
    spec = reading.spectrum if isinstance(reading.spectrum, dict) else {}
    foot = spec.get("footprint") if isinstance(spec.get("footprint"), dict) else {}

    def get(name, default, lo, hi):
        v = foot.get(name)
        return float(v) if isinstance(v, (int, float)) and lo <= v <= hi else default

    return get("u", 0.5, 0.0, 1.0), get("v", 0.5, 0.0, 1.0), get("frac_w", DEFAULT_FRAC_W, 0.02, 1.0)


def label_patch(detections, patch, aspect=0.75):
    """{'label', 'share', 'shares'} for the patch from SAM 3 detections, or None without masks.

    ``detections`` carry class_name, confidence and mask_polygons_norm (rings of [x, y] as
    fractions of the image); ``aspect`` is the image's height over its width."""
    from PIL import Image, ImageDraw

    w = CANVAS_W
    h = max(8, int(round(w * aspect)))
    canvas = Image.new("L", (w, h), 0)
    draw = ImageDraw.Draw(canvas)
    names = []
    usable = [d for d in detections or [] if isinstance(d, dict) and d.get("class_name") in CLASSES
              and isinstance(d.get("confidence"), (int, float)) and d["confidence"] >= MIN_CONFIDENCE]
    # the most confident mask is drawn last, so it is the one a pixel keeps
    for det in sorted(usable, key=lambda d: d["confidence"]):
        if det["class_name"] not in names:
            names.append(det["class_name"])
        value = names.index(det["class_name"]) + 1
        for ring in det.get("mask_polygons_norm") or []:
            points = [(float(x) * w, float(y) * h) for x, y in ring
                      if isinstance(x, (int, float)) and isinstance(y, (int, float))]
            if len(points) >= 3:
                draw.polygon(points, fill=value)
    if not names:
        return None
    u, v, frac_w = patch
    cx, cy, r = u * w, v * h, max(1.5, 0.5 * frac_w * w)
    pixels = canvas.load()
    counts, total = {}, 0
    for y in range(max(0, int(cy - r)), min(h, int(cy + r) + 1)):
        for x in range(max(0, int(cx - r)), min(w, int(cx + r) + 1)):
            if (x + 0.5 - cx) ** 2 + (y + 0.5 - cy) ** 2 <= r * r:
                total += 1
                value = pixels[x, y]
                if value:
                    counts[names[value - 1]] = counts.get(names[value - 1], 0) + 1
    if not total:
        return None
    shares = {name: round(n / total, 3) for name, n in sorted(counts.items(), key=lambda kv: -kv[1])}
    top = next(iter(shares), None)
    if top is None:
        return {"label": "none", "share": 0.0, "shares": {}}
    label = top if shares[top] >= MIN_SHARE else "mixed"
    out = {"label": label, "share": shares[top], "shares": shares}
    # the laser's spot is the middle of the patch: what it hit, as against what the patch averages
    spot = pixels[min(w - 1, max(0, int(cx))), min(h - 1, max(0, int(cy)))]
    if spot:
        out["centre"] = names[spot - 1]
    return out


def segment(jpeg):
    """SAM 3 detections for a keyframe: (detections, inference ms), or None when the service
    is not configured or did not answer."""
    import requests

    api = (getattr(settings, "ULTRALYTICS_API_URL", None) or "").strip()
    if not api:
        return None
    try:
        response = requests.post(
            f"{api.rstrip('/')}/api/predict",
            files={"file": ("keyframe.jpg", io.BytesIO(jpeg), "image/jpeg")},
            data={"model": MODEL, "classes": ",".join(CLASSES), "confidence": MIN_CONFIDENCE},
            timeout=REQUEST_TIMEOUT_S)
        body = response.json()
    except (requests.exceptions.RequestException, ValueError) as err:
        log.warning("keyframe segmentation failed: %s", err)
        return None
    if response.status_code != 200 or not body.get("success"):
        log.warning("keyframe segmentation refused: %s", str(body.get("error") or response.status_code)[:200])
        return None
    return body.get("detections") or [], body.get("inference_ms")


def _aim(reading):
    return reading.aim if isinstance(reading.aim, dict) else {}


def thumb(jpeg):
    """A keyframe as a small grey image with its mean removed and unit length, or None."""
    from PIL import Image

    try:
        image = Image.open(io.BytesIO(jpeg)).convert("L").resize(THUMB, Image.BILINEAR)
    except Exception:  # not an image
        return None
    a = np.asarray(image, dtype=float).ravel()
    a -= a.mean()
    norm = float(np.linalg.norm(a))
    return a / norm if norm > 0 else None


def _thumb_of(reading):
    with _THUMB_LOCK:
        if reading.pk in _THUMBS:
            _THUMBS.move_to_end(reading.pk)
            return _THUMBS[reading.pk]
    jpeg = _jpeg(reading)
    t = thumb(jpeg) if jpeg else None
    with _THUMB_LOCK:
        _THUMBS[reading.pk] = t
        while len(_THUMBS) > KEEP_THUMBS:
            _THUMBS.popitem(last=False)
    return t


def same_view(a, b):
    """True when two readings of one vehicle can be the same look by their poses: standing,
    within ``SAME_VIEW_MAX_MIN``, the same laser range and, where both have an aim, the same aim."""
    if a.vehicle_id != b.vehicle_id or abs((a.captured - b.captured).total_seconds()) > SAME_VIEW_MAX_MIN * 60:
        return False
    if not (a.range_valid and b.range_valid) or a.range_m is None or b.range_m is None:
        return False
    if abs(a.range_m - b.range_m) > SAME_VIEW_RANGE_M:
        return False
    if (a.speed_mps or 0.0) > SAME_VIEW_SPEED_MPS or (b.speed_mps or 0.0) > SAME_VIEW_SPEED_MPS:
        return False
    aim_a, aim_b = _aim(a), _aim(b)
    if "azimuth_deg" in aim_a and "azimuth_deg" in aim_b:
        turn = abs((aim_a["azimuth_deg"] - aim_b["azimuth_deg"] + 180.0) % 360.0 - 180.0)
        tilt = abs(aim_a.get("elevation_deg", 0.0) - aim_b.get("elevation_deg", 0.0))
        if turn > SAME_VIEW_AIM_DEG or tilt > SAME_VIEW_AIM_DEG:
            return False
    return patch_of(a) == patch_of(b)


def _earlier_look(reading, jpeg):
    """A segmented reading of the same view (by pose, then by how alike the keyframes are), or None."""
    from .models import FieldReading

    mine = thumb(jpeg) if jpeg else None
    if mine is None:
        return None
    span = timedelta(minutes=SAME_VIEW_MAX_MIN)
    near = list(FieldReading.objects.using("observations")
                .filter(vehicle_id=reading.vehicle_id, surface__isnull=False,
                        captured__gte=reading.captured - span, captured__lte=reading.captured + span)
                .exclude(pk=reading.pk).exclude(surface__has_key="from"))
    near.sort(key=lambda r: abs((r.captured - reading.captured).total_seconds()))
    for other in near[:SAME_VIEW_TRIES]:
        if not (isinstance(other.surface, dict) and other.surface.get("label") and same_view(reading, other)):
            continue
        theirs = _thumb_of(other)
        if theirs is not None and float(mine @ theirs) >= SAME_VIEW_LIKENESS:
            return other
    return None


def _jpeg(reading):
    if not reading.image_relpath:
        return None
    root = Path(settings.OBSERVATIONS_ROOT).resolve()
    path = (root / reading.image_relpath).resolve()
    if not str(path).startswith(str(root) + os.sep) or not path.is_file():
        return None
    return path.read_bytes()


def surface_for(reading, *, copy=True, segment_new=True):
    """The surface record for a reading, or None when it has no keyframe or the service is down.

    ``copy=False`` segments the keyframe even when the same view already has a label;
    ``segment_new=False`` only copies, and returns None for a view not seen before."""
    patch = patch_of(reading)
    jpeg = _jpeg(reading)
    if jpeg is None:
        return None
    earlier = _earlier_look(reading, jpeg) if copy else None
    if earlier is not None:
        kept = {k: earlier.surface[k] for k in ("label", "share", "shares", "centre") if k in earlier.surface}
        return {**kept, "patch": list(patch), "model": earlier.surface.get("model", MODEL), "from": earlier.pk}
    if not segment_new:
        return None
    got = segment(jpeg)
    if got is None:
        return None
    detections, ms = got
    aspect = (reading.height / reading.width) if reading.width and reading.height else 0.75
    label = label_patch(detections, patch, aspect) or {"label": "none", "share": 0.0, "shares": {}}
    out = {**label, "patch": list(patch), "model": MODEL, "n_masks": len(detections)}
    if isinstance(ms, (int, float)) and math.isfinite(ms):
        out["ms"] = round(float(ms))
    return out


def write_surface(pk, *, force=False, segment_new=True):
    """Label one stored reading. Returns the surface record written, or None.

    ``force`` segments the keyframe again whatever label it or its neighbours already have;
    ``segment_new=False`` only copies the label of a view already segmented."""
    from .models import FieldReading

    reading = FieldReading.objects.using("observations").filter(pk=pk).first()
    if reading is None or not reading.image_relpath or not isinstance(reading.spectrum, dict):
        return None
    if isinstance(reading.surface, dict) and not force:
        return None
    surface = surface_for(reading, copy=not force, segment_new=segment_new)
    if surface is None:
        return None
    FieldReading.objects.using("observations").filter(pk=pk).update(surface=surface)
    return surface
