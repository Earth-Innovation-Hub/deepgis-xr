"""
Live vehicle poses for the viewers' follow mode (the AI pilot's follow_vehicle).

A vehicle's publisher (for the OpenUAV PX4 twin, dreams_llm_bridge's deepgis_pose
node; later field vehicles) POSTs its latest pose to vehicle_pose with a
bearer token. Only the latest pose per vehicle is kept, in the shared "live" cache;
signed-in viewers poll vehicles_live and fly the camera with it. Nothing here sends
anything to a vehicle.

Tokens are configured as VEHICLE_POSE_TOKENS = "vehicle_id:sha256hex,...": the server
keeps only the hash, and a token may only post for its own vehicle id. Sims started by
the OpenUAV launcher instead hold HMAC-SHA256(VEHICLE_FLEET_SECRET, vehicle id) for an id
starting with VEHICLE_FLEET_PREFIX, so each sim can post only as itself and none needs
configuring here.

Camera frames work the same way: the vehicle POSTs a JPEG to vehicle_frame with the same
token (metadata, including the pose at capture, in the X-Frame-Meta header), only the
latest is kept, vehicles_live says which vehicles have one, and signed-in viewers fetch
it from vehicle_frame_image.
"""

import hashlib
import hmac
import json
import math
import re
from io import BytesIO
from time import time as now

from django.conf import settings
from django.core.cache import caches
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST
from PIL import Image

MAX_BODY_BYTES = 4096
POSE_TTL_SEC = 60  # a vehicle silent this long drops off the list
FRAME_TTL_SEC = 60
FRAME_MAX_BYTES = 600 * 1024
FRAME_MAX_SIDE = 4096
CAPTURE_SKEW_SEC = 600  # a capture time further than this from the server's clock is dropped
IDS_KEY = "vehicles:ids"
VEHICLE_ID = re.compile(r"[a-z0-9_-]{1,40}")
KINDS = ("sim", "field")
# (min, max); out-of-range numbers are dropped, not clamped: a bad pose must not fly the camera
POSE_LIMITS = {
    "up_m": (-500.0, 20000.0),
    "alt_amsl": (-500.0, 20000.0),
    "heading_deg": (-360.0, 720.0),
    "gimbal_pitch_deg": (-90.0, 45.0),
    "hfov_deg": (1.0, 170.0),
    "speed_mps": (0.0, 400.0),
}


def pose_tokens():
    """{sha256 hex: vehicle id} from VEHICLE_POSE_TOKENS."""
    out = {}
    for item in (settings.VEHICLE_POSE_TOKENS or "").split(","):
        vid, _, digest = item.strip().partition(":")
        if VEHICLE_ID.fullmatch(vid) and re.fullmatch(r"[0-9a-f]{64}", digest):
            out[digest] = vid
    return out


def bearer(request):
    auth = request.headers.get("Authorization", "")
    token = auth[7:].strip() if auth.startswith("Bearer ") else ""
    return token or None


def token_vehicle(token, tokens):
    digest = hashlib.sha256(token.encode()).hexdigest()
    found = None
    for known, vid in tokens.items():
        if hmac.compare_digest(known, digest):
            found = vid
    return found


def fleet_token(secret, vid):
    return hmac.new(secret.encode(), vid.encode(), hashlib.sha256).hexdigest()


def fleet_vehicle(token, vid):
    """vid if token is the launcher's token for this sim, else None."""
    secret, prefix = settings.VEHICLE_FLEET_SECRET, settings.VEHICLE_FLEET_PREFIX
    if not (secret and prefix and isinstance(vid, str) and vid.startswith(prefix)
            and VEHICLE_ID.fullmatch(vid)):
        return None
    return vid if hmac.compare_digest(fleet_token(secret, vid), token) else None


def _finite(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _latlon(lat, lon):
    return _finite(lat) and _finite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180


def clean_pose(data):
    """The stored pose, or None if the position is missing or invalid."""
    if not _latlon(data.get("lat"), data.get("lon")):
        return None
    pose = {"lat": float(data["lat"]), "lon": float(data["lon"])}
    for field, (lo, hi) in POSE_LIMITS.items():
        v = data.get(field)
        if _finite(v) and lo <= v <= hi:
            pose[field] = float(v)
    ref = data.get("ref")
    if isinstance(ref, dict) and _latlon(ref.get("lat"), ref.get("lon")):
        pose["ref"] = {"lat": float(ref["lat"]), "lon": float(ref["lon"])}
        if _finite(ref.get("alt_amsl")):
            pose["ref"]["alt_amsl"] = float(ref["alt_amsl"])
    for field in ("armed", "landed"):
        if isinstance(data.get(field), bool):
            pose[field] = data[field]
    name = data.get("name")
    if isinstance(name, str) and name.strip():
        pose["name"] = name.strip()[:80]
    if data.get("kind") in KINDS:
        pose["kind"] = data["kind"]
    return pose


def _json_object(raw):
    try:
        data = json.loads(raw or b"{}")
    except (ValueError, UnicodeDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _vehicle_for(token, tokens, data):
    """(vehicle id, None) or (None, error response) for a parsed request."""
    vid = token_vehicle(token, tokens) or fleet_vehicle(token, data.get("vehicle"))
    if vid is None:
        return None, JsonResponse({"error": "A valid vehicle token is required"}, status=401)
    if data.get("vehicle", vid) != vid:
        return None, JsonResponse({"error": "This token is for another vehicle"}, status=403)
    return vid, None


@csrf_exempt
@require_POST
def vehicle_pose(request):
    tokens = pose_tokens()
    if not (tokens or settings.VEHICLE_FLEET_SECRET):
        return JsonResponse({"error": "Vehicle poses are not configured"}, status=503)
    token = bearer(request)
    if token is None:
        return JsonResponse({"error": "A valid vehicle token is required"}, status=401)
    if len(request.body) > MAX_BODY_BYTES:
        return JsonResponse({"error": "Pose too large"}, status=413)
    data = _json_object(request.body)
    if data is None:
        return JsonResponse({"error": "Invalid JSON"}, status=400)
    vid, error = _vehicle_for(token, tokens, data)
    if error:
        return error
    pose = clean_pose(data)
    if pose is None:
        return JsonResponse({"error": "lat and lon are required"}, status=400)
    pose.update(id=vid, received=now())
    live = caches["live"]
    live.set(f"vehicle:{vid}", pose, POSE_TTL_SEC)
    ids = live.get(IDS_KEY) or []
    if vid not in ids:
        live.set(IDS_KEY, sorted({*ids, vid}), None)
    return JsonResponse({"ok": True})


def jpeg_size(data):
    """(width, height) of a JPEG within FRAME_MAX_SIDE, else None. Reads only the header."""
    if not data.startswith(b"\xff\xd8\xff"):
        return None
    try:
        with Image.open(BytesIO(data)) as im:
            if im.format != "JPEG":
                return None
            w, h = im.size
    except Exception:
        return None
    return (w, h) if 0 < w <= FRAME_MAX_SIDE and 0 < h <= FRAME_MAX_SIDE else None


@csrf_exempt
@require_POST
def vehicle_frame(request):
    """One camera frame (image/jpeg body) from a vehicle; the optional X-Frame-Meta header
    carries the JSON {vehicle, captured (unix s), pose fields at capture}."""
    tokens = pose_tokens()
    if not (tokens or settings.VEHICLE_FLEET_SECRET):
        return JsonResponse({"error": "Vehicle frames are not configured"}, status=503)
    token = bearer(request)
    if token is None:
        return JsonResponse({"error": "A valid vehicle token is required"}, status=401)
    if len(request.body) > FRAME_MAX_BYTES:
        return JsonResponse({"error": "Frame too large"}, status=413)
    raw_meta = request.headers.get("X-Frame-Meta", "")
    meta = _json_object(raw_meta.encode()) if len(raw_meta) <= MAX_BODY_BYTES else None
    if meta is None:
        return JsonResponse({"error": "X-Frame-Meta must be a JSON object"}, status=400)
    vid, error = _vehicle_for(token, tokens, meta)
    if error:
        return error
    size = jpeg_size(request.body)
    if size is None:
        return JsonResponse({"error": "The body must be a JPEG"}, status=400)
    t = now()
    info = {"w": size[0], "h": size[1], "bytes": len(request.body), "received": t}
    pose = clean_pose(meta)
    if pose:
        info["pose"] = pose
    captured = meta.get("captured")
    if _finite(captured) and abs(captured - t) <= CAPTURE_SKEW_SEC:
        info["captured"] = float(captured)
    live = caches["live"]
    info["seq"] = (live.get(f"frame_info:{vid}") or {}).get("seq", 0) + 1
    live.set(f"frame:{vid}", bytes(request.body), FRAME_TTL_SEC)
    live.set(f"frame_info:{vid}", info, FRAME_TTL_SEC)
    return JsonResponse({"ok": True, "seq": info["seq"]})


@require_GET
def vehicle_frame_image(request, vid):
    if not request.user.is_authenticated:
        return JsonResponse({"error": "Sign in to see vehicle cameras"}, status=401)
    jpeg = caches["live"].get(f"frame:{vid}") if VEHICLE_ID.fullmatch(vid) else None
    if jpeg is None:
        return JsonResponse({"error": "No recent frame from this vehicle"}, status=404)
    resp = HttpResponse(jpeg, content_type="image/jpeg")
    resp["Cache-Control"] = "private, no-store"
    return resp


@require_GET
def vehicles_live(request):
    if not request.user.is_authenticated:
        return JsonResponse({"error": "Sign in to follow vehicles"}, status=401)
    live = caches["live"]
    ids = live.get(IDS_KEY) or []
    found = live.get_many([f"vehicle:{vid}" for vid in ids])
    poses = found.values()
    if len(found) < len(ids):  # sims come and go; forget the ones whose pose expired
        live.set(IDS_KEY, sorted(p["id"] for p in poses), None)
    frames = live.get_many([f"frame_info:{p['id']}" for p in poses])
    t = now()
    vehicles = []
    for pose in poses:
        pose = dict(pose)
        pose["age_sec"] = round(max(0.0, t - pose.pop("received")), 2)
        info = frames.get(f"frame_info:{pose['id']}")
        if info:
            pose["frame"] = {"seq": info["seq"], "w": info["w"], "h": info["h"],
                             "age_sec": round(max(0.0, t - info["received"]), 2)}
        vehicles.append(pose)
    vehicles.sort(key=lambda p: p["age_sec"])
    return JsonResponse({"vehicles": vehicles})
