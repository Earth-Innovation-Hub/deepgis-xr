"""
AI pilot chat for the DeepGIS viewers: Earth (/label/3d/search/), the Moon and
the planets.

The browser posts a natural-language request ("orbit around Tempe Town Lake")
plus the body and the current camera view; this view asks the DREAMS Lab robot LLM (one
`ask_robot_llm` turn on the read-only dreams_mcp, constrained to PILOT_SCHEMA)
for a short reply and a list of camera-drone actions. The actions are
validated and clamped here and executed client-side by the page's existing
takeoff / land / orbit controls, or as data layers (show_layer) fetched from
public sources in the browser (off Earth: drawn from the body's terrain or
elevation map; the sea layers come through pilot_ocean below); place names are geocoded in the browser, off Earth from the
IAU planetary gazetteer.
Nothing here touches a real vehicle.
"""

import json
import math
import re
import time
from urllib.parse import quote

import requests
from django.conf import settings
from django.core.cache import cache
from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_POST

ACTION_TYPES = ("goto", "orbit", "takeoff", "land", "look", "stop", "wait",
                "show_layer", "hide_layer")
# Data layers the page knows how to fetch, draw and cite (LAYERS in hud/pilot.js)
LAYER_KINDS = ("geology", "faults", "flood", "fires", "river", "landcover",
               "soils", "wildlife", "trails", "springs", "mines", "surface_temp", "ndvi",
               "humidity", "air_temp", "sea_temp", "chlorophyll")
# Colour maps a raster layer can be drawn in (COLORMAPS in hud/pilot.js)
COLORMAPS = ("jet", "turbo", "viridis", "inferno", "plasma", "coolwarm", "rdylgn")
MAX_ACTIONS = 8
MAX_HISTORY = 8
MAX_MESSAGE_CHARS = 600
# Now and then the model describes a flight or layer in reply but returns no actions;
# such a reply gets one more try
PROMISE_RE = re.compile(r"\b(show|showing|fly|flying|orbit|orbiting|pull|pulling|bring|bringing|head|heading|"
                        r"zoom|zooming|display|displaying|draw|drawing|load|loading|switch|switching|climb|climbing|"
                        r"land|landing|descend|descending|take off|taking off)\b", re.IGNORECASE)

# Display names; keys match planet-bodies.js and web/geo/nomenclature/<body>.json
BODIES = {
    "earth": "Earth", "moon": "the Moon", "mars": "Mars", "mercury": "Mercury",
    "venus": "Venus", "io": "Io", "europa": "Europa", "ganymede": "Ganymede",
    "callisto": "Callisto", "titan": "Titan", "pluto": "Pluto", "charon": "Charon",
}

# (min, max) per numeric field; out-of-range values are clamped, not rejected.
LIMITS = {
    "alt_m": (5.0, 20000.0),
    "radius_m": (20.0, 20000.0),
    "revolutions": (0.25, 20.0),
    "speed_mps": (1.0, 300.0),
    "pitch_deg": (-90.0, 0.0),
    "heading_deg": (-360.0, 360.0),
    "seconds": (0.0, 120.0),
    "distance_km": (1.0, 500.0),
}
# Weather and sea layers cover bays and regions, wider than any orbit
LAYER_LIMITS = {**LIMITS, "radius_m": (20.0, 200000.0)}
# Off Earth the camera flies at orbiter scale
PLANET_LIMITS = {**LIMITS, "alt_m": (5.0, 500000.0), "radius_m": (20.0, 500000.0),
                 "speed_mps": (1.0, 6000.0)}

PILOT_SCHEMA = {
    "type": "object",
    "properties": {
        "reply": {"type": "string"},
        "actions": {
            "type": "array",
            "maxItems": MAX_ACTIONS,
            "items": {
                "type": "object",
                # Constrained decoding writes keys in this order; with kind before place
                # the model reliably fills in the place for a layer
                "properties": {
                    "type": {"enum": list(ACTION_TYPES)},
                    "kind": {"enum": list(LAYER_KINDS)},
                    "place": {"type": "string"},
                    "colormap": {"enum": list(COLORMAPS)},
                    "lat": {"type": "number"},
                    "lon": {"type": "number"},
                    "radius_m": {"type": "number"},
                    "distance_km": {"type": "number"},
                    "alt_m": {"type": "number"},
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
# Actions go back to the model as history, so they keep the schema's key order: an
# example with place before kind leads the model to skip kind, which drops the layer
FIELD_ORDER = tuple(PILOT_SCHEMA["properties"]["actions"]["items"]["properties"])
LAYER_FIELDS = ("type", "kind", "place", "colormap", "lat", "lon", "radius_m", "distance_km")
# Layers drawn as colour maps; a colour map named in the message applies to them
RASTER_KINDS = ("surface_temp", "ndvi", "humidity", "air_temp", "sea_temp", "chlorophyll")
COLORMAP_WORDS = {**{c: c for c in COLORMAPS}, "rainbow": "jet", "red-yellow-green": "rdylgn"}
PLANET_ACTION_TYPES = tuple(t for t in ACTION_TYPES if t not in ("show_layer", "hide_layer"))
# Layers drawn from each body's terrain or elevation map (PLANET_LAYERS in hud/pilot.js)
PLANET_LAYER_KINDS = {
    "moon": ("elevation", "slope", "contours"),
    "mars": ("elevation",),
    "pluto": ("elevation",),
}
PLANET_LAYER_DOCS = {
    "elevation": "elevation (topography, height) as a colour heat map stretched over the area, with the measured height range",
    "slope": "terrain slope (steepness) as a colour map",
    "contours": "elevation contour lines",
}


def _planet_schema(kinds):
    item = dict(PILOT_SCHEMA["properties"]["actions"]["items"])
    props = {k: v for k, v in item["properties"].items() if k not in ("distance_km", "colormap")}
    if kinds:
        props["type"] = {"enum": list(ACTION_TYPES)}
        props["kind"] = {"enum": list(kinds)}
    else:
        props.pop("kind")
        props["type"] = {"enum": list(PLANET_ACTION_TYPES)}
    item["properties"] = props
    return {**PILOT_SCHEMA, "properties": {
        "reply": {"type": "string"},
        "actions": {**PILOT_SCHEMA["properties"]["actions"], "items": item},
    }}


PLANET_SCHEMA = _planet_schema(())
PLANET_LAYER_SCHEMAS = {body: _planet_schema(kinds) for body, kinds in PLANET_LAYER_KINDS.items()}

SYSTEM_PROMPT = """You are the AI pilot of a virtual camera drone flying over a 3D globe (Cesium) in the DeepGIS viewer. Turn the user's request into a short friendly reply and a list of actions, executed in order.

Actions (all heights are metres ABOVE GROUND):
- goto: fly to a place and hover. Fields: place (a geocodable name) or lat+lon; alt_m (default: frame the place); pitch_deg (camera tilt, -90 straight down, 0 horizon; default -45); heading_deg (0 = north).
- orbit: circle a point with the camera aimed at it. Fields: place or lat+lon (omit both to orbit what the user is looking at now); radius_m (omit to fit the place's size); revolutions (default 1); alt_m; speed_mps (ground speed); clockwise (default false); pitch_deg (omit to aim at the centre).
- takeoff: climb straight up to alt_m above ground (default 100 above the current height).
- land: descend straight down to the ground.
- look: point the camera. Fields: pitch_deg and/or heading_deg.
- stop: stop all motion immediately.
- wait: hover for seconds.
- show_layer: draw a data layer around a place and list what it contains, with sources, in the chat. Fields: kind; place (always set it to the place the user names, e.g. "Bishop, California") or lat+lon; omit both only when the user means where they are looking ("here", "this field", "in view"); radius_m (omit for the kind's default). kind is one of:
  - geology: geologic map units and rock types (default 5 km; worldwide, most detailed in the US)
  - faults: active (Quaternary) faults and earthquake fault lines (15 km; US)
  - flood: FEMA flood zones, flood risk, floodplains (3 km; US)
  - fires: past wildfire perimeters and burn history (20 km; US)
  - river: trace a river or stream downstream from the place and show live streamflow at USGS gauges; use distance_km (default 50) instead of radius_m (US)
  - landcover: land cover / land use mix such as urban, forest, cropland, water (5 km; contiguous US)
  - soils: soil types under a field or site (300 m; US). "This field" or "here" means the point in view: omit place and lat/lon.
  - wildlife: animal and plant observations, species lists (2 km; worldwide, iNaturalist)
  - trails: hiking and walking trails (3 km; worldwide, OpenStreetMap)
  - springs: springs and hot springs (5 km; worldwide, OpenStreetMap)
  - mines: mines, mine shafts, adits and quarries (5 km; worldwide, OpenStreetMap)
  - surface_temp: land surface temperature (how hot the ground is, not the air) as a colour map with the measured range, from the latest clear Landsat thermal image (default: the whole place; worldwide over land, a new image about every 8 days, taken mid-morning). Also for "heat map", "hot spots", "urban heat island" or "thermal" requests.
  - ndvi: vegetation greenness (NDVI) as a colour map, with the share of green vegetation and of bare or built ground, from the latest clear Sentinel-2 image (10 m; worldwide over land, a new image every few days). Also for "vegetation", "greenness", "plant health", "how green" or "tree cover" requests.
  - humidity: current relative humidity of the air as a colour map, with dew point, air temperature and wind at the centre (default: the whole place; worldwide, from weather models).
  - air_temp: current air temperature as a colour map, with humidity and wind at the centre (worldwide, from weather models). Use it for "air temperature", "how hot is it", "weather" or "temperature right now"; use surface_temp for the ground, roofs or pavement.
  - sea_temp: sea surface temperature (water temperature of the ocean, a bay, sea or large lake) as a colour map with the measured range, from the latest daily satellite analysis (1 km; worldwide over water). Any temperature request for a body of water is sea_temp.
  - chlorophyll: chlorophyll-a in the surface water (phytoplankton, algae, ocean colour, productivity) as a colour map, from satellites (2 km; worldwide over water, about two weeks behind).
  For surface_temp, ndvi, humidity, air_temp, sea_temp and chlorophyll, set colormap only if the user names a colour map: jet, turbo, viridis, inferno, plasma, coolwarm or rdylgn ("rainbow" means jet, "red-yellow-green" means rdylgn). These kinds default to the whole place; set radius_m only when the user gives a distance.
- hide_layer: remove a layer. Fields: kind (omit to remove every layer).

Rules:
- Write place names so a geocoder finds them: include the city and state or country, e.g. "Tempe Town Lake, Tempe, Arizona". Use lat/lon only when the user gives coordinates.
- Only fill fields the user asked for or that clearly follow from the request; the viewer picks sensible defaults for the rest.
- An orbit flies to its own start point, so do not add a goto before it unless the user asks to go somewhere first.
- To climb or descend where the drone is, use takeoff (alt_m) or land, not goto; to only turn or tilt the camera, use look.
- Use one show_layer per kind asked for ("trails, springs and mines" is three). Convert distances to radius_m in metres ("within 20 km" is 20000); distance_km is only for river.
- Put show_layer before any orbit or goto of the same place; leave the orbit's radius_m out so the viewer sizes it to the area.
- Never name, list, count or describe what a layer contains in reply (no faults, zones, fires, flows, species, soils, trails, temperatures, humidity, vegetation or chlorophyll values); the viewer lists them from its sourced data.
- If the request is a question or not a flight request, answer it in reply and return no actions.
- Never say in reply that you will show, fly, orbit or move anything unless actions does it; a request repeated from earlier in the conversation gets its actions again.

Examples (actions only):
- "show active faults near Bishop" -> [{"type": "show_layer", "kind": "faults", "place": "Bishop, California"}]
- "flood risk around Tempe Town Lake" -> [{"type": "show_layer", "kind": "flood", "place": "Tempe Town Lake, Tempe, Arizona"}]
- "trace the Salt River downstream and show live flow" -> [{"type": "show_layer", "kind": "river", "place": "Salt River, Arizona"}]
- "past fire perimeters within 20 km" -> [{"type": "show_layer", "kind": "fires", "radius_m": 20000}]
- "what soils are under this field?" -> [{"type": "show_layer", "kind": "soils"}]
- "orbit Hayden Butte and show geology within 5 km" -> [{"type": "show_layer", "kind": "geology", "place": "Hayden Butte, Tempe, Arizona", "radius_m": 5000}, {"type": "orbit", "place": "Hayden Butte, Tempe, Arizona"}]
- "orbit all of Tempe and show surface temperature as a jet colormap" -> [{"type": "show_layer", "kind": "surface_temp", "place": "Tempe, Arizona", "colormap": "jet"}, {"type": "orbit", "place": "Tempe, Arizona"}]
- "how green is Phoenix?" -> [{"type": "show_layer", "kind": "ndvi", "place": "Phoenix, Arizona"}]
- "what's the humidity around Tucson" -> [{"type": "show_layer", "kind": "humidity", "place": "Tucson, Arizona"}]
- "sea surface temperature of Monterey Bay in jet" -> [{"type": "show_layer", "kind": "sea_temp", "place": "Monterey Bay, California", "colormap": "jet"}]
- "show chlorophyll and water temperature off Santa Cruz" -> [{"type": "show_layer", "kind": "chlorophyll", "place": "Santa Cruz, California"}, {"type": "show_layer", "kind": "sea_temp", "place": "Santa Cruz, California"}]
- reply is one or two short sentences describing what you are about to do. Never claim to control a real aircraft."""

PLANET_PROMPT = """You are the AI pilot of a virtual camera spacecraft flying over a 3D globe of {body} (Cesium) in the DeepGIS viewer. Turn the user's request into a short friendly reply and a list of actions, executed in order.

Actions (all heights are metres ABOVE GROUND):
- goto: fly to a place and hover. Fields: place (a feature name) or lat+lon; alt_m (default: frame the place); pitch_deg (camera tilt, -90 straight down, 0 horizon; default -45); heading_deg (0 = north).
- orbit: circle a point with the camera aimed at it. Fields: place or lat+lon (omit both to orbit what the user is looking at now); radius_m (omit to fit the feature's size); revolutions (default 1); alt_m; speed_mps (ground speed); clockwise (default false); pitch_deg (omit to aim at the centre).
- takeoff: climb straight up to alt_m above ground (default 5 km above the current height).
- land: descend straight down to the surface.
- look: point the camera. Fields: pitch_deg and/or heading_deg.
- stop: stop all motion immediately.
- wait: hover for seconds.
{layer_actions}
Rules:
- place is the feature's official IAU name as in the Gazetteer of Planetary Nomenclature, without the body or feature type unless it is part of the name: "Tycho", "Mare Imbrium", "Olympus Mons", "Valles Marineris". On the Moon the Apollo landing sites are "Apollo 11" to "Apollo 17". Use lat/lon (planetocentric, east-positive degrees) only when the user gives coordinates.
- This is orbital scale: features are kilometres to hundreds of kilometres across, so think in km (alt_m 50000 is 50 km). Omit alt_m and radius_m unless the user gives them; the viewer sizes them to the feature.
- Only fill fields the user asked for or that clearly follow from the request; the viewer picks sensible defaults for the rest.
- An orbit flies to its own start point, so do not add a goto before it unless the user asks to go somewhere first.
- To climb or descend where the camera is, use takeoff (alt_m) or land, not goto; to only turn or tilt the camera, use look.
{layer_rules}
- If the request is a question or not a flight request, answer it briefly in reply and return no actions; never invent feature facts you are unsure of.

Examples (actions only):
- "orbit Tycho twice" -> [{{"type": "orbit", "place": "Tycho", "revolutions": 2}}]
- "fly to the Apollo 15 site at 5 km" -> [{{"type": "goto", "place": "Apollo 15", "alt_m": 5000}}]
- "go to 18.4 N 77.7 E and look at the horizon" -> [{{"type": "goto", "lat": 18.4, "lon": 77.7, "pitch_deg": 0}}]
- reply is one or two short sentences describing what you are about to do. Never claim to control a real spacecraft."""

PLANET_LAYER_RULES = """- Use show_layer for any request to show, colour or map elevation, height, topography{slope_words}; "heat map" or "colormap" means elevation unless another kind is named. Set place as for goto, or omit place and lat/lon for "here" or "in view"; set radius_m only when the user gives a distance.
- Put show_layer before an orbit or goto of the same place.
- Never state heights, ranges or slopes in reply; the viewer measures them and lists them with their source.
- Example: "orbit Tycho and show elevation as a colormap" -> [{{"type": "show_layer", "kind": "elevation", "place": "Tycho"}}, {{"type": "orbit", "place": "Tycho"}}]"""


def planet_prompt(body):
    kinds = PLANET_LAYER_KINDS.get(body, ())
    if kinds:
        docs = "\n".join(f"  - {k}: {PLANET_LAYER_DOCS[k]}" for k in kinds)
        actions = ("- show_layer: draw a data layer. Fields: kind; place or lat+lon (omit both for the area in view); "
                   "radius_m (omit to fit the feature). kind is one of:\n" + docs +
                   "\n- hide_layer: remove a layer. Fields: kind (omit to remove every layer).\n")
        slope_words = ", slope or contours" if "slope" in kinds else ""
        rules = PLANET_LAYER_RULES.format(slope_words=slope_words)
    else:
        actions, rules = "", "- There are no data layers here; if asked for one, say so in reply."
    return PLANET_PROMPT.format(body=BODIES[body], layer_actions=actions, layer_rules=rules)


def _num(v, field, limits=LIMITS):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        return None
    lo, hi = limits[field]
    return max(lo, min(hi, float(v)))


def clean_actions(raw, body="earth"):
    """Keep known action types and fields, clamp numbers, drop bad coordinates."""
    if body == "earth":
        types, limits, kinds = ACTION_TYPES, LIMITS, LAYER_KINDS
    else:
        kinds = PLANET_LAYER_KINDS.get(body, ())
        types, limits = (ACTION_TYPES if kinds else PLANET_ACTION_TYPES), PLANET_LIMITS
    out = []
    for a in raw if isinstance(raw, list) else []:
        if not isinstance(a, dict) or a.get("type") not in types:
            continue
        act = {"type": a["type"]}
        lim = LAYER_LIMITS if body == "earth" and act["type"] == "show_layer" else limits
        place = a.get("place")
        if isinstance(place, str) and place.strip():
            act["place"] = place.strip()[:120]
        lat, lon = a.get("lat"), a.get("lon")
        if (isinstance(lat, (int, float)) and isinstance(lon, (int, float))
                and not isinstance(lat, bool) and not isinstance(lon, bool)
                and -90 <= lat <= 90 and -180 <= lon <= 180):
            act["lat"], act["lon"] = float(lat), float(lon)
        for field in lim:
            v = _num(a.get(field), field, lim)
            if v is not None:
                act[field] = v
        if isinstance(a.get("clockwise"), bool):
            act["clockwise"] = a["clockwise"]
        if act["type"] in ("show_layer", "hide_layer"):
            kind = a.get("kind")
            if kind in kinds:
                act["kind"] = kind
            elif kind is not None or act["type"] == "show_layer":
                continue
            if act["type"] == "show_layer" and body == "earth" and a.get("colormap") in COLORMAPS:
                act["colormap"] = a["colormap"]
            if kind != "river" and "distance_km" in act:
                km = act.pop("distance_km")
                act.setdefault("radius_m", _num(km * 1000, "radius_m", lim))
        else:
            act.pop("distance_km", None)
        fields = (LAYER_FIELDS if act["type"] == "show_layer" else ("type", "kind") if act["type"] == "hide_layer"
                  else FIELD_ORDER)
        act = {k: act[k] for k in FIELD_ORDER if k in act and k in fields}
        if act["type"] == "show_layer":
            # An orbit runs until its laps end; draw the layer before it, not after
            i = len(out)
            while i and out[i - 1]["type"] == "orbit":
                i -= 1
            out.insert(i, act)
        else:
            out.append(act)
        if len(out) == MAX_ACTIONS:
            break
    return out


def _clean_history(raw, body="earth"):
    hist = []
    for h in raw if isinstance(raw, list) else []:
        if (isinstance(h, dict) and h.get("role") in ("user", "assistant")
                and isinstance(h.get("content"), str)):
            content = h["content"]
            if h["role"] == "assistant":
                # Earlier plans as this server would send them, in schema key order
                try:
                    plan = json.loads(content)
                except ValueError:
                    plan = None
                if isinstance(plan, dict) and "actions" in plan:
                    content = json.dumps({"reply": str(plan.get("reply", "")),
                                          "actions": clean_actions(plan["actions"], body)})
            hist.append({"role": h["role"], "content": content[:2000]})
    return hist[-MAX_HISTORY:]


def named_colormap(message):
    """The one colour map the message names, if exactly one."""
    found = {cm for word, cm in COLORMAP_WORDS.items()
             if re.search(rf"\b{re.escape(word)}\b", message, re.IGNORECASE)}
    return found.pop() if len(found) == 1 else None


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


def _rate_limited(user_id, scope="pilot", per_min=None):
    key = f"{scope}-rate:{user_id}:{int(time.time() // 60)}"
    if cache.add(key, 1, timeout=90):
        return False
    try:
        return cache.incr(key) > (per_min or settings.DEEPGIS_PILOT_RATE_PER_MIN)
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
    # The event-stream reply has no charset, which requests would read as Latin-1
    resp.encoding = "utf-8"
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
                             "login_url": "/label/admin/login/"}, status=401)
    if not settings.DEEPGIS_PILOT_MCP_TOKEN:
        return JsonResponse({"error": "The AI pilot is not configured on this server."}, status=503)
    try:
        data = json.loads(request.body)
    except ValueError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)
    message = data.get("message") if isinstance(data, dict) else None
    if not isinstance(message, str) or not message.strip():
        return JsonResponse({"error": "Empty message"}, status=400)
    body = data.get("body", "earth")
    if not isinstance(body, str) or body not in BODIES:
        return JsonResponse({"error": "Unknown body"}, status=400)
    if _rate_limited(request.user.pk):
        return JsonResponse({"error": "Too many requests; wait a minute."}, status=429)

    view_line = _describe_view(data.get("view"))
    prompt = (view_line + "\n" if view_line else "") + "User: " + message.strip()[:MAX_MESSAGE_CHARS]
    timeout = settings.DEEPGIS_PILOT_TIMEOUT_SEC
    args = {
        "prompt": prompt,
        "system_prompt": SYSTEM_PROMPT if body == "earth" else planet_prompt(body),
        "json_schema": PILOT_SCHEMA if body == "earth" else PLANET_LAYER_SCHEMAS.get(body, PLANET_SCHEMA),
        "history": _clean_history(data.get("history"), body),
        "temperature": 0.2,
        "max_tokens": 800,
        "timeout_sec": timeout,
    }
    for attempt in range(2):
        try:
            out = call_mcp_tool("ask_robot_llm", args, timeout + 10)
        except (requests.RequestException, RuntimeError, ValueError, KeyError) as e:
            return JsonResponse({"error": f"AI pilot unavailable: {type(e).__name__}"}, status=502)
        plan = out.get("json") if isinstance(out, dict) else None
        if not isinstance(plan, dict):
            return JsonResponse({"error": "The AI pilot returned no plan; try rephrasing."}, status=502)
        reply = plan.get("reply") if isinstance(plan.get("reply"), str) else ""
        actions = clean_actions(plan.get("actions"), body)
        if actions or not PROMISE_RE.search(reply):
            break
    cmap = named_colormap(message) if body == "earth" else None
    for a in actions:
        if cmap and a["type"] == "show_layer" and a.get("kind") in RASTER_KINDS:
            a["colormap"] = cmap
    actions = [{k: a[k] for k in FIELD_ORDER if k in a} for a in actions]
    return JsonResponse({
        "reply": reply.strip()[:1000],
        "actions": actions,
        "model": out.get("model", ""),
        "duration_sec": out.get("duration_sec"),
    })


# Gridded sea data for the sea_temp and chlorophyll layers, from NOAA ERDDAP servers,
# which send no CORS headers, so the page cannot read them itself.
# res is the grid spacing in degrees; lat_desc grids store latitude north to south.
OCEAN_DATASETS = {
    "sea_temp": {"url": "https://coastwatch.pfeg.noaa.gov/erddap/griddap/jplMURSST41",
                 "var": "analysed_sst", "res": 0.01, "altitude": False, "lat_desc": False},
    "chlorophyll": {"url": "https://coastwatch.noaa.gov/erddap/griddap/noaacwNPPN20S3ASCIDINEOF2kmDaily",
                    "var": "chlor_a", "res": 0.02, "altitude": True, "lat_desc": True},
}
OCEAN_MAX_SPAN_DEG = 10.0
OCEAN_MAX_CELLS = 160  # per side; coarser areas are subsampled
OCEAN_RATE_PER_MIN = 20
OCEAN_CACHE_SEC = 3 * 3600


def ocean_query(ds, south, north, west, east):
    """ERDDAP griddap query for the latest day over the box, subsampled to OCEAN_MAX_CELLS."""
    stride = max(1, math.ceil(max(north - south, east - west) / ds["res"] / OCEAN_MAX_CELLS))
    lat = f"({north}):{stride}:({south})" if ds["lat_desc"] else f"({south}):{stride}:({north})"
    q = f"{ds['var']}[(last)]" + ("[(0.0)]" if ds["altitude"] else "") + f"[{lat}][({west}):{stride}:({east})]"
    return f"{ds['url']}.json?{quote(q, safe='():')}", stride


def ocean_grid(rows):
    """ERDDAP JSON rows (time, [altitude], lat, lon, value) as a grid with rows south to north."""
    lats = sorted({r[-3] for r in rows})
    lons = sorted({r[-2] for r in rows})
    li, lj = {v: i for i, v in enumerate(lats)}, {v: j for j, v in enumerate(lons)}
    values = [[None] * len(lons) for _ in lats]
    for r in rows:
        v = r[-1]
        if isinstance(v, (int, float)) and math.isfinite(v):
            values[li[r[-3]]][lj[r[-2]]] = round(v, 3)
    return lats, lons, values


@require_GET
def pilot_ocean(request):
    if not request.user.is_authenticated:
        return JsonResponse({"error": "login_required", "login_url": "/label/admin/login/"}, status=401)
    kind = request.GET.get("kind")
    ds = OCEAN_DATASETS.get(kind)
    if not ds:
        return JsonResponse({"error": "Unknown sea layer"}, status=400)
    try:
        south, north, west, east = (round(float(request.GET[k]), 2) for k in ("south", "north", "west", "east"))
    except (KeyError, ValueError):
        return JsonResponse({"error": "south, north, west and east are required"}, status=400)
    if not (-90 <= south < north <= 90 and -180 <= west < east <= 180
            and north - south <= OCEAN_MAX_SPAN_DEG and east - west <= OCEAN_MAX_SPAN_DEG):
        return JsonResponse({"error": f"The area must be within {OCEAN_MAX_SPAN_DEG:g} degrees on each side"}, status=400)

    key = f"pilot-ocean:{kind}:{south}:{north}:{west}:{east}"
    cached = cache.get(key)
    if cached:
        return JsonResponse(cached)
    if _rate_limited(request.user.pk, "pilot-ocean", OCEAN_RATE_PER_MIN):
        return JsonResponse({"error": "Too many requests; wait a minute."}, status=429)
    url, stride = ocean_query(ds, south, north, west, east)
    try:
        for attempt in range(2):
            # ERDDAP servers are busy now and then; a server error or timeout gets one retry
            try:
                resp = requests.get(url, timeout=30)
            except (requests.ConnectionError, requests.Timeout):
                if attempt:
                    raise
                continue
            if resp.status_code < 500 or attempt:
                break
        if resp.status_code >= 400:
            return JsonResponse({"error": f"NOAA ERDDAP returned HTTP {resp.status_code}"}, status=502)
        rows = resp.json()["table"]["rows"]
        lats, lons, values = ocean_grid(rows)
        when = rows[0][0]
    except (requests.RequestException, ValueError, KeyError, IndexError, TypeError) as e:
        return JsonResponse({"error": f"NOAA ERDDAP is unavailable right now ({type(e).__name__})"}, status=502)
    out = {"time": when, "lat": lats, "lon": lons, "values": values,
           "res": ds["res"] * stride, "dataset": ds["url"].rsplit("/", 1)[1]}
    cache.set(key, out, OCEAN_CACHE_SEC)
    return JsonResponse(out)
