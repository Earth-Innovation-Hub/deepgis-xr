"""
Robot registry and nearby search: simulations today, field robots later.

A robot's id is its callsign ("kestrel", "badger", "otter"): lowercase, hyphenated, unique,
and independent of the world or container it runs in. Its publisher posts as that id
(views/vehicles.py), the DREAMS Lab MCP serves it as robot=<id>, and the AI pilot follows it
by that id. The world it is in ("Locutus world", "Tempe Town Lake world") is its site, so a
query for a world finds every robot in it. Students' OpenUAV sims are openuav-<username>.

core.Vehicle holds each robot's identity (name, platform, airframe, site, aliases, its
MCP id) and last-known position; core.VehiclePosition holds a downsampled track. The
latest pose at full rate stays in the "live" cache. record_pose writes the database at
most every TRACK_SEC per robot, so ingest stays cheap on SQLite.
"""

import logging
import math
import random
import re
import time
from datetime import timedelta

from django.conf import settings
from django.core.cache import caches
from django.utils import timezone

from deepgis_xr.apps.core.models import Vehicle, VehiclePosition, VehicleType

log = logging.getLogger(__name__)

IDS_KEY = "vehicles:ids"
TRACK_SEC = 10  # database writes per robot at most this often
TRACK_MIN_MOVE_M = 2.0  # a track point needs this much movement...
TRACK_HEARTBEAT_SEC = 300  # ...or this long since the last one
TRACK_KEEP_DAYS = 14
REGISTRY_SEC = 30

# platform -> (VehicleType name, category, icon)
PLATFORMS = {
    "multirotor": ("Multirotor", "DRONE", "\U0001F681"),
    "fixed_wing": ("Fixed-wing", "DRONE", "\u2708\ufe0f"),
    "vtol": ("VTOL", "DRONE", "\U0001F6E9\ufe0f"),
    "rover": ("Rover", "GROUND", "\U0001F699"),
    "legged": ("Legged robot", "ROBOT", "\U0001F916"),
    "boat": ("Boat", "MARINE", "\U0001F6A4"),
    "submarine": ("Underwater vehicle", "MARINE", "\U0001F30A"),
    "other": ("Other", "OTHER", "\U0001F4CD"),
}
# words in a query -> the platforms they mean
PLATFORM_ALIASES = {"multicopter": "multirotor"}  # older platform names stored or sent
# "drone" means any uncrewed robot here: aerial, ground, surface or underwater
PLATFORM_WORDS = {
    "drone": tuple(p for p in PLATFORMS if p != "other"), "robot": tuple(p for p in PLATFORMS if p != "other"),
    "uav": ("multirotor", "fixed_wing", "vtol"),
    "aircraft": ("multirotor", "fixed_wing", "vtol"), "aerial": ("multirotor", "fixed_wing", "vtol"),
    "quadcopter": ("multirotor",), "copter": ("multirotor",), "multicopter": ("multirotor",),
    "quadrotor": ("multirotor",), "hexacopter": ("multirotor",),
    "plane": ("fixed_wing", "vtol"), "fixed-wing": ("fixed_wing",), "vtol": ("vtol",),
    "rover": ("rover",), "ugv": ("rover", "legged"), "ground": ("rover", "legged"),
    "legged": ("legged",), "dog": ("legged",),
    "boat": ("boat",), "usv": ("boat",), "vessel": ("boat", "submarine"), "ship": ("boat",),
    "marine": ("boat", "submarine"), "water": ("boat", "submarine"),
    "submarine": ("submarine",), "auv": ("submarine",), "underwater": ("submarine",),
}
COMPASS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")

_registry = {"t": -1e9, "data": {}}


def canonical_id(text):
    """"Kestrel", "the badger", "alice's sim" -> "kestrel", "badger", "alice-sim"; "" if empty."""
    if not isinstance(text, str):
        return ""
    s = text.strip().lower()
    s = re.sub(r"^(?:the|a|an)\s+", "", s)
    s = re.sub(r"[\u2019']s\b", "", s)
    s = re.sub(r"[\s_/]+", "-", s)
    s = re.sub(r"[^a-z0-9.-]", "", s)
    return re.sub(r"-{2,}", "-", s).strip("-.")[:60]


def platform_set(text):
    """The platforms a word or platform name means ("drones" -> aerial ones); None if none."""
    key = canonical_id(text).rstrip("s") if text else ""
    if not key:
        return None
    key = PLATFORM_ALIASES.get(key, key)
    if key.replace("-", "_") in PLATFORMS:
        return {key.replace("-", "_")}
    return set(PLATFORM_WORDS.get(key, ())) or None


def _vehicle_info(v):
    info = {
        "id": v.vehicle_id, "name": v.name, "kind": v.kind or "sim",
        "platform": PLATFORM_ALIASES.get(v.platform, v.platform) or "other", "airframe": v.airframe,
        "site": v.site,
        "aliases": [a for a in (v.aliases or []) if isinstance(a, str)],
        "mcp_robot": v.mcp_robot, "description": v.description,
    }
    if v.current_latitude is not None and v.current_longitude is not None:
        info["last"] = {"lat": float(v.current_latitude), "lon": float(v.current_longitude),
                        "alt_amsl": v.current_altitude, "heading_deg": v.current_heading,
                        "seen": v.last_update.timestamp() if v.last_update else None}
    return info


def registry(refresh=False):
    """{id: identity and last-known position} from core.Vehicle, cached per process."""
    if refresh or time.monotonic() - _registry["t"] > REGISTRY_SEC:
        try:
            _registry["data"] = {v.vehicle_id: _vehicle_info(v) for v in Vehicle.objects.all()}
        except Exception:
            log.exception("robot registry unavailable")
        _registry["t"] = time.monotonic()
    return _registry["data"]


def _matches(info, key):
    if key in (info["id"], canonical_id(info.get("name"))):
        return True
    return key in {canonical_id(a) for a in info.get("aliases", ())}


def field_id_free(vid, refresh=False):
    """True if a field robot may enroll as vid: no other robot answers to it by id, name or
    alias (an enrolled field robot keeps its own id)."""
    for info in registry(refresh).values():
        if _matches(info, vid) and not (info["id"] == vid and info.get("kind") == "field"):
            return False
    return True


def mentions_robot(text):
    """True when text names a known robot by id or alias ("chase kestrel"), as a whole word."""
    if not isinstance(text, str) or not text.strip():
        return False
    words = canonical_id(text)
    if not words:
        return False
    padded = f"-{words}-"
    for vid, info in registry().items():
        for name in (vid, *info.get("aliases", ())):
            key = canonical_id(name)
            if key and f"-{key}-" in padded:
                return True
    return False


def resolve(name, live_ids=()):
    """The robot id a user's name for it means, or None: an id, a display name, an alias
    ("the rover"), or a username for an OpenUAV sim ("alice", "alice's sim")."""
    key = canonical_id(name)
    if not key:
        return None
    reg = registry()
    known = set(reg) | set(live_ids)
    trimmed = re.sub(r"-(?:openuav-)?(?:sim|simulation|drone|robot|multirotor|rover|boat)$", "", key)
    for k in dict.fromkeys((key, trimmed)):
        if k in known:
            return k
        for vid, info in reg.items():
            if _matches(info, k):
                return vid
        prefix = settings.VEHICLE_FLEET_PREFIX
        if prefix and prefix + k in known:
            return prefix + k
    return None


def _world_key(site):
    """"Locutus world (digital twin, ...)" -> "locutus"; "" when the site names no world."""
    m = re.match(r"\s*(.+?)\s+world\b", site or "", re.IGNORECASE)
    return canonical_id(m.group(1)) if m else ""


def locate(place):
    """{"lat", "lon", "label"} for a place that names a robot ("badger") or a world
    ("Locutus world"), which no geocoder knows: the robot's position, or the middle of
    the world's robots. None for anything else."""
    key = canonical_id(place)
    if not key:
        return None
    vid = resolve(place)
    # A world only when named as one: "Tempe Town Lake" is also a real place for the geocoder
    world = re.sub(r"-(?:world|twin|digital-twin|sim|simulation)$", "", key)
    if not vid and world == key:
        return None
    rows = [r for r in nearby(include_offline=True, limit=500) if "lat" in r and "lon" in r]
    hits = ([r for r in rows if r["id"] == vid] if vid
            else [r for r in rows if world and _world_key(r.get("site")) == world])
    if not hits:
        return None
    names = ", ".join(r.get("name") or r["id"] for r in hits)
    return {"lat": sum(r["lat"] for r in hits) / len(hits), "lon": sum(r["lon"] for r in hits) / len(hits),
            "label": names if vid else f"{place.strip()} ({names})"}


def _distance_m(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371008.8 * math.asin(min(1.0, math.sqrt(a)))


def _bearing_deg(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def _vehicle_type(platform):
    name, category, icon = PLATFORMS.get(platform, PLATFORMS["other"])
    vt, _ = VehicleType.objects.get_or_create(name=name, defaults={"category": category, "icon_symbol": icon})
    return vt


def _new_vehicle(vid, pose):
    fleet = settings.VEHICLE_FLEET_PREFIX and vid.startswith(settings.VEHICLE_FLEET_PREFIX)
    platform = pose.get("platform") or ("multirotor" if fleet else "other")
    owner = None
    if fleet:
        from django.contrib.auth import get_user_model
        owner = get_user_model().objects.filter(username=vid[len(settings.VEHICLE_FLEET_PREFIX):]).first()
    return Vehicle.objects.create(
        vehicle_id=vid, name=pose.get("name") or vid, vehicle_type=_vehicle_type(platform),
        kind=pose.get("kind") or "sim", platform=platform, owner=owner,
        site="OpenUAV" if fleet else pose.get("site", ""))


def record_pose(vid, pose):
    """Keep core.Vehicle's last-known position (every TRACK_SEC) and a track point when the
    robot has moved TRACK_MIN_MOVE_M, or every TRACK_HEARTBEAT_SEC while it stays put."""
    live = caches["live"]
    key = f"vehicle_db:{vid}"
    t = time.time()
    last = live.get(key) or {}
    if t - last.get("t", 0) < TRACK_SEC:
        return
    track = last.get("track")
    add_point = (track is None or t - track["t"] >= TRACK_HEARTBEAT_SEC
                 or _distance_m(track["lat"], track["lon"], pose["lat"], pose["lon"]) >= TRACK_MIN_MOVE_M)
    if add_point:
        track = {"t": t, "lat": pose["lat"], "lon": pose["lon"]}
    live.set(key, {"t": t, "track": track}, 3600)

    v = Vehicle.objects.filter(vehicle_id=vid).first() or _new_vehicle(vid, pose)
    v.current_latitude, v.current_longitude = pose["lat"], pose["lon"]
    v.current_altitude = pose.get("alt_amsl")
    v.current_heading = pose.get("heading_deg")
    v.current_speed = pose.get("speed_mps")
    v.status = "ACTIVE"
    v.save(update_fields=["current_latitude", "current_longitude", "current_altitude",
                          "current_heading", "current_speed", "status", "last_update"])
    if add_point:
        VehiclePosition.objects.create(
            vehicle=v, latitude=pose["lat"], longitude=pose["lon"], altitude=pose.get("alt_amsl"),
            heading=pose.get("heading_deg"), speed=pose.get("speed_mps"),
            sensor_data={k: pose[k] for k in ("up_m", "armed", "landed") if k in pose})
        if random.random() < 0.01:
            cutoff = timezone.now() - timedelta(days=TRACK_KEEP_DAYS)
            VehiclePosition.objects.filter(vehicle=v, timestamp__lt=cutoff).delete()


def mark_offline(ids):
    if ids:
        Vehicle.objects.filter(vehicle_id__in=list(ids), status="ACTIVE").update(status="INACTIVE")


def live_poses(t=None):
    """Latest pose of every robot reporting now, with age_sec and its frame, freshest first.
    t is the clock the poses' received times came from (default time.time())."""
    live = caches["live"]
    ids = live.get(IDS_KEY) or []
    found = live.get_many([f"vehicle:{vid}" for vid in ids])
    poses = list(found.values())
    if len(found) < len(ids):  # sims come and go; forget the ones whose pose expired
        live.set(IDS_KEY, sorted(p["id"] for p in poses), None)
        try:
            mark_offline(set(ids) - {p["id"] for p in poses})
        except Exception:
            log.exception("could not mark robots offline")
    frames = live.get_many([f"frame_info:{p['id']}" for p in poses])
    t = time.time() if t is None else t
    out = []
    for pose in poses:
        pose = dict(pose)
        pose["age_sec"] = round(max(0.0, t - pose.pop("received")), 2)
        info = frames.get(f"frame_info:{pose['id']}")
        if info:
            pose["frame"] = {"seq": info["seq"], "w": info["w"], "h": info["h"],
                             "age_sec": round(max(0.0, t - info["received"]), 2)}
        out.append(pose)
    out.sort(key=lambda p: p["age_sec"])
    return out


IDENTITY = ("name", "kind", "platform", "airframe", "site", "aliases", "mcp_robot")


def enrich(pose, reg=None):
    """A live pose with the robot's registry identity (its registry name wins)."""
    info = (reg if reg is not None else registry()).get(pose["id"])
    out = dict(pose)
    if info:
        out.update({k: info[k] for k in IDENTITY if info.get(k) not in (None, "", [])})
    out.setdefault("name", pose["id"])
    return out


def nearby(lat=None, lon=None, radius_m=0.0, platform="", query="", include_offline=False, limit=50):
    """Robots live now (and with include_offline, known ones with a last-known position),
    optionally within radius_m of (lat, lon), of a platform, or matching a name; live first,
    then nearest. Each gets distance_m, bearing_deg and direction when a point is given."""
    reg = registry()
    rows = {}
    for pose in live_poses():
        row = enrich(pose, reg)
        row["online"] = True
        rows[pose["id"]] = row
    if include_offline:
        t = time.time()
        for vid, info in reg.items():
            if vid in rows:
                continue
            row = {"id": vid, **{k: info[k] for k in IDENTITY if info.get(k) not in (None, "", [])},
                   "online": False}
            last = info.get("last")
            if last:
                row.update({k: last[k] for k in ("lat", "lon", "alt_amsl", "heading_deg") if last[k] is not None})
                if last.get("seen"):
                    row["last_seen_sec"] = round(max(0.0, t - last["seen"]))
            rows[vid] = row
    platforms = platform_set(platform) if platform else None
    key = canonical_id(query)
    words = platform_set(query) if key else None
    out = []
    for row in rows.values():
        if platforms and row.get("platform") not in platforms:
            continue
        if key and not (words and row.get("platform") in words):
            info = reg.get(row["id"]) or {"id": row["id"], "name": row.get("name"), "aliases": []}
            text = canonical_id(" ".join(str(row.get(k) or "") for k in ("id", "name", "airframe", "site")))
            if not (_matches(info, key) or key in text):
                continue
        if lat is not None and lon is not None and "lat" in row:
            d = _distance_m(lat, lon, row["lat"], row["lon"])
            if radius_m and d > radius_m:
                continue
            b = _bearing_deg(lat, lon, row["lat"], row["lon"])
            row.update(distance_m=round(d, 1), bearing_deg=round(b), direction=COMPASS[round(b / 45) % 8])
        elif lat is not None and radius_m:
            continue
        out.append(row)
    out.sort(key=lambda r: (not r["online"], r.get("distance_m", float("inf")), r["id"]))
    return out[:limit]
