"""
Live vehicle poses for the viewers' follow mode (the AI pilot's follow_vehicle).

A vehicle's publisher (for the OpenUAV PX4 twin, dreams_llm_bridge's deepgis_pose
node; later field vehicles) POSTs its latest pose to vehicle_pose with a
bearer token. Only the latest pose per vehicle is kept, in the shared "live" cache;
signed-in viewers poll vehicles_live and fly the camera with it. Nothing here sends
anything to a vehicle.

Tokens are configured as VEHICLE_POSE_TOKENS = "vehicle_id:sha256hex,...": the server
keeps only the hash, and a token may only post for its own vehicle id.
"""

import hashlib
import hmac
import json
import math
import re
from time import time as now

from django.conf import settings
from django.core.cache import caches
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

MAX_BODY_BYTES = 4096
POSE_TTL_SEC = 60  # a vehicle silent this long drops off the list
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


def token_vehicle(request, tokens):
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    digest = hashlib.sha256(auth[7:].strip().encode()).hexdigest()
    found = None
    for known, vid in tokens.items():
        if hmac.compare_digest(known, digest):
            found = vid
    return found


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


@csrf_exempt
@require_POST
def vehicle_pose(request):
    tokens = pose_tokens()
    if not tokens:
        return JsonResponse({"error": "Vehicle poses are not configured"}, status=503)
    vid = token_vehicle(request, tokens)
    if vid is None:
        return JsonResponse({"error": "A valid vehicle token is required"}, status=401)
    if len(request.body) > MAX_BODY_BYTES:
        return JsonResponse({"error": "Pose too large"}, status=413)
    try:
        data = json.loads(request.body or b"{}")
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({"error": "Invalid JSON"}, status=400)
    if not isinstance(data, dict):
        return JsonResponse({"error": "Invalid JSON"}, status=400)
    if data.get("vehicle", vid) != vid:
        return JsonResponse({"error": "This token is for another vehicle"}, status=403)
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


@require_GET
def vehicles_live(request):
    if not request.user.is_authenticated:
        return JsonResponse({"error": "Sign in to follow vehicles"}, status=401)
    live = caches["live"]
    ids = live.get(IDS_KEY) or []
    poses = live.get_many([f"vehicle:{vid}" for vid in ids]).values()
    t = now()
    vehicles = []
    for pose in poses:
        pose = dict(pose)
        pose["age_sec"] = round(max(0.0, t - pose.pop("received")), 2)
        vehicles.append(pose)
    vehicles.sort(key=lambda p: p["age_sec"])
    return JsonResponse({"vehicles": vehicles})
