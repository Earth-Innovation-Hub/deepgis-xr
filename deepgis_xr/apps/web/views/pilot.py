"""
AI pilot chat for the DeepGIS Search viewer (/label/3d/search/).

The browser posts a natural-language request ("orbit around Tempe Town Lake")
plus the current camera view; this view asks the DREAMS Lab robot LLM (one
`ask_robot_llm` turn on the read-only dreams_mcp, constrained to PILOT_SCHEMA)
for a short reply and a list of camera-drone actions. The actions are
validated and clamped here and executed client-side by the page's existing
takeoff / land / orbit controls; place names are geocoded in the browser with
Cesium Ion. Nothing here touches a real vehicle.
"""

import json
import math
import time

import requests
from django.conf import settings
from django.core.cache import cache
from django.http import JsonResponse
from django.views.decorators.http import require_POST

ACTION_TYPES = ("goto", "orbit", "takeoff", "land", "look", "stop", "wait",
                "show_geology", "hide_geology")
MAX_ACTIONS = 8
MAX_HISTORY = 8
MAX_MESSAGE_CHARS = 600

# (min, max) per numeric field; out-of-range values are clamped, not rejected.
LIMITS = {
    "alt_m": (5.0, 20000.0),
    "radius_m": (20.0, 20000.0),
    "revolutions": (0.25, 20.0),
    "speed_mps": (1.0, 300.0),
    "pitch_deg": (-90.0, 0.0),
    "heading_deg": (-360.0, 360.0),
    "seconds": (0.0, 120.0),
}

PILOT_SCHEMA = {
    "type": "object",
    "properties": {
        "reply": {"type": "string"},
        "actions": {
            "type": "array",
            "maxItems": MAX_ACTIONS,
            "items": {
                "type": "object",
                "properties": {
                    "type": {"enum": list(ACTION_TYPES)},
                    "place": {"type": "string"},
                    "lat": {"type": "number"},
                    "lon": {"type": "number"},
                    "alt_m": {"type": "number"},
                    "radius_m": {"type": "number"},
                    "revolutions": {"type": "number"},
                    "speed_mps": {"type": "number"},
                    "clockwise": {"type": "boolean"},
                    "pitch_deg": {"type": "number"},
                    "heading_deg": {"type": "number"},
                    "seconds": {"type": "number"},
                },
                "required": ["type"],
            },
        },
    },
    "required": ["reply", "actions"],
}

SYSTEM_PROMPT = """You are the AI pilot of a virtual camera drone flying over a 3D globe (Cesium) in the DeepGIS viewer. Turn the user's request into a short friendly reply and a list of actions, executed in order.

Actions (all heights are metres ABOVE GROUND):
- goto: fly to a place and hover. Fields: place (a geocodable name) or lat+lon; alt_m (default: frame the place); pitch_deg (camera tilt, -90 straight down, 0 horizon; default -45); heading_deg (0 = north).
- orbit: circle a point with the camera aimed at it. Fields: place or lat+lon (omit both to orbit what the user is looking at now); radius_m (omit to fit the place's size); revolutions (default 1); alt_m; speed_mps (ground speed); clockwise (default false); pitch_deg (omit to aim at the centre).
- takeoff: climb straight up to alt_m above ground (default 100 above the current height).
- land: descend straight down to the ground.
- look: point the camera. Fields: pitch_deg and/or heading_deg.
- stop: stop all motion immediately.
- wait: hover for seconds.
- show_geology: mark the mapped geologic features (sourced data for the Phoenix and Tempe area) within radius_m of a place and list them in the chat. Fields: place or lat+lon (omit both for the point in view); radius_m (default 5000).
- hide_geology: remove the geology markers.

Rules:
- Write place names so a geocoder finds them: include the city and state or country, e.g. "Tempe Town Lake, Tempe, Arizona". Use lat/lon only when the user gives coordinates.
- Only fill fields the user asked for or that clearly follow from the request; the viewer picks sensible defaults for the rest.
- An orbit flies to its own start point, so do not add a goto before it unless the user asks to go somewhere first.
- To climb or descend where the drone is, use takeoff (alt_m) or land, not goto; to only turn or tilt the camera, use look.
- For geology, rocks or landforms around a place, put show_geology first, then any orbit of the same place; leave the orbit's radius_m out so the viewer sizes it to the area.
- Never name, list or describe geologic features in reply; the viewer lists them from its sourced data.
- If the request is a question or not a flight request, answer it in reply and return no actions.
- reply is one or two short sentences describing what you are about to do. Never claim to control a real aircraft."""


def _num(v, field):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        return None
    lo, hi = LIMITS[field]
    return max(lo, min(hi, float(v)))


def clean_actions(raw):
    """Keep known action types and fields, clamp numbers, drop bad coordinates."""
    out = []
    for a in raw if isinstance(raw, list) else []:
        if not isinstance(a, dict) or a.get("type") not in ACTION_TYPES:
            continue
        act = {"type": a["type"]}
        place = a.get("place")
        if isinstance(place, str) and place.strip():
            act["place"] = place.strip()[:120]
        lat, lon = a.get("lat"), a.get("lon")
        if (isinstance(lat, (int, float)) and isinstance(lon, (int, float))
                and not isinstance(lat, bool) and not isinstance(lon, bool)
                and -90 <= lat <= 90 and -180 <= lon <= 180):
            act["lat"], act["lon"] = float(lat), float(lon)
        for field in LIMITS:
            v = _num(a.get(field), field)
            if v is not None:
                act[field] = v
        if isinstance(a.get("clockwise"), bool):
            act["clockwise"] = a["clockwise"]
        out.append(act)
        if len(out) == MAX_ACTIONS:
            break
    return out


def _clean_history(raw):
    hist = []
    for h in raw if isinstance(raw, list) else []:
        if (isinstance(h, dict) and h.get("role") in ("user", "assistant")
                and isinstance(h.get("content"), str)):
            hist.append({"role": h["role"], "content": h["content"][:2000]})
    return hist[-MAX_HISTORY:]


def _describe_view(view):
    """One line about the current camera for the prompt; empty if unusable."""
    if not isinstance(view, dict):
        return ""

    def f(key, src=view):
        v = src.get(key) if isinstance(src, dict) else None
        return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) else None

    lat, lon, agl, hdg = f("lat"), f("lon"), f("height_agl"), f("heading_deg")
    if lat is None or lon is None:
        return ""
    line = f"Current view: camera at lat {lat:.5f}, lon {lon:.5f}"
    if agl is not None:
        line += f", {agl:.0f} m above ground"
    if hdg is not None:
        line += f", heading {hdg:.0f} deg"
    tgt = view.get("target")
    tlat, tlon = f("lat", tgt), f("lon", tgt)
    if tlat is not None and tlon is not None:
        line += f"; looking at lat {tlat:.5f}, lon {tlon:.5f}"
    return line + "."


def _rate_limited(user_id):
    key = f"pilot-rate:{user_id}:{int(time.time() // 60)}"
    if cache.add(key, 1, timeout=90):
        return False
    try:
        return cache.incr(key) > settings.DEEPGIS_PILOT_RATE_PER_MIN
    except ValueError:
        return False


def call_mcp_tool(name, arguments, timeout):
    """One stateless MCP tools/call over streamable HTTP; returns the tool result."""
    resp = requests.post(
        settings.DEEPGIS_PILOT_MCP_URL,
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
              "params": {"name": name, "arguments": arguments}},
        headers={"Authorization": f"Bearer {settings.DEEPGIS_PILOT_MCP_TOKEN}",
                 "Accept": "application/json, text/event-stream"},
        timeout=timeout,
    )
    resp.raise_for_status()
    body = resp.text
    if "text/event-stream" in resp.headers.get("Content-Type", ""):
        body = next((ln[6:] for ln in body.splitlines() if ln.startswith("data: ")), "")
    msg = json.loads(body)
    if "error" in msg:
        raise RuntimeError(msg["error"].get("message", "MCP error"))
    result = msg["result"]
    text = (result.get("content") or [{}])[0].get("text", "")
    if result.get("isError"):
        raise RuntimeError(text or "tool error")
    structured = (result.get("structuredContent") or {}).get("result")
    return structured if structured is not None else json.loads(text)


@require_POST
def pilot_chat(request):
    if not request.user.is_authenticated:
        return JsonResponse({"error": "login_required",
                             "login_url": "/label/admin/login/?next=/label/3d/search/"}, status=401)
    if not settings.DEEPGIS_PILOT_MCP_TOKEN:
        return JsonResponse({"error": "The AI pilot is not configured on this server."}, status=503)
    try:
        data = json.loads(request.body)
    except ValueError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)
    message = data.get("message") if isinstance(data, dict) else None
    if not isinstance(message, str) or not message.strip():
        return JsonResponse({"error": "Empty message"}, status=400)
    if _rate_limited(request.user.pk):
        return JsonResponse({"error": "Too many requests; wait a minute."}, status=429)

    view_line = _describe_view(data.get("view"))
    prompt = (view_line + "\n" if view_line else "") + "User: " + message.strip()[:MAX_MESSAGE_CHARS]
    timeout = settings.DEEPGIS_PILOT_TIMEOUT_SEC
    try:
        out = call_mcp_tool("ask_robot_llm", {
            "prompt": prompt,
            "system_prompt": SYSTEM_PROMPT,
            "json_schema": PILOT_SCHEMA,
            "history": _clean_history(data.get("history")),
            "temperature": 0.2,
            "max_tokens": 800,
            "timeout_sec": timeout,
        }, timeout + 10)
    except (requests.RequestException, RuntimeError, ValueError, KeyError) as e:
        return JsonResponse({"error": f"AI pilot unavailable: {type(e).__name__}"}, status=502)

    plan = out.get("json") if isinstance(out, dict) else None
    if not isinstance(plan, dict):
        return JsonResponse({"error": "The AI pilot returned no plan; try rephrasing."}, status=502)
    reply = plan.get("reply") if isinstance(plan.get("reply"), str) else ""
    return JsonResponse({
        "reply": reply.strip()[:1000],
        "actions": clean_actions(plan.get("actions")),
        "model": out.get("model", ""),
        "duration_sec": out.get("duration_sec"),
    })
