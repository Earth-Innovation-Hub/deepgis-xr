"""
Acquisition advice for a field robot's spectrometer.

A robot that posts a "spectrum" product (views/vehicles.py) gets advice back in the reply
to that post: what its own exposure control should aim for. Nothing is sent to a robot
otherwise, and the robot clamps and may ignore what it gets. The advice is

    target     how close to full scale the brightest pixels of the band should sit
    band       the wavelengths that must not clip, [lo, hi] nm
    window_ms  how long the robot may co-add scans for one reading

It comes from two layers. rule_policy is geometry and runs on every post: where the sun
is relative to the camera at the robot's place and time, and how fast the robot drives
across the patch the instrument sees. Now and then (the robot has moved or turned,
started or stopped, the sun has climbed, or ADVICE_TTL_SEC has passed) the lab's vision
model is shown the robot's latest camera frame with those facts and asked to adjust the
rules' answer for what is in the patch. Its answer is clamped: while the robot moves it
may only make the rules' answer more cautious, since what it saw is already behind the
robot. The model is never in the loop that sets an integration time: that loop runs on
the robot after every reading.

DEEPGIS_ACQUISITION_ADVICE is "llm" (both layers, the default), "rules" or "off".
DEEPGIS_ACQUISITION_MODEL names the vision model to ask, from those the lab's bridge
offers; empty asks whichever one it is serving.
"""

import base64
import logging
import math
import threading
from datetime import datetime, timezone

import requests
from django.conf import settings
from django.core.cache import caches

from . import pilot

log = logging.getLogger(__name__)

ADVICE_TTL_SEC = 1800            # the model's judgement is reused this long while nothing changes
ADVICE_MIN_INTERVAL_SEC = 120    # and it is asked at most this often for one robot
ADVICE_ROBOT_TTL_SEC = 180       # how long the robot may keep using an advice it was sent
ADVICE_SHOW_SEC = 120            # how long the last advice is kept for viewers
NIGHT_SUN_DEG = -3.0             # below this there is no daylight to judge: rules only
MOVING_MPS = 0.3
FACING_SUN_DEG = 60.0            # the camera "faces the sun" within this of its azimuth...
LOW_SUN_DEG = 40.0               # ...while the sun is lower than this
SMEAR_SHARE = 0.25               # a reading may cover this share of the patch's width in motion
TARGET_LIMITS = (0.5, 0.9)
WINDOW_LIMITS_MS = (30.0, 400.0)
BANDS = {"full": None, "red_edge": (650.0, 800.0)}  # None: the instrument's whole range
HEADING_CHANGE_DEG = 45.0        # the model is asked again when the robot has turned this much,
MOVED_M = 15.0                   # driven this far,
SUN_CHANGE_DEG = 5.0             # or the sun has climbed or sunk this much

ADVICE_SCHEMA = {
    "type": "object",
    "properties": {
        "patch": {"type": "string"},
        "target_peak": {"type": "number"},
        "band": {"type": "string", "enum": list(BANDS)},
        "window_ms": {"type": "number"},
        "reason": {"type": "string"},
    },
    "required": ["patch", "target_peak", "band", "window_ms", "reason"],
}
ADVICE_PROMPT = """You choose the exposure policy for a point spectrometer on a field rover. The rover sets its own integration time after every reading; you set what it aims for. The image is the rover's latest camera frame, a real photograph; the spectrometer looks along the camera's axis and averages a patch around the point given in the request. Answer with JSON only.
- patch: a few words on what fills that patch (for example "sunlit gravel", "tree foliage, half in shade", "open sky").
- target_peak (0.5 to 0.9): how close to full scale the brightest pixels of the band should sit. Nearer 0.9 gives a cleaner spectrum, but the next reading clips if the scene gets brighter. About 0.85 for a parked rover and an evenly lit patch. About 0.7 when the rover moves, or wind moves leaves in and out of the sun. 0.55 to 0.65 when the patch mixes direct sun and shade, or holds sky, water glint, glass, metal or other glare, or the camera looks toward a low sun.
- band: "full" keeps the whole spectrum unclipped and is the default. "red_edge" (650-800 nm) only when green vegetation clearly fills most of the patch: the green peak may then clip slightly so that the red edge and the oxygen band are measured at their best.
- window_ms (30 to 400): how long the rover co-adds scans for one reading. Never above the baseline's value while the rover moves; shorter when the image shows the scene changing fast.
- reason: one sentence of at most 25 words naming what in the image or the readings decided it.
Start from the baseline in the request and change it only for a reason you can see in the image or the readings."""


def sun_position(t, lat, lon):
    """(elevation deg, azimuth deg clockwise from north, local solar time in hours) at unix
    time t. The Astronomical Almanac's low-precision formulas, good to a few tenths of a
    degree; no refraction."""
    d = t / 86400.0 - 10957.5  # days since 2000-01-01 12:00 UTC
    g = math.radians((357.529 + 0.98560028 * d) % 360.0)
    ecliptic = math.radians((280.459 + 0.98564736 * d) % 360.0 + 1.915 * math.sin(g) + 0.020 * math.sin(2 * g))
    tilt = math.radians(23.439 - 0.00000036 * d)
    ra = math.atan2(math.cos(tilt) * math.sin(ecliptic), math.cos(ecliptic))
    dec = math.asin(math.sin(tilt) * math.sin(ecliptic))
    sidereal = (18.697374558 + 24.06570982441908 * d) % 24.0
    hour_angle = math.radians((sidereal * 15.0 + lon) % 360.0) - ra
    la = math.radians(lat)
    elevation = math.asin(math.sin(la) * math.sin(dec) + math.cos(la) * math.cos(dec) * math.cos(hour_angle))
    azimuth = math.atan2(-math.sin(hour_angle),
                         math.tan(dec) * math.cos(la) - math.sin(la) * math.cos(hour_angle))
    return (math.degrees(elevation), math.degrees(azimuth) % 360.0,
            (math.degrees(hour_angle) / 15.0 + 12.0) % 24.0)


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def context(vid, data, t):
    """What is known about the robot and its reading at time t, or None without a position.
    The pose is the one sent with the latest camera frame if there is one, else the live pose."""
    live = caches["live"]
    pose = (live.get(f"frame_info:{vid}") or {}).get("pose") or live.get(f"vehicle:{vid}")
    if not pose or not _num(pose.get("lat")) or not _num(pose.get("lon")):
        return None
    elevation, azimuth, solar_time = sun_position(t, pose["lat"], pose["lon"])
    ctx = {"lat": pose["lat"], "lon": pose["lon"], "t": t,
           "speed_mps": pose["speed_mps"] if _num(pose.get("speed_mps")) else 0.0,
           "sun_elevation_deg": round(elevation, 1), "sun_azimuth_deg": round(azimuth, 1),
           "solar_time_h": round(solar_time, 2)}
    if _num(pose.get("heading_deg")):
        ctx["heading_deg"] = pose["heading_deg"] % 360.0
        # where the sun is from the camera's axis: 0 ahead, +90 to the right, 180 behind
        ctx["sun_relative_deg"] = round((azimuth - ctx["heading_deg"] + 180.0) % 360.0 - 180.0, 1)
    laser, footprint = data.get("laser") or {}, data.get("footprint") or {}
    if "range_m" in laser:
        ctx["range_m"] = laser["range_m"]
    if "diameter_m" in footprint:
        ctx["patch_m"] = footprint["diameter_m"]
    return ctx


def rule_policy(ctx):
    """The policy from geometry alone: {target, band, window_ms, why}."""
    moving = ctx["speed_mps"] >= MOVING_MPS
    target, window, why = 0.85, WINDOW_LIMITS_MS[1], []
    if ctx["sun_elevation_deg"] < NIGHT_SUN_DEG:
        return {"target": target, "band": "full", "window_ms": window,
                "why": "the sun is down: longest window, no daylight to protect"}
    if moving:
        target = 0.7
        why.append(f"moving at {ctx['speed_mps']:.1f} m/s")
        if "patch_m" in ctx:  # do not drive across more than a share of the patch in one reading
            window = min(window, max(WINDOW_LIMITS_MS[0], 1000.0 * SMEAR_SHARE * ctx["patch_m"] / ctx["speed_mps"]))
            why.append(f"patch {ctx['patch_m']:.1f} m across")
    else:
        why.append("parked")
    rel = ctx.get("sun_relative_deg")
    if rel is not None and abs(rel) <= FACING_SUN_DEG and 0.0 <= ctx["sun_elevation_deg"] <= LOW_SUN_DEG:
        target = min(target, 0.6)
        why.append(f"camera faces a sun {ctx['sun_elevation_deg']:.0f} deg high")
    elif rel is not None:
        why.append("sun behind the camera" if abs(rel) >= 120.0 else "sun to the side")
    return {"target": target, "band": "full", "window_ms": round(window), "why": ", ".join(why)}


def clean_judgement(raw, base, moving):
    """The model's answer inside the limits, or None if it is not usable. For a moving
    robot the answer may only be more cautious than the rules' (base)."""
    if not isinstance(raw, dict) or not _num(raw.get("target_peak")):
        return None
    window = raw.get("window_ms") if _num(raw.get("window_ms")) else base["window_ms"]
    text = lambda v, n: " ".join(v.split())[:n] if isinstance(v, str) else ""  # noqa: E731
    return {
        "target": round(min(base["target"] if moving else TARGET_LIMITS[1], max(TARGET_LIMITS[0], raw["target_peak"])), 2),
        "band": raw["band"] if raw.get("band") in BANDS and not moving else base["band"],
        "window_ms": round(min(base["window_ms"] if moving else WINDOW_LIMITS_MS[1], max(WINDOW_LIMITS_MS[0], window))),
        "patch": text(raw.get("patch"), 80),
        "reason": text(raw.get("reason"), 200),
    }


def _sun_words(ctx):
    text = (f"the sun is {ctx['sun_elevation_deg']:.0f} degrees above the horizon at azimuth "
            f"{ctx['sun_azimuth_deg']:.0f}")
    rel = ctx.get("sun_relative_deg")
    if rel is None:
        return text + "; the camera's heading is unknown"
    side = "right" if rel >= 0 else "left"
    if abs(rel) <= FACING_SUN_DEG:
        where = f"{abs(rel):.0f} degrees to the {side} of the camera's axis: the camera looks toward it (back-lit scene)"
    elif abs(rel) >= 120.0:
        where = f"{abs(rel):.0f} degrees to the {side} of the camera's axis: behind the camera (front-lit scene)"
    else:
        where = f"{abs(rel):.0f} degrees to the {side} of the camera's axis (side-lit scene)"
    return f"{text}, {where}"


def judgement_prompt(ctx, data, base):
    when = datetime.fromtimestamp(ctx["t"], timezone.utc)
    hours = int(ctx["solar_time_h"])
    lines = [f"Time: {when:%Y-%m-%d %H:%M} UTC, local solar time {hours:02d}:{int((ctx['solar_time_h'] - hours) * 60):02d}. "
             f"Sun: {_sun_words(ctx)}.",
             f"Rover: {'moving at %.1f m/s' % ctx['speed_mps'] if ctx['speed_mps'] >= MOVING_MPS else 'parked'}."]
    fp = data.get("footprint") or {}
    where = "the centre of the image"
    if "u" in fp and "v" in fp:
        where = f"a point {fp['u'] * 100:.0f}% from the left and {fp['v'] * 100:.0f}% from the top of the image"
    text = f"The spectrometer looks at about {where}"
    if "patch_m" in ctx and "range_m" in ctx:
        text += f"; the laser measures {ctx['range_m']:.1f} m to it and the patch is about {ctx['patch_m']:.1f} m across"
    if "frac_w" in fp:
        text += f", about {min(fp['frac_w'], 1.0) * 100:.0f}% of the image width"
    lines.append(text + ".")
    acq = data.get("acquisition") or {}
    now = []
    if "integration_ms" in data:
        scans = int(acq.get("scans", 1))
        now.append(f"{scans} scan{'s' if scans != 1 else ''} of {data['integration_ms']:g} ms")
    if "peak_frac" in data:
        now.append(f"brightest pixel at {data['peak_frac'] * 100:.0f}% of full scale")
    if "clipped_pct" in data:
        now.append(f"{data['clipped_pct']:.0f}% of the visible range clipped")
    if now:
        lines.append("Its last reading: " + ", ".join(now) + ".")
    if data.get("notes"):
        lines.append("The instrument's notes on that reading: " + " ".join(data["notes"]))
    lines.append(f"Baseline from the geometry: target_peak {base['target']:.2f}, band {base['band']}, "
                 f"window_ms {base['window_ms']:.0f} ({base['why']}).")
    return "\n".join(lines)


def judge(vid, ctx, data, base):
    """Ask the vision model once and keep its cleaned answer; a failure leaves the rules in charge."""
    live = caches["live"]
    jpeg = live.get(f"frame:{vid}")
    if not jpeg:
        return
    timeout = settings.DEEPGIS_PILOT_TIMEOUT_SEC
    args = {"image": base64.b64encode(jpeg).decode(), "prompt": judgement_prompt(ctx, data, base),
            "system_prompt": ADVICE_PROMPT, "json_schema": ADVICE_SCHEMA, "temperature": 0.1,
            "max_tokens": 300, "timeout_sec": timeout}
    model = getattr(settings, "DEEPGIS_ACQUISITION_MODEL", "")
    if model:  # otherwise whichever vision model the lab's bridge is serving
        args["model"] = model
    try:
        out = pilot.call_mcp_tool("describe_image", args, timeout + 10)
    except (requests.RequestException, RuntimeError, ValueError, KeyError) as e:
        log.warning("acquisition advice for %s: model unavailable (%s)", vid, type(e).__name__)
        return
    judged = clean_judgement(out.get("json") if isinstance(out, dict) else None, base, ctx["speed_mps"] >= MOVING_MPS)
    if judged is None:
        log.warning("acquisition advice for %s: unusable answer", vid)
        return
    judged.update(model=str(out.get("model", ""))[:80], ctx=ctx)
    live.set(f"advice_llm:{vid}", judged, ADVICE_TTL_SEC)
    log.info("acquisition advice for %s: target %.2f, band %s, window %d ms (%s)", vid, judged["target"],
             judged["band"], judged["window_ms"], judged["reason"])


def run_async(fn):
    threading.Thread(target=fn, daemon=True).start()


def _changed(then, ctx):
    """Has the situation the model judged changed enough to ask it again?"""
    if (then["speed_mps"] >= MOVING_MPS) != (ctx["speed_mps"] >= MOVING_MPS):
        return True
    north = math.radians(ctx["lat"] - then["lat"]) * 6371000.0
    east = math.radians(ctx["lon"] - then["lon"]) * 6371000.0 * math.cos(math.radians(ctx["lat"]))
    if math.hypot(north, east) >= MOVED_M:
        return True
    if abs(then["sun_elevation_deg"] - ctx["sun_elevation_deg"]) >= SUN_CHANGE_DEG:
        return True
    if ("heading_deg" in then) != ("heading_deg" in ctx):
        return True
    if "heading_deg" in ctx and abs((then["heading_deg"] - ctx["heading_deg"] + 180.0) % 360.0 - 180.0) >= HEADING_CHANGE_DEG:
        return True
    a, b = then.get("range_m"), ctx.get("range_m")
    return (a is None) != (b is None) or (a is not None and not 0.5 <= a / max(b, 0.01) <= 2.0)


def advise(vid, data, t):
    """The advice to return with a vehicle's spectrum product (cleaned data), or None."""
    mode = getattr(settings, "DEEPGIS_ACQUISITION_ADVICE", "llm")
    if mode not in ("llm", "rules"):
        return None
    ctx = context(vid, data, t)
    if ctx is None:
        return None
    base = rule_policy(ctx)
    live = caches["live"]
    judged = live.get(f"advice_llm:{vid}") if mode == "llm" else None
    stale = judged is not None and _changed(judged["ctx"], ctx)
    if (mode == "llm" and settings.DEEPGIS_PILOT_MCP_TOKEN and ctx["sun_elevation_deg"] >= NIGHT_SUN_DEG
            and (judged is None or stale) and live.add(f"advice_try:{vid}", 1, ADVICE_MIN_INTERVAL_SEC)):
        run_async(lambda: judge(vid, ctx, data, base))
    policy = {"target": base["target"], "band": base["band"], "window_ms": base["window_ms"],
              "source": "deepgis:rules", "reason": base["why"]}
    if judged is not None and not stale:
        policy.update(target=judged["target"], band=judged["band"],
                      window_ms=min(judged["window_ms"], base["window_ms"]),
                      source="deepgis:llm", reason=judged["reason"])
    lo, hi = BANDS[policy["band"]] or (data["wl0"], data["wl0"] + data["dwl"] * len(data["counts"]))
    advice = {"target": policy["target"], "band": [lo, hi], "window_ms": policy["window_ms"],
              "ttl_s": ADVICE_ROBOT_TTL_SEC, "source": policy["source"], "reason": policy["reason"]}
    shown = {**advice, "t": t, "sun": {k: ctx[k] for k in ("sun_elevation_deg", "sun_azimuth_deg",
                                                             "sun_relative_deg", "solar_time_h") if k in ctx}}
    if policy["source"] == "deepgis:llm":
        shown.update(patch=judged["patch"], model=judged["model"])
    live.set(f"advice:{vid}", shown, ADVICE_SHOW_SEC)
    return advice


def live_advice(vid, t):
    """The last advice sent to a vehicle, with its age, for viewers; None if there is none."""
    shown = caches["live"].get(f"advice:{vid}")
    if not shown:
        return None
    out = {k: v for k, v in shown.items() if k != "t"}
    out["age_sec"] = round(max(0.0, t - shown["t"]), 1)
    return out
