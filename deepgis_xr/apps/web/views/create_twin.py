"""AI Pilot create_twin jobs: enqueue a Gazebo x500 twin at the Cesium look-at.

Superuser confirm in the chat posts look_at + bbox here. Jobs live in the shared
live cache so every gunicorn worker sees the same record; when
DEEPGIS_TWIN_BUILDER_URL is set the request is forwarded to the
authenticated twin-builder worker on the lab server. Otherwise a local stub advances
the job through the same status ladder so the UI and tests can run without
touching production twins.
"""
from __future__ import annotations

import base64
import json
import math
import os
import secrets
import threading
import time
import uuid

import requests
from django.conf import settings
from django.core.cache import caches
from django.db import close_old_connections, transaction
from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_POST

from . import pilot
from .sims import drop_session, panel_path, register_session, set_session_status

JOB_TTL_SEC = 6 * 3600
JOB_KEY = "create-twin-job:{}"
USER_JOB_KEY = "create-twin-user:{}"
CREATE_TWIN_RATE_PER_MIN = 4
STATUSES = ("queued", "capturing", "baking", "spawning", "enrolling", "ready", "failed")
PROTECTED_NAMES = frozenset({
    "locutus", "otter", "aquatic", "heron", "kestrel", "badger", "xudrone",
    "digital-twin-locutus", "digital-twin-water-tempe-lake", "digital-twin-aquatic",
    "zenoh-locutus", "zenoh-heron-tempe",
})
VEHICLE_CLASSES = {"kestrel": "x500_gimbal"}
BODY_RADIUS_M = {"earth": 6378137.0, "moon": 1737400.0}
DEFAULT_PATCH_M = 150.0
PATCH_LIMITS = (20.0, 400.0)
DISK_QUOTA_MB = 2048
IDLE_TTL_SEC = 2 * 3600
MAX_NADIR_CHARS = 3_000_000


def _patch_m(v, default):
    if not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v):
        return default
    return float(min(PATCH_LIMITS[1], max(PATCH_LIMITS[0], v)))


def clean_create_twin(a):
    """A create_twin action for one kestrel on a 20–400 m patch, or None."""
    if not isinstance(a, dict):
        return None
    raw = a.get("vehicle_class")
    key = raw.strip().lower() if isinstance(raw, str) else "kestrel"
    if key not in VEHICLE_CLASSES:
        return None
    count = a.get("count", 1)
    if isinstance(count, bool) or not isinstance(count, (int, float)) or count != 1:
        return None
    if a.get("width_m") is None and a.get("length_m") is None and a.get("radius_m") is not None:
        side = _patch_m(a.get("radius_m"), DEFAULT_PATCH_M)
        width = length = side
    else:
        width = _patch_m(a.get("width_m"), DEFAULT_PATCH_M)
        length = _patch_m(a.get("length_m"), DEFAULT_PATCH_M)
    return {
        "type": "create_twin",
        "vehicle_class": key,
        "count": 1,
        "width_m": width,
        "length_m": length,
    }


def _look_at(data):
    src = data.get("look_at") if isinstance(data.get("look_at"), dict) else data
    lat, lon = src.get("lat"), src.get("lon")
    if not (isinstance(lat, (int, float)) and isinstance(lon, (int, float))
            and not isinstance(lat, bool) and not isinstance(lon, bool)
            and -90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    out = {"lat": float(lat), "lon": float(lon)}
    elev = src.get("elev_m")
    if isinstance(elev, (int, float)) and not isinstance(elev, bool) and math.isfinite(elev):
        out["elev_m"] = float(elev)
    return out


def _body(data):
    """earth by default. Only the Moon viewer sends moon."""
    raw = data.get("body") if isinstance(data, dict) else None
    if raw in (None, "", "earth"):
        return "earth"
    if raw == "moon":
        return "moon"
    raise ValueError("This twin is for Earth or the Moon.")


def _dem(data, body):
    """Elevation grid sampled on the viewer, required for the Moon and used on Earth when sent.

    Heights are metres relative to the look-at. An Earth job without a grid keeps
    the older flat-ground path so an older page can still confirm.
    """
    raw = data.get("dem") if isinstance(data, dict) else None
    if body == "moon" and not isinstance(raw, dict):
        raise ValueError("Lunar elevation grid is required.")
    if not isinstance(raw, dict):
        return None
    grid = raw.get("grid")
    heights = raw.get("heights")
    if (isinstance(grid, bool) or not isinstance(grid, int)
            or grid < 17 or grid > 129 or grid % 2 == 0):
        raise ValueError("Elevation grid is not usable.")
    if not isinstance(heights, list) or len(heights) != grid * grid:
        raise ValueError("Elevation grid is not usable.")
    out = []
    for value in heights:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("Elevation grid is not usable.")
        height = float(value)
        if not math.isfinite(height) or abs(height) > 20000:
            raise ValueError("Elevation grid is not usable.")
        out.append(height)
    center = out[(grid // 2) * grid + (grid // 2)]
    if abs(center) > 30:
        raise ValueError("Elevation grid is not centred on the look-at.")
    return {"grid": grid, "heights": out}


def _bbox_from_patch(lat, lon, width_m, length_m, body="earth"):
    """Axis-aligned box. width is east-west, length is north-south, both in metres."""
    if body == "moon":
        metres = BODY_RADIUS_M["moon"] * math.pi / 180.0
        cos_floor = 1e-3
    else:
        metres = 111320.0
        cos_floor = 0.05
    dlat = (length_m / 2.0) / metres
    coslat = max(cos_floor, abs(math.cos(math.radians(lat))))
    dlon = (width_m / 2.0) / (metres * coslat)
    return {
        "west": lon - dlon, "south": lat - dlat,
        "east": lon + dlon, "north": lat + dlat,
    }


def _bbox(data, look, width_m, length_m, body="earth"):
    raw = data.get("bbox")
    if isinstance(raw, dict):
        try:
            west, south, east, north = (float(raw[k]) for k in ("west", "south", "east", "north"))
        except (KeyError, TypeError, ValueError):
            west = south = east = north = None
        if body == "moon":
            metres = BODY_RADIUS_M["moon"] * math.pi / 180.0
            cos_floor = 1e-3
        else:
            metres = 111320.0
            cos_floor = 0.05
        half = (PATCH_LIMITS[1] / 2.0) / metres * 1.15
        half_lon = half / max(cos_floor, abs(math.cos(math.radians(look["lat"]))))
        if (west is not None and -180 <= west <= 180 and -180 <= east <= 180
                and -90 <= south <= 90 and -90 <= north <= 90
                and west < east and south < north
                and (east - west) <= 2 * half_lon and (north - south) <= 2 * half):
            return {"west": west, "south": south, "east": east, "north": north}
    return _bbox_from_patch(look["lat"], look["lon"], width_m, length_m, body)


def _nadir(data):
    """JPEG data URL of the viewport, or empty when it is missing or unusable."""
    raw = data.get("nadir") or ""
    if not isinstance(raw, str) or len(raw) > MAX_NADIR_CHARS:
        return ""
    if not raw.startswith("data:image/jpeg;base64,"):
        return ""
    return raw


def _callsign(user):
    """Session callsign that cannot collide with protected production twins."""
    base = f"ktwin-{secrets.token_hex(3)}"
    safe_user = "".join(c for c in (user or "u")[:8].lower() if c.isalnum()) or "u"
    name = f"{base}-{safe_user}"
    if name in PROTECTED_NAMES or any(p in name for p in ("locutus", "otter", "aquatic")):
        name = f"ktwin-{secrets.token_hex(4)}"
    return name


def _jobs():
    """The live cache is Redis when configured, so both gunicorn workers agree."""
    return caches["live"]


def _job_get(job_id):
    return _jobs().get(JOB_KEY.format(job_id))


def _job_set(job):
    store = _jobs()
    store.set(JOB_KEY.format(job["id"]), job, JOB_TTL_SEC)
    store.set(USER_JOB_KEY.format(job["user_id"]), job["id"], JOB_TTL_SEC)


def _update(job_id, **fields):
    job = _job_get(job_id)
    if not job:
        return None
    job.update(fields)
    job["updated"] = time.time()
    _job_set(job)
    return job


def _builder_configured():
    return bool(getattr(settings, "DEEPGIS_TWIN_BUILDER_URL", "")
                and getattr(settings, "DEEPGIS_TWIN_BUILDER_TOKEN", ""))


def _forward_builder(job, nadir=""):
    url = settings.DEEPGIS_TWIN_BUILDER_URL.rstrip("/") + "/jobs"
    headers = {
        "Authorization": f"Bearer {settings.DEEPGIS_TWIN_BUILDER_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "job_id": job["id"],
        "callsign": job["callsign"],
        "vehicle_class": job["vehicle_class"],
        "airframe": VEHICLE_CLASSES[job["vehicle_class"]],
        "count": 1,
        "width_m": job["width_m"],
        "length_m": job["length_m"],
        "body": job.get("body") or "earth",
        "look_at": job["look_at"],
        "bbox": job["bbox"],
        "user": job["user"],
        "host_port": job["host_port"],
        "idle_ttl_sec": IDLE_TTL_SEC,
        "disk_quota_mb": DISK_QUOTA_MB,
        "protected_names": sorted(PROTECTED_NAMES),
    }
    if job.get("dem"):
        payload["dem"] = job["dem"]
    if nadir:
        payload["nadir_b64"] = nadir
    resp = requests.post(url, json=payload, headers=headers, timeout=30)
    resp.raise_for_status()
    return resp.json() if resp.content else {}


def _stub_pipeline(job_id, nadir=""):
    """Advance a job locally without spawning Docker (tests / unset builder)."""
    close_old_connections()
    try:
        _stub_pipeline_body(job_id, nadir)
    finally:
        close_old_connections()


def _stub_pipeline_body(job_id, nadir=""):
    stages = (
        ("capturing", "Cropping DEM and nadir imagery"),
        ("baking", "Writing Gazebo heightmap world"),
        ("spawning", "Starting session container (stub)"),
        ("enrolling", "Enrolling pose agent (stub)"),
    )
    try:
        for status, message in stages:
            time.sleep(0.05)
            job = _update(job_id, status=status, message=message)
            if not job:
                return
            if getattr(settings, "DEEPGIS_TWIN_BUILDER_STUB_FAIL", False):
                _fail_job(job_id, "Stub failure forced by settings")
                return
        job = _job_get(job_id)
        if not job:
            return
        set_session_status(job["callsign"], "up")
        # A job that already carries a sampled grid does not call Open-Elevation.
        artifact = None
        if job.get("body") == "moon" or job.get("dem"):
            artifact = _local_bake(job)
        else:
            try:
                from twin_builder import bake as twin_bake  # optional; only in the lab image
                nadir_path = None
                if nadir:
                    comma = nadir.find(",")
                    raw = nadir[comma + 1:] if comma >= 0 else nadir
                    nadir_path = os.path.join(job.get("id", job_id), "viewport.jpg")
                    os.makedirs(os.path.dirname(nadir_path), exist_ok=True)
                    with open(nadir_path, "wb") as fh:
                        fh.write(base64.b64decode(raw))
                artifact = twin_bake.bake_job(job, nadir_jpeg=nadir_path)
            except Exception:
                artifact = _local_bake(job)
        _update(job_id, status="ready", message="Twin ready",
                vehicle=job["callsign"], follow_view="chase",
                airframe=VEHICLE_CLASSES[job["vehicle_class"]],
                artifact=artifact)
    except Exception as e:
        _fail_job(job_id, f"{type(e).__name__}: {str(e)[:200]}")


def _local_bake(job):
    """Write a minimal site world under the twin jobs dir when the full worker is absent."""
    root = getattr(settings, "DEEPGIS_TWIN_JOBS_DIR", "") or os.path.join(
        getattr(settings, "BASE_DIR", "/tmp"), "var", "twin-jobs")
    job_dir = os.path.join(root, job["id"])
    os.makedirs(job_dir, exist_ok=True)
    world_path = os.path.join(job_dir, "site.sdf")
    lat, lon = job["look_at"]["lat"], job["look_at"]["lon"]
    elev = job["look_at"].get("elev_m", 0.0)
    lunar = job.get("body") == "moon"
    surface = "MOON_SCS" if lunar else "EARTH_WGS84"
    note = ""
    dem = job.get("dem")
    if dem:
        heights = dem["heights"]
        kind = "lunar" if lunar else "earth"
        note = f"    <!-- {kind} heightmap {dem['grid']} {min(heights):.2f} {max(heights):.2f} -->\n"
    sdf = f"""<?xml version="1.0" ?>
<sdf version="1.9">
  <world name="{job['callsign']}">
{note}    <spherical_coordinates>
      <surface_model>{surface}</surface_model>
      <latitude_deg>{lat:.8f}</latitude_deg>
      <longitude_deg>{lon:.8f}</longitude_deg>
      <elevation>{elev:.3f}</elevation>
      <heading_deg>0</heading_deg>
    </spherical_coordinates>
    <include>
      <uri>https://fuel.gazebosim.org/1.0/OpenRobotics/models/Sun</uri>
    </include>
    <model name="ground_plane">
      <static>true</static>
      <link name="link">
        <collision name="collision"><geometry><plane><normal>0 0 1</normal></plane></geometry></collision>
        <visual name="visual"><geometry><plane><normal>0 0 1</normal><size>1 1</size></plane></geometry></visual>
      </link>
    </model>
  </world>
</sdf>
"""
    with open(world_path, "w", encoding="utf-8") as fh:
        fh.write(sdf)
    meta = {
        "callsign": job["callsign"],
        "look_at": job["look_at"],
        "bbox": job["bbox"],
        "width_m": job["width_m"],
        "length_m": job["length_m"],
        "count": 1,
        "body": job.get("body") or "earth",
        "airframe": VEHICLE_CLASSES[job["vehicle_class"]],
        "world_sdf": world_path,
        "props": [],
    }
    with open(os.path.join(job_dir, "job.json"), "w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=2)
    return {"job_dir": job_dir, "world_sdf": world_path}


def _fail_job(job_id, message):
    job = _job_get(job_id)
    if job:
        drop_session(job.get("callsign"))
        job.pop("url", None)
        _job_set(job)
    _update(job_id, status="failed", message=message)


def enqueue(user, payload):
    """Validate payload and create a queued job. Raises ValueError on bad input."""
    act = clean_create_twin(payload)
    if not act:
        count = payload.get("count", 1) if isinstance(payload, dict) else 1
        if count != 1:
            raise ValueError("This twin spawns one kestrel.")
        raise ValueError("Unknown vehicle class.")
    look = _look_at(payload)
    if not look:
        raise ValueError("look_at lat/lon required.")
    body = _body(payload)
    dem = _dem(payload, body)
    bbox = _bbox(payload, look, act["width_m"], act["length_m"], body)
    nadir = _nadir(payload)
    user_id = user.pk
    existing_id = _jobs().get(USER_JOB_KEY.format(user_id))
    if existing_id:
        existing = _job_get(existing_id)
        if existing and existing.get("status") not in ("ready", "failed"):
            raise ValueError("You already have a twin job in progress.")
    job_id = uuid.uuid4().hex
    callsign = _callsign(user.get_username())
    if callsign in PROTECTED_NAMES:
        raise ValueError("Refusing protected twin name.")
    sim = register_session(callsign=callsign, owner=user, look_at=look)
    job = {
        "id": job_id,
        "user_id": user_id,
        "user": user.get_username(),
        "status": "queued",
        "message": "Queued",
        "vehicle_class": act["vehicle_class"],
        "count": 1,
        "width_m": act["width_m"],
        "length_m": act["length_m"],
        "body": body,
        "dem": dem,
        "look_at": look,
        "bbox": bbox,
        "callsign": callsign,
        "host_port": sim.host_port,
        "url": panel_path(sim.host_port),
        "created": time.time(),
        "updated": time.time(),
        "idle_ttl_sec": IDLE_TTL_SEC,
        "disk_quota_mb": DISK_QUOTA_MB,
    }
    _job_set(job)
    if _builder_configured():
        try:
            _forward_builder(job, nadir)
            _update(job_id, message="Forwarded to twin builder")
        except (requests.RequestException, ValueError, KeyError) as e:
            _fail_job(job_id, f"Builder unreachable: {type(e).__name__}: {str(e)[:160]}")
        return _job_get(job_id)
    def _start():
        threading.Thread(target=_stub_pipeline, args=(job_id, nadir), daemon=True).start()
    transaction.on_commit(_start)
    return job


def public_job(job):
    if not job:
        return None
    keys = ("id", "status", "message", "vehicle_class", "count", "width_m", "length_m", "body", "look_at", "bbox",
            "callsign", "vehicle", "follow_view", "airframe", "url", "created", "updated")
    return {k: job[k] for k in keys if k in job}


@require_POST
def pilot_create_twin(request):
    if not request.user.is_authenticated:
        return JsonResponse({"error": "login_required", "login_url": "/label/admin/login/"}, status=401)
    if not request.user.is_superuser:
        return JsonResponse({"error": "Creating twins is for superusers."}, status=403)
    try:
        data = json.loads(request.body)
    except ValueError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)
    if not isinstance(data, dict):
        return JsonResponse({"error": "Invalid JSON"}, status=400)
    if pilot._rate_limited(request.user.pk, "create-twin", CREATE_TWIN_RATE_PER_MIN):
        return JsonResponse({"error": "Too many twin jobs; wait a minute."}, status=429)
    try:
        job = enqueue(request.user, data)
    except ValueError as e:
        return JsonResponse({"error": str(e)}, status=400)
    return JsonResponse(public_job(job))


@require_GET
def pilot_create_twin_status(request, job_id):
    if not request.user.is_authenticated:
        return JsonResponse({"error": "login_required", "login_url": "/label/admin/login/"}, status=401)
    if not request.user.is_superuser:
        return JsonResponse({"error": "Creating twins is for superusers."}, status=403)
    if not isinstance(job_id, str) or not job_id.isalnum() or len(job_id) > 40:
        return JsonResponse({"error": "Unknown job."}, status=404)
    job = _job_get(job_id)
    if not job or job.get("user_id") != request.user.pk:
        return JsonResponse({"error": "Unknown job."}, status=404)
    if _builder_configured() and job.get("status") not in ("ready", "failed"):
        try:
            url = settings.DEEPGIS_TWIN_BUILDER_URL.rstrip("/") + f"/jobs/{job_id}"
            headers = {"Authorization": f"Bearer {settings.DEEPGIS_TWIN_BUILDER_TOKEN}"}
            resp = requests.get(url, headers=headers, timeout=15)
            if resp.ok:
                remote = resp.json()
                if isinstance(remote, dict) and remote.get("status") in STATUSES:
                    if remote.get("status") == "failed":
                        drop_session(job.get("callsign"))
                        job.pop("url", None)
                        _job_set(job)
                    elif remote.get("status") == "ready":
                        set_session_status(job.get("callsign"), "up")
                    fields = {k: remote[k] for k in ("status", "message", "vehicle", "follow_view", "airframe")
                              if k in remote}
                    job = _update(job_id, **fields) or job
        except (requests.RequestException, ValueError, KeyError):
            pass
    return JsonResponse(public_job(job))
