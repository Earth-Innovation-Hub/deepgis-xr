"""Stored field readings: one camera keyframe, its spectrum, and where the laser landed.

The live cache still serves the picture-in-picture. This module keeps the same
posts, keyed by the capture time the vehicle already sends, in the observations
database. A missing database or a write error never fails the live post.

The target is the end of the laser ray: ``range`` metres from the camera along
its heading, with pitch measured up from the horizon. Heading 0 is north.
Without a heading the reading is kept and the target is left empty.
"""

import base64
import logging
import math
import os
import sys
import json
import threading
import time
import urllib.parse
import urllib.request
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

from django.conf import settings
from django.contrib.gis.geos import Point, Polygon
from django.db import IntegrityError, close_old_connections, transaction
from django.db.models import Q
from django.http import FileResponse, HttpResponse, JsonResponse
from django.views.decorators.http import require_GET

log = logging.getLogger(__name__)

EARTH_R_M = 6371000.0
QUERY_LIMIT = 500
_field_yes = set()


def _is_field(vid):
    """Only enrolled field robots are stored. Twin frames stay in the live cache."""
    if vid in _field_yes:
        return True
    from deepgis_xr.apps.core.models import Vehicle
    if Vehicle.objects.filter(vehicle_id=vid, kind="field").exists():
        _field_yes.add(vid)
        return True
    return False


def enabled():
    """True only for a configured observations database outside the test runner."""
    if "test" in sys.argv:
        return False
    root = getattr(settings, "OBSERVATIONS_ROOT", "") or ""
    return bool(root) and "observations" in settings.DATABASES


def destination(lat, lon, heading_deg, pitch_deg, range_m):
    """(lat, lon, up_m) at the end of the ray, or None when it cannot be aimed."""
    if not all(math.isfinite(v) for v in (lat, lon, heading_deg, range_m)) or range_m < 0:
        return None
    pitch = pitch_deg if pitch_deg is not None and math.isfinite(pitch_deg) else 0.0
    horiz = range_m * math.cos(math.radians(pitch))
    up = range_m * math.sin(math.radians(pitch))
    heading = math.radians(heading_deg)
    north = horiz * math.cos(heading)
    east = horiz * math.sin(heading)
    dlat = math.degrees(north / EARTH_R_M)
    cos_lat = math.cos(math.radians(lat))
    dlon = math.degrees(east / (EARTH_R_M * cos_lat)) if abs(cos_lat) > 1e-6 else 0.0
    return lat + dlat, lon + dlon, up


def remember_frame(vid, info, jpeg):
    if not enabled():
        return
    try:
        _remember_frame(vid, info, jpeg)
    except Exception:
        log.exception("field reading frame for %s was not stored", vid)


def remember_spectrum(vid, captured, data):
    if not enabled():
        return
    try:
        _remember_spectrum(vid, captured, data)
    except Exception:
        log.exception("field reading spectrum for %s was not stored", vid)


def _usec(captured):
    if captured is None:
        return None
    try:
        usec = int(round(float(captured) * 1_000_000))
    except (TypeError, ValueError):
        return None
    return usec if usec > 0 else None


def _when(usec):
    return datetime.fromtimestamp(usec / 1_000_000, timezone.utc)


def _point(lon, lat):
    if lon is None or lat is None or not (math.isfinite(lon) and math.isfinite(lat)):
        return None
    return Point(float(lon), float(lat), srid=4326)


def _place(reading):
    """Fill the target from the camera pose and the laser, or clear it."""
    reading.target = None
    reading.target_up_m = None
    if not reading.range_valid or reading.range_m is None or reading.camera is None:
        return
    if reading.heading_deg is None:
        return
    landed = destination(reading.camera.y, reading.camera.x, reading.heading_deg,
                         reading.pitch_deg, reading.range_m)
    if landed is None:
        return
    lat, lon, up = landed
    reading.target = _point(lon, lat)
    reading.target_up_m = up


def _save(reading):
    from .models import FieldReading

    fields = ("captured", "alt_amsl", "heading_deg", "pitch_deg", "speed_mps", "camera",
              "range_m", "range_min_m", "range_max_m", "range_valid", "target", "target_up_m",
              "image_relpath", "image_bytes", "width", "height", "spectrum")
    for _attempt in (1, 2):
        try:
            with transaction.atomic(using="observations"):
                _place(reading)
                current = (FieldReading.objects.using("observations")
                           .select_for_update()
                           .filter(vehicle_id=reading.vehicle_id, captured_usec=reading.captured_usec)
                           .first())
                if current is None:
                    reading.pk = None
                    reading.save(using="observations")
                    return reading
                changed = [name for name in fields if name not in ("target", "target_up_m") and getattr(reading, name) not in (None, "")]
                for name in changed:
                    setattr(current, name, getattr(reading, name))
                _place(current)
                # target can be cleared; analysis is written by another thread, so it is not in this list
                current.save(using="observations", update_fields=changed + ["target", "target_up_m"])
                return current
        except IntegrityError:
            continue


def _remember_frame(vid, info, jpeg):
    from .models import FieldReading

    if not _is_field(vid):
        return
    usec = _usec((info or {}).get("captured"))
    if usec is None:
        return
    pose = (info or {}).get("pose") or {}
    rel = _write_jpeg(vid, usec, jpeg)
    reading = FieldReading(
        vehicle_id=vid, captured_usec=usec, captured=_when(usec),
        alt_amsl=pose.get("alt_amsl"), heading_deg=pose.get("heading_deg"),
        pitch_deg=pose.get("gimbal_pitch_deg"), speed_mps=pose.get("speed_mps"),
        camera=_point(pose.get("lon"), pose.get("lat")),
        image_relpath=rel.as_posix(), image_bytes=len(jpeg),
        width=(info or {}).get("w"), height=(info or {}).get("h"))
    # keep a spectrum and laser already stored for this capture
    prior = (FieldReading.objects.using("observations")
             .filter(vehicle_id=vid, captured_usec=usec).first())
    if prior is not None:
        reading.range_m = prior.range_m
        reading.range_min_m = prior.range_min_m
        reading.range_max_m = prior.range_max_m
        reading.range_valid = prior.range_valid
        reading.spectrum = prior.spectrum
    _keep(reading)


def _write_jpeg(vid, usec, jpeg):
    when = _when(usec)
    rel = Path(vid) / f"{when:%Y}" / f"{when:%m}" / f"{when:%d}" / f"{usec}.jpg"
    root = Path(settings.OBSERVATIONS_ROOT)
    path = (root / rel).resolve()
    if not str(path).startswith(str(root.resolve()) + os.sep):
        raise ValueError("reading path escapes the observations root")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".part")
    tmp.write_bytes(bytes(jpeg))
    tmp.replace(path)
    return rel


def _remember_spectrum(vid, captured, data):
    from .models import FieldReading

    if not _is_field(vid):
        return
    usec = _usec(captured)
    if usec is None or not isinstance(data, dict):
        return
    laser = data.get("laser") or {}
    prior = (FieldReading.objects.using("observations")
             .filter(vehicle_id=vid, captured_usec=usec).first())
    reading = prior or FieldReading(vehicle_id=vid, captured_usec=usec, captured=_when(usec))
    reading.spectrum = data
    reading.range_m = laser.get("range_m")
    reading.range_min_m = laser.get("min_m")
    reading.range_max_m = laser.get("max_m")
    reading.range_valid = bool(laser.get("valid", 0) >= 0.5 and laser.get("range_m") is not None)
    _keep(reading)


def _features(rows):
    features = []
    for row in rows:
        point = row.target or row.camera
        if point is None:
            continue
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [point.x, point.y]},
            "properties": {
                "id": row.id,
                "vehicle": row.vehicle_id,
                "captured": row.captured.isoformat(),
                "role": "target" if row.target is not None else "camera",
                "range_m": row.range_m,
                "up_m": row.target_up_m,
                "heading_deg": row.heading_deg,
                "frame": f"/label/api/field-readings/{row.id}/frame.jpg" if row.image_relpath else None,
                "spectrum": bool(row.spectrum),
            },
        })
    return {"type": "FeatureCollection", "features": features}


def _box(params):
    try:
        south, west, north, east = (float(params[k]) for k in ("south", "west", "north", "east"))
    except (KeyError, TypeError, ValueError):
        return None
    if not all(math.isfinite(v) for v in (south, west, north, east)):
        return None
    if not (-90 <= south < north <= 90 and -180 <= west < east <= 180):
        return None
    if north - south > 5 or east - west > 5:
        return None
    poly = Polygon.from_bbox((west, south, east, north))
    poly.srid = 4326
    return poly


@require_GET
def geojson(request):
    """Readings whose target (or camera, when the ray could not be aimed) lies in the box."""
    if not request.user.is_authenticated:
        return JsonResponse({"error": "Sign in to see field readings"}, status=401)
    if not enabled():
        return JsonResponse({"type": "FeatureCollection", "features": []})
    box = _box(request.GET)
    if box is None:
        return JsonResponse({"error": "south, west, north, east are required"}, status=400)
    from .models import FieldReading

    rows = (FieldReading.objects.using("observations")
            .filter(Q(target__intersects=box) | Q(target__isnull=True, camera__intersects=box))
            .order_by("-captured")[:QUERY_LIMIT])
    resp = JsonResponse(_features(rows))
    resp["Cache-Control"] = "private, no-store"
    return resp


@require_GET
def frame_image(request, pk):
    if not request.user.is_authenticated:
        return JsonResponse({"error": "Sign in to see field readings"}, status=401)
    if not enabled():
        return HttpResponse(status=404)
    from .models import FieldReading

    row = FieldReading.objects.using("observations").filter(pk=pk).first()
    if row is None or not row.image_relpath:
        return HttpResponse(status=404)
    root = Path(settings.OBSERVATIONS_ROOT).resolve()
    path = (root / row.image_relpath).resolve()
    if not str(path).startswith(str(root) + os.sep) or not path.is_file():
        return HttpResponse(status=404)
    resp = FileResponse(path.open("rb"), content_type="image/jpeg")
    resp["Cache-Control"] = "private, max-age=86400"
    return resp


_NOTE_QUEUE = deque()
_NOTE_LOCK = threading.Lock()
_NOTE_THREAD = None
_NOTE_LIMIT = 4

_NOTE_SYSTEM = (
    "You write two short notes for one stored reading from a field robot. "
    "The attached image is its photograph, taken at the same moment as the instrument readings. "
    "image: two or three sentences on only what is visible. Mention the ground, vegetation, "
    "structures and where they sit in the frame. Do not repeat instrument numbers in this note. "
    "combined: two or three sentences that put the photograph together with the laser range, "
    "the spectrometer notes, and the sun, weather and air-quality figures in the request. "
    "Say whether those notes fit the part of the picture the laser is aimed at, and use the "
    "sun, cloud and air quality only as context for the light and the air. Band ratios are "
    "raw counts for this instrument, not NDVI; do not judge them by reflectance thresholds. "
    "Do not invent measurements, species or place names."
)
_NOTE_SCHEMA = {
    "type": "object",
    "properties": {"image": {"type": "string"}, "combined": {"type": "string"}},
    "required": ["image", "combined"],
}


def _facts(reading):
    """The pose, laser and spectrometer notes that go beside the photograph."""
    lines = []
    if reading.camera is not None:
        lines.append("Camera at latitude %.5f, longitude %.5f." % (reading.camera.y, reading.camera.x))
    if reading.heading_deg is not None:
        lines.append("Heading %.0f degrees, pitch %.0f degrees." % (reading.heading_deg, reading.pitch_deg or 0))
    elif reading.pitch_deg is not None:
        lines.append("Pitch %.0f degrees. No heading was reported." % reading.pitch_deg)
    spec = reading.spectrum if isinstance(reading.spectrum, dict) else {}
    laser = spec.get("laser") or {}
    if isinstance(laser.get("range_m"), (int, float)):
        lines.append("Laser range %.2f m along the camera axis." % laser["range_m"])
    foot = spec.get("footprint") or {}
    if isinstance(foot.get("diameter_m"), (int, float)):
        lines.append("The spectrometer averages a patch about %.1f m across there." % foot["diameter_m"])
    notes = [str(item) for item in (spec.get("notes") or []) if item][:6]
    if notes:
        lines.append("Spectrometer notes: " + " ".join(notes))
    indices = spec.get("indices") if isinstance(spec.get("indices"), dict) else {}
    bits = ["%s %.2f" % (key, value) for key, value in indices.items() if isinstance(value, (int, float))]
    if bits:
        lines.append("Band ratios of raw counts: " + ", ".join(bits) + ".")
    sky = reading.sky if isinstance(getattr(reading, "sky", None), dict) else {}
    sun = sky.get("sun") or {}
    if isinstance(sun.get("azimuth_deg"), (int, float)) and isinstance(sun.get("elevation_deg"), (int, float)):
        lines.append("Sun azimuth %.0f degrees clockwise from north, elevation %.0f degrees."
                     % (sun["azimuth_deg"], sun["elevation_deg"]))
    air = sky.get("atmosphere") or {}
    weather = []
    if isinstance(air.get("temperature_c"), (int, float)):
        weather.append("%.0f C" % air["temperature_c"])
    if isinstance(air.get("relative_humidity_pct"), (int, float)):
        weather.append("%.0f%% relative humidity" % air["relative_humidity_pct"])
    if isinstance(air.get("pressure_hpa"), (int, float)):
        weather.append("%.0f hPa" % air["pressure_hpa"])
    if isinstance(air.get("cloud_cover_pct"), (int, float)):
        weather.append("%.0f%% cloud" % air["cloud_cover_pct"])
    if isinstance(air.get("wind_speed_mps"), (int, float)):
        weather.append("wind %.1f m/s from %.0f degrees" % (air["wind_speed_mps"], air.get("wind_from_deg") or 0))
    if isinstance(air.get("shortwave_wm2"), (int, float)):
        weather.append("shortwave %.0f W/m2" % air["shortwave_wm2"])
    if weather:
        lines.append("Weather (" + str(air.get("time") or "Open-Meteo") + "): " + ", ".join(weather) + ".")
    quality = []
    if isinstance(air.get("us_aqi"), (int, float)):
        quality.append("US AQI %.0f" % air["us_aqi"])
    if isinstance(air.get("pm2_5_ugm3"), (int, float)):
        quality.append("PM2.5 %.1f ug/m3" % air["pm2_5_ugm3"])
    if isinstance(air.get("ozone_ugm3"), (int, float)):
        quality.append("ozone %.0f ug/m3" % air["ozone_ugm3"])
    if isinstance(air.get("uv_index"), (int, float)):
        quality.append("UV index %.1f" % air["uv_index"])
    if isinstance(air.get("aerosol_optical_depth"), (int, float)):
        quality.append("aerosol optical depth %.2f" % air["aerosol_optical_depth"])
    if quality:
        lines.append("Air quality: " + ", ".join(quality) + ".")
    return "\n".join(lines)


def _notes_from(out):
    if not isinstance(out, dict):
        return None
    body = out.get("json") if isinstance(out.get("json"), dict) else out
    image, combined = body.get("image"), body.get("combined")
    if not isinstance(image, str) or not isinstance(combined, str):
        return None
    image, combined = " ".join(image.split()), " ".join(combined.split())
    if not image or not combined:
        return None
    return {"image": image[:1500], "combined": combined[:1500]}


def _jpeg_b64(reading):
    if not reading.image_relpath:
        return None
    root = Path(settings.OBSERVATIONS_ROOT).resolve()
    path = (root / reading.image_relpath).resolve()
    if not str(path).startswith(str(root) + os.sep) or not path.is_file():
        return None
    return base64.b64encode(path.read_bytes()).decode("ascii")


def _write_analysis(pk):
    from .models import FieldReading
    from .views.pilot import call_mcp_tool

    close_old_connections()
    reading = FieldReading.objects.using("observations").filter(pk=pk).first()
    if reading is None or (isinstance(reading.analysis, dict) and reading.analysis.get("image")):
        return
    if reading.camera is not None and not reading.sky:
        _write_sky(reading.pk)
        reading = FieldReading.objects.using("observations").filter(pk=pk).first()
    image = _jpeg_b64(reading)
    if not image or not isinstance(reading.spectrum, dict):
        return
    timeout = min(float(getattr(settings, "DEEPGIS_PILOT_TIMEOUT_SEC", 45) or 45), 45)
    out = call_mcp_tool("describe_image", {
        "image": image,
        "prompt": "Instrument readings taken with this photograph:\n" + _facts(reading) + "\nWrite the image note and the combined note.",
        "system_prompt": _NOTE_SYSTEM,
        "json_schema": _NOTE_SCHEMA,
        "temperature": 0.2,
        "max_tokens": 500,
        "timeout_sec": timeout,
    }, timeout + 10)
    notes = _notes_from(out)
    if notes is None:
        log.warning("field reading %s note was not understood", pk)
        return
    FieldReading.objects.using("observations").filter(pk=pk, analysis__isnull=True).update(analysis=notes)
    log.info("field reading %s noted", pk)


def _note_worker():
    global _NOTE_THREAD
    while True:
        with _NOTE_LOCK:
            if not _NOTE_QUEUE:
                _NOTE_THREAD = None
                return
            pk = _NOTE_QUEUE.popleft()
        try:
            _write_analysis(pk)
        except Exception:
            log.exception("field reading %s note failed", pk)
        finally:
            close_old_connections()


def schedule_analysis(pk):
    """Ask for the two notes after the response has been sent. One at a time."""
    global _NOTE_THREAD
    if not enabled() or not pk or not getattr(settings, "DEEPGIS_PILOT_MCP_TOKEN", ""):
        return
    with _NOTE_LOCK:
        if pk in _NOTE_QUEUE:
            return
        if len(_NOTE_QUEUE) >= _NOTE_LIMIT:
            _NOTE_QUEUE.popleft()
        _NOTE_QUEUE.append(pk)
        if _NOTE_THREAD is None or not _NOTE_THREAD.is_alive():
            _NOTE_THREAD = threading.Thread(target=_note_worker, name="field-reading-notes", daemon=True)
            _NOTE_THREAD.start()


def _keep(reading):
    saved = _save(reading)
    if saved is None:
        return None
    if saved.camera is not None:
        schedule_sky(saved.pk)
        schedule_adsb(saved.pk)
    if saved.image_relpath and saved.spectrum:
        schedule_analysis(saved.pk)
    return saved



_SKY_QUEUE = deque()
_SKY_LOCK = threading.Lock()
_SKY_THREAD = None
_SKY_LIMIT = 8
_SKY_WEATHER = {}
_SKY_HOURLY = (
    "temperature_2m,relative_humidity_2m,dew_point_2m,surface_pressure,cloud_cover,"
    "wind_speed_10m,wind_direction_10m,shortwave_radiation,direct_radiation,"
    "diffuse_radiation,direct_normal_irradiance"
)


def sun_position(lat, lon, when):
    """Sun azimuth clockwise from north, and elevation above the horizon, in degrees.

    The time is the stored UTC instant. This is the NOAA solar-position approximation.
    """
    when = when.astimezone(timezone.utc)
    jd = when.timestamp() / 86400.0 + 2440587.5
    t = (jd - 2451545.0) / 36525.0
    L0 = (280.46646 + t * (36000.76983 + t * 0.0003032)) % 360.0
    M = (357.52911 + t * (35999.05029 - 0.0001537 * t)) % 360.0
    Mr = math.radians(M)
    C = (
        math.sin(Mr) * (1.914602 - t * (0.004817 + 0.000014 * t))
        + math.sin(2 * Mr) * (0.019993 - 0.000101 * t)
        + math.sin(3 * Mr) * 0.000289
    )
    true_long = L0 + C
    omega = 125.04 - 1934.136 * t
    lam = true_long - 0.00569 - 0.00478 * math.sin(math.radians(omega))
    seconds = 21.448 - t * (46.815 + t * (0.00059 - t * 0.001813))
    eps0 = 23.0 + (26.0 + seconds / 60.0) / 60.0
    eps = eps0 + 0.00256 * math.cos(math.radians(omega))
    decl = math.degrees(math.asin(math.sin(math.radians(eps)) * math.sin(math.radians(lam))))
    e0 = 0.016708634 - t * (0.000042037 + 0.0000001267 * t)
    y = math.tan(math.radians(eps / 2.0)) ** 2
    Lr = math.radians(L0)
    eqtime = 4.0 * math.degrees(
        y * math.sin(2 * Lr)
        - 2 * e0 * math.sin(Mr)
        + 4 * e0 * y * math.sin(Mr) * math.cos(2 * Lr)
        - 0.5 * y * y * math.sin(4 * Lr)
        - 1.25 * e0 * e0 * math.sin(2 * Mr)
    )
    minutes = when.hour * 60.0 + when.minute + when.second / 60.0 + when.microsecond / 6.0e7
    solar = (minutes + eqtime + 4.0 * lon) % 1440.0
    ha = solar / 4.0 - 180.0
    if ha < -180.0:
        ha += 360.0
    latr, declr, har = math.radians(lat), math.radians(decl), math.radians(ha)
    cos_z = math.sin(latr) * math.sin(declr) + math.cos(latr) * math.cos(declr) * math.cos(har)
    cos_z = min(1.0, max(-1.0, cos_z))
    zenith = math.degrees(math.acos(cos_z))
    elevation = 90.0 - zenith
    sin_z = math.sin(math.radians(zenith))
    if sin_z < 1e-6:
        azimuth = 180.0
    else:
        cos_az = (math.sin(latr) * cos_z - math.sin(declr)) / (math.cos(latr) * sin_z)
        cos_az = min(1.0, max(-1.0, cos_az))
        azimuth = math.degrees(math.acos(cos_az))
        azimuth = (azimuth + 180.0) % 360.0 if ha > 0 else (540.0 - azimuth) % 360.0
    return azimuth, elevation


def _atmosphere_from(payload, when):
    hourly = payload.get("hourly") if isinstance(payload, dict) else None
    if not isinstance(hourly, dict):
        return None
    times = hourly.get("time") or []
    hour = when.astimezone(timezone.utc).strftime("%Y-%m-%dT%H")
    idx = next((i for i, stamp in enumerate(times) if str(stamp).startswith(hour)), None)
    if idx is None:
        return None

    def val(name):
        series = hourly.get(name) or []
        if idx >= len(series) or not isinstance(series[idx], (int, float)):
            return None
        return series[idx]

    names = {
        "temperature_c": "temperature_2m",
        "relative_humidity_pct": "relative_humidity_2m",
        "dew_point_c": "dew_point_2m",
        "pressure_hpa": "surface_pressure",
        "cloud_cover_pct": "cloud_cover",
        "wind_speed_mps": "wind_speed_10m",
        "wind_from_deg": "wind_direction_10m",
        "shortwave_wm2": "shortwave_radiation",
        "direct_wm2": "direct_radiation",
        "diffuse_wm2": "diffuse_radiation",
        "dni_wm2": "direct_normal_irradiance",
    }
    out = {"source": "open-meteo", "time": times[idx]}
    for key, name in names.items():
        value = val(name)
        if value is not None:
            out[key] = value
    return out


def _fetch_atmosphere(lat, lon, when):
    hour = when.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
    key = (round(lat, 2), round(lon, 2), hour.strftime("%Y-%m-%dT%H"))
    if key in _SKY_WEATHER:
        return _SKY_WEATHER[key]
    query = urllib.parse.urlencode({
        "latitude": f"{lat:.4f}",
        "longitude": f"{lon:.4f}",
        "hourly": _SKY_HOURLY,
        "start_date": hour.strftime("%Y-%m-%d"),
        "end_date": hour.strftime("%Y-%m-%d"),
        "timezone": "UTC",
        "wind_speed_unit": "ms",
    })
    req = urllib.request.Request(
        "https://api.open-meteo.com/v1/forecast?" + query,
        headers={"User-Agent": "deepgis-field-readings"},
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    parsed = _atmosphere_from(payload, when)
    if parsed is not None:
        try:
            parsed.update(_air_values(lat, lon, when))
        except Exception:
            log.warning("air quality was not fetched")
        _SKY_WEATHER[key] = parsed
    return parsed


def _sky_for(reading):
    if reading.camera is None or reading.captured is None:
        return None
    lat, lon = reading.camera.y, reading.camera.x
    azimuth, elevation = sun_position(lat, lon, reading.captured)
    sky = {
        "sun": {
            "azimuth_deg": round(azimuth, 2),
            "elevation_deg": round(elevation, 2),
            "azimuth_from": "north",
        }
    }
    try:
        sky["atmosphere"] = _fetch_atmosphere(lat, lon, reading.captured)
    except Exception:
        log.warning("field reading %s atmosphere was not fetched", reading.pk)
        sky["atmosphere"] = None
    return sky


def _write_sky(pk):
    from .models import FieldReading

    close_old_connections()
    reading = FieldReading.objects.using("observations").filter(pk=pk).first()
    if reading is None or reading.sky or reading.camera is None:
        return
    sky = _sky_for(reading)
    if sky is None:
        return
    FieldReading.objects.using("observations").filter(pk=pk, sky__isnull=True).update(sky=sky)
    log.info("field reading %s sky stored", pk)


def _sky_worker():
    global _SKY_THREAD
    while True:
        with _SKY_LOCK:
            if not _SKY_QUEUE:
                _SKY_THREAD = None
                return
            pk = _SKY_QUEUE.popleft()
        try:
            _write_sky(pk)
        except Exception:
            log.exception("field reading %s sky failed", pk)
        finally:
            close_old_connections()


def schedule_sky(pk):
    """Sun and atmosphere for one reading, after the live post has returned."""
    global _SKY_THREAD
    if not enabled() or not pk:
        return
    with _SKY_LOCK:
        if pk in _SKY_QUEUE:
            return
        while len(_SKY_QUEUE) >= _SKY_LIMIT:
            _SKY_QUEUE.popleft()
        _SKY_QUEUE.append(pk)
        if _SKY_THREAD is None or not _SKY_THREAD.is_alive():
            _SKY_THREAD = threading.Thread(target=_sky_worker, name="field-reading-sky", daemon=True)
            _SKY_THREAD.start()



_ADSB_QUEUE = deque()
_ADSB_LOCK = threading.Lock()
_ADSB_THREAD = None
_ADSB_LIMIT = 8
_ADSB_CACHE = {}
_ADSB_RADIUS_NM = 25
_ADSB_KEEP = 25
_KT_TO_MPS = 0.514444
_FT_TO_M = 0.3048
_AIR_NAMES = {
    "us_aqi": "us_aqi",
    "pm2_5_ugm3": "pm2_5",
    "pm10_ugm3": "pm10",
    "ozone_ugm3": "ozone",
    "nitrogen_dioxide_ugm3": "nitrogen_dioxide",
    "carbon_monoxide_ugm3": "carbon_monoxide",
    "uv_index": "uv_index",
    "aerosol_optical_depth": "aerosol_optical_depth",
}


def _picked(payload, when, names):
    hourly = payload.get("hourly") if isinstance(payload, dict) else None
    if not isinstance(hourly, dict):
        return {}
    times = hourly.get("time") or []
    hour = when.astimezone(timezone.utc).strftime("%Y-%m-%dT%H")
    idx = next((i for i, stamp in enumerate(times) if str(stamp).startswith(hour)), None)
    if idx is None:
        return {}
    out = {}
    for key, name in names.items():
        series = hourly.get(name) or []
        if idx < len(series) and isinstance(series[idx], (int, float)):
            out[key] = series[idx]
    return out


def _air_values(lat, lon, when):
    hour = when.astimezone(timezone.utc)
    query = urllib.parse.urlencode({
        "latitude": f"{lat:.4f}",
        "longitude": f"{lon:.4f}",
        "hourly": ",".join(_AIR_NAMES.values()),
        "start_date": hour.strftime("%Y-%m-%d"),
        "end_date": hour.strftime("%Y-%m-%d"),
        "timezone": "UTC",
    })
    req = urllib.request.Request(
        "https://air-quality-api.open-meteo.com/v1/air-quality?" + query,
        headers={"User-Agent": "deepgis-field-readings"},
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    return _picked(payload, when, _AIR_NAMES)


def _aircraft_from(payload):
    """Keep every aircraft object the feed returned, nearest first."""
    rows = payload.get("ac") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return None
    aircraft = [item for item in rows if isinstance(item, dict)]
    aircraft.sort(key=lambda item: item["dst"] if isinstance(item.get("dst"), (int, float)) else 1e9)
    return {
        "source": "adsb.lol",
        "radius_nm": _ADSB_RADIUS_NM,
        "aircraft": aircraft,
    }


def aircraft_lines(report):
    """Display rows. alt_baro == "ground" is on the ground; a numeric altitude is airborne."""
    lines = []
    for row in (report or {}).get("aircraft") or []:
        if not isinstance(row, dict):
            continue
        raw = "alt_baro" in row or "flight" in row or "hex" in row
        alt = row.get("alt_baro")
        if alt == "ground":
            status, altitude = "on ground", "ground"
        elif isinstance(alt, (int, float)):
            status, altitude = "airborne", "%.0f ft" % alt
        elif isinstance(row.get("alt_geom"), (int, float)):
            status, altitude = "airborne", "%.0f ft" % row["alt_geom"]
        elif isinstance(row.get("altitude_m"), (int, float)):
            status, altitude = "airborne", "%.0f m" % row["altitude_m"]
        elif raw:
            status, altitude = "unknown", "—"
        else:
            status, altitude = "not stored", "—"
        heading = row.get("track")
        if not isinstance(heading, (int, float)):
            heading = row.get("true_heading") if isinstance(row.get("true_heading"), (int, float)) else row.get("heading_deg")
        if isinstance(row.get("gs"), (int, float)):
            speed = "%.0f kt" % row["gs"]
        elif isinstance(row.get("speed_mps"), (int, float)):
            speed = "%.0f m/s" % row["speed_mps"]
        else:
            speed = "—"
        name = row.get("flight") if raw else row.get("callsign")
        name = " ".join(str(name or "").split()) or str(row.get("hex") or "") or "—"
        dst = row.get("dst")
        lines.append({
            "callsign": name,
            "status": status,
            "altitude": altitude,
            "heading": ("%.0f°" % heading) if isinstance(heading, (int, float)) else "—",
            "speed": speed,
            "distance": ("%.1f nm" % dst) if isinstance(dst, (int, float)) else "—",
            "type": str(row.get("t") or "—"),
        })
    return lines



def _fetch_adsb(lat, lon):
    key = (round(lat, 2), round(lon, 2))
    now = time.monotonic()
    hit = _ADSB_CACHE.get(key)
    if hit and now - hit[0] < 60:
        return hit[1]
    req = urllib.request.Request(
        "https://api.adsb.lol/v2/point/%.5f/%.5f/%d" % (lat, lon, _ADSB_RADIUS_NM),
        headers={"User-Agent": "deepgis-field-readings"},
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        report = _aircraft_from(json.loads(resp.read().decode("utf-8")))
    if report is not None:
        _ADSB_CACHE[key] = (now, report)
    return report


def _write_adsb(pk):
    from .models import FieldReading

    close_old_connections()
    reading = FieldReading.objects.using("observations").filter(pk=pk).first()
    if reading is None or reading.adsb or reading.camera is None:
        return
    try:
        report = _fetch_adsb(reading.camera.y, reading.camera.x)
    except Exception:
        log.warning("field reading %s aircraft list was not fetched", pk)
        return
    if report is None:
        return
    FieldReading.objects.using("observations").filter(pk=pk, adsb__isnull=True).update(adsb=report)
    log.info("field reading %s aircraft stored", pk)


def _adsb_worker():
    global _ADSB_THREAD
    while True:
        with _ADSB_LOCK:
            if not _ADSB_QUEUE:
                _ADSB_THREAD = None
                return
            pk = _ADSB_QUEUE.popleft()
        try:
            _write_adsb(pk)
        except Exception:
            log.exception("field reading %s aircraft failed", pk)
        finally:
            close_old_connections()


def schedule_adsb(pk):
    """Nearby aircraft for one reading, after the live post has returned."""
    global _ADSB_THREAD
    if not enabled() or not pk:
        return
    with _ADSB_LOCK:
        if pk in _ADSB_QUEUE:
            return
        while len(_ADSB_QUEUE) >= _ADSB_LIMIT:
            _ADSB_QUEUE.popleft()
        _ADSB_QUEUE.append(pk)
        if _ADSB_THREAD is None or not _ADSB_THREAD.is_alive():
            _ADSB_THREAD = threading.Thread(target=_adsb_worker, name="field-reading-adsb", daemon=True)
            _ADSB_THREAD.start()
