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
elevation map; the sea layers come through pilot_ocean below, the lidar
terrain through pilot_topo); place names are geocoded in the browser, off Earth from the
IAU planetary gazetteer. describe_view sends one frame of the canvas to pilot_describe,
which asks the same model what it sees (dreams_mcp's describe_image). follow_vehicle
(Earth only) rides the camera on a live vehicle's pose from views/vehicles.py.
Nothing here touches a real vehicle.
"""

import base64
import json
import math
import os
import re
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from urllib.parse import quote

import numpy as np
import requests
from osgeo import gdal, osr
from django.conf import settings
from django.core.cache import cache
from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_POST

ACTION_TYPES = ("goto", "orbit", "takeoff", "land", "look", "stop", "wait",
                "show_layer", "hide_layer", "describe_view", "follow_vehicle")
# Vehicles report positions on Earth only
EARTH_ONLY_TYPES = ("show_layer", "hide_layer", "follow_vehicle")
FOLLOW_VIEWS = ("camera", "chase")
VEHICLE_NAME = re.compile(r"[a-z0-9_.-]{1,40}")
# Data layers the page knows how to fetch, draw and cite (LAYERS in hud/pilot.js)
LAYER_KINDS = ("geology", "faults", "flood", "fires", "river", "landcover",
               "soils", "wildlife", "trails", "springs", "mines", "surface_temp", "ndvi",
               "humidity", "air_temp", "sea_temp", "chlorophyll", "elevation", "slope", "contours",
               "lidar_dem", "topo_datasets")
# Colour maps a raster layer can be drawn in (COLORMAPS in hud/pilot.js)
COLORMAPS = ("jet", "turbo", "viridis", "inferno", "plasma", "coolwarm", "rdylgn")
# The model now and then writes coordinates as a place: "lat 37.41, lon -118.52"
COORD_PLACE = re.compile(r"\s*(?:lat(?:itude)?\s*)?(-?\d{1,2}(?:\.\d+)?)\s*,?\s*(?:lon(?:gitude)?\s*)?(-?\d{1,3}(?:\.\d+)?)\s*",
                         re.IGNORECASE)
MAX_ACTIONS = 8
MAX_HISTORY = 8
MAX_MESSAGE_CHARS = 600
# Now and then the model describes a flight or layer in reply but returns no actions;
# such a reply gets one more try
PROMISE_RE = re.compile(r"\b(show|showing|fly|flying|orbit|orbiting|pull|pulling|bring|bringing|head|heading|"
                        r"zoom|zooming|display|displaying|draw|drawing|load|loading|switch|switching|climb|climbing|"
                        r"land|landing|descend|descending|take off|taking off|"
                        r"take a look|describe|describing|analy[sz]e|analy[sz]ing|"
                        r"follow|following|sync|syncing|ride along|riding along)\b", re.IGNORECASE)

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
                    "vehicle": {"type": "string"},
                    "view": {"enum": list(FOLLOW_VIEWS)},
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
FOLLOW_FIELDS = ("type", "vehicle", "view")
# Layers drawn as colour maps; a colour map named in the message applies to them
RASTER_KINDS = ("surface_temp", "ndvi", "humidity", "air_temp", "sea_temp", "chlorophyll", "elevation", "lidar_dem")
COLORMAP_WORDS = {**{c: c for c in COLORMAPS}, "rainbow": "jet", "red-yellow-green": "rdylgn"}
PLANET_ACTION_TYPES = tuple(t for t in ACTION_TYPES if t not in EARTH_ONLY_TYPES)
PLANET_LAYER_ACTION_TYPES = tuple(t for t in ACTION_TYPES if t != "follow_vehicle")
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
    props = {k: v for k, v in item["properties"].items()
             if k not in ("distance_km", "colormap", "vehicle", "view")}
    if kinds:
        props["type"] = {"enum": list(PLANET_LAYER_ACTION_TYPES)}
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
  - elevation: terrain height (topography, relief) as a colour map over the ground with the measured height range, from Cesium World Terrain (default: the whole place; worldwide, about 30 m detail, finer in places). Also for "how high" or "height map" requests.
  - slope: terrain steepness as a colour map, from Cesium World Terrain (worldwide).
  - contours: elevation contour lines, from Cesium World Terrain (worldwide).
  - lidar_dem: high-resolution lidar or drone terrain (down to 0.5 m) as shaded relief coloured by height, with height and slope figures, from OpenTopography surveys stored on DeepGIS (default 2 km; so far only around Bishop, California: the Volcanic Tablelands fault scarps, the White Mountains fault zone and the Bishop Tuff). Use it for "lidar", "high resolution terrain", "hillshade", "shaded relief", "bare earth", "DEM" or "fault scarp" requests; use elevation for terrain anywhere else.
  - topo_datasets: which lidar, drone and elevation datasets OpenTopography has around a place, with their footprints, dates and links (default 15 km; mostly the US). Also for "what lidar is there" or "OpenTopography data" requests.
  For surface_temp, ndvi, humidity, air_temp, sea_temp, chlorophyll, elevation and lidar_dem, set colormap only if the user names a colour map: jet, turbo, viridis, inferno, plasma, coolwarm or rdylgn ("rainbow" means jet, "red-yellow-green" means rdylgn). These kinds default to the whole place; set radius_m only when the user gives a distance.
- hide_layer: remove a layer. Fields: kind (omit to remove every layer).
- describe_view: look at the camera image and list what is visible in it, in the chat. No fields. Use it whenever the user asks what is in view or asks to look at, describe, analyse or list what the camera sees ("what do you see?", "describe the scene", "do a visual analysis of the view"). Put it last, after any goto, orbit, look or show_layer that sets up the view.
- follow_vehicle: lock the camera to a live vehicle that reports its position to DeepGIS, and keep following until stop. Vehicles: the digital twin "locutus" (also "the twin"), and students' OpenUAV simulations, named after their username. Fields: vehicle (its name, only if the user names one or says "the twin"); view: "camera" to see through the vehicle's own gimbal camera (the default, also for "sync", "what the sim/drone camera sees", "ride along") or "chase" to follow it from behind and above ("chase", "follow behind", "show me the drone").

Rules:
- Write place names so a geocoder finds them: include the city and state or country, e.g. "Tempe Town Lake, Tempe, Arizona". Use lat/lon only when the user gives coordinates.
- Only fill fields the user asked for or that clearly follow from the request; the viewer picks sensible defaults for the rest.
- An orbit flies to its own start point, so do not add a goto before it unless the user asks to go somewhere first.
- To climb or descend where the drone is, use takeoff (alt_m) or land, not goto; to only turn or tilt the camera, use look.
- Use one show_layer per kind asked for ("trails, springs and mines" is three). Convert distances to radius_m in metres ("within 20 km" is 20000); distance_km is only for river.
- Put show_layer before any orbit or goto of the same place; leave the orbit's radius_m out so the viewer sizes it to the area.
- Never name, list, count or describe what a layer contains in reply (no faults, zones, fires, flows, species, soils, trails, temperatures, humidity, vegetation, chlorophyll, heights, slopes or datasets); the viewer lists them from its sourced data.
- The request starts with the drone's telemetry ("Current view") and, for questions about the surroundings, the places OpenStreetMap names around the point in view. Answer where-and-which questions from them in reply with no actions ("what dam are we looking at?", "where are we?", "what lake is that?", "how high are we?", "which way are we facing?"): name the best match nearest the point in view, say it is from the map and the drone's position, and give height, heading or distance from the telemetry when asked. Never name a place that is not listed; if none fits, say so and use describe_view.
- A question about what is visible or what the scene looks like is a describe_view request. Never describe the view yourself in reply; say you will take a look.
- A request to follow, sync with, ride along with or chase the simulation, the twin, the sim drone or a vehicle is a follow_vehicle request. Never state where a vehicle is or what it is doing in reply; the viewer reports it.
- If the request is any other question or not a flight request, answer it in reply and return no actions.
- Never say in reply that you will show, fly, orbit, look at or move anything unless actions does it; a request repeated from earlier in the conversation gets its actions again.

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
- "elevation map of Mount Whitney" -> [{"type": "show_layer", "kind": "elevation", "place": "Mount Whitney, California"}]
- "show the lidar hillshade of the fault scarps in the Volcanic Tablelands" -> [{"type": "show_layer", "kind": "lidar_dem", "place": "Volcanic Tablelands, Bishop, California"}]
- "what lidar does OpenTopography have near Bishop?" -> [{"type": "show_layer", "kind": "topo_datasets", "place": "Bishop, California"}]
- "do a visual analysis of the view and list what you observe" -> [{"type": "describe_view"}]
- "what dam are we looking at?" -> [] (reply names the listed dam nearest the point in view)
- "orbit this dam" -> [{"type": "orbit"}] ("this", "that" and "here" mean the point in view: leave out place and lat/lon)
- "fly to Hayden Butte and tell me what you see" -> [{"type": "goto", "place": "Hayden Butte, Tempe, Arizona"}, {"type": "describe_view"}]
- "sync the view with the OpenUAV sim camera" -> [{"type": "follow_vehicle", "view": "camera"}]
- "chase the locutus drone" -> [{"type": "follow_vehicle", "vehicle": "locutus", "view": "chase"}]
- "follow the twin and tell me what its camera sees" -> [{"type": "follow_vehicle", "vehicle": "locutus", "view": "camera"}, {"type": "describe_view"}]
- "chase alice's OpenUAV sim" -> [{"type": "follow_vehicle", "vehicle": "alice", "view": "chase"}]
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
- describe_view: look at the camera image and list what is visible in it, in the chat. No fields. Use it whenever the user asks what is in view or asks to look at, describe, analyse or list what the camera sees ("what do you see?", "describe the scene", "do a visual analysis of the view"). Put it last, after any goto, orbit, look or show_layer that sets up the view.
{layer_actions}
Rules:
- place is the feature's official IAU name as in the Gazetteer of Planetary Nomenclature, without the body or feature type unless it is part of the name: "Tycho", "Mare Imbrium", "Olympus Mons", "Valles Marineris". On the Moon the Apollo landing sites are "Apollo 11" to "Apollo 17". Use lat/lon (planetocentric, east-positive degrees) only when the user gives coordinates.
- This is orbital scale: features are kilometres to hundreds of kilometres across, so think in km (alt_m 50000 is 50 km). Omit alt_m and radius_m unless the user gives them; the viewer sizes them to the feature.
- Only fill fields the user asked for or that clearly follow from the request; the viewer picks sensible defaults for the rest.
- An orbit flies to its own start point, so do not add a goto before it unless the user asks to go somewhere first.
- To climb or descend where the camera is, use takeoff (alt_m) or land, not goto; to only turn or tilt the camera, use look.
{layer_rules}
- The request starts with the camera's telemetry ("Current view"); answer where-are-we, how-high and which-way questions from it in reply with no actions.
- A question about what is visible is a describe_view request. Never describe the view yourself in reply; say you will take a look.
- If the request is any other question or not a flight request, answer it briefly in reply and return no actions; never invent feature facts you are unsure of.

Examples (actions only):
- "orbit Tycho twice" -> [{{"type": "orbit", "place": "Tycho", "revolutions": 2}}]
- "fly to the Apollo 15 site at 5 km" -> [{{"type": "goto", "place": "Apollo 15", "alt_m": 5000}}]
- "go to 18.4 N 77.7 E and look at the horizon" -> [{{"type": "goto", "lat": 18.4, "lon": 77.7, "pitch_deg": 0}}]
- "do a visual analysis of the viewport camera scene and list what you observe" -> [{{"type": "describe_view"}}]
- "fly to Olympus Mons and describe what you see" -> [{{"type": "goto", "place": "Olympus Mons"}}, {{"type": "describe_view"}}]
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
        types, limits = (PLANET_LAYER_ACTION_TYPES if kinds else PLANET_ACTION_TYPES), PLANET_LIMITS
    out = []
    for a in raw if isinstance(raw, list) else []:
        if not isinstance(a, dict) or a.get("type") not in types:
            continue
        act = {"type": a["type"]}
        lim = LAYER_LIMITS if body == "earth" and act["type"] == "show_layer" else limits
        place = a.get("place")
        lat, lon = a.get("lat"), a.get("lon")
        if isinstance(place, str) and (m := COORD_PLACE.fullmatch(place)) and lat is None and lon is None:
            lat, lon = float(m.group(1)), float(m.group(2))
        elif isinstance(place, str) and place.strip():
            act["place"] = place.strip()[:120]
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
        if act["type"] == "follow_vehicle":
            vehicle = a.get("vehicle")
            if isinstance(vehicle, str) and VEHICLE_NAME.fullmatch(vehicle.strip().lower()):
                act["vehicle"] = vehicle.strip().lower()
            act["view"] = a.get("view") if a.get("view") in FOLLOW_VIEWS else "camera"
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
                  else ("type",) if act["type"] == "describe_view" else FOLLOW_FIELDS if act["type"] == "follow_vehicle"
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


COMPASS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")
# What the page reports the camera drone doing (droneActivity in hud/pilot.js)
ACTIVITY_RE = re.compile(r"orbiting|climbing or descending|following [a-z0-9_.-]{1,40} \((?:camera|chase) view\)")


def _compass(deg):
    return COMPASS[round((deg % 360) / 45) % 8]


def _distance(m):
    return f"{m:.0f} m" if m < 1000 else f"{m / 1000:.1f} km"


def _view_num(src, key):
    v = src.get(key) if isinstance(src, dict) else None
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) else None


def _describe_view(view):
    """The camera drone's telemetry for the prompt, one line; empty if unusable."""
    if not isinstance(view, dict):
        return ""
    f = lambda key, src=view: _view_num(src, key)  # noqa: E731
    lat, lon, agl, hdg = f("lat"), f("lon"), f("height_agl"), f("heading_deg")
    if lat is None or lon is None:
        return ""
    line = f"Current view: camera at lat {lat:.5f}, lon {lon:.5f}"
    if agl is not None:
        line += f", {agl:.0f} m above ground"
    if (ground := f("ground_elev_m")) is not None:
        line += f" (ground elevation {ground:.0f} m)"
    if hdg is not None:
        line += f", heading {hdg % 360:.0f} deg ({_compass(hdg)})"
    if (pitch := f("pitch_deg")) is not None:
        line += (f", camera tilted {abs(pitch):.0f} deg below the horizon" if pitch < 0
                 else f", camera {pitch:.0f} deg above the horizon")
    if (roll := f("roll_deg")) is not None and abs(roll) >= 1:
        line += f", rolled {roll:.0f} deg"
    tgt = view.get("target")
    tlat, tlon = f("lat", tgt), f("lon", tgt)
    if tlat is not None and tlon is not None:
        line += f"; looking at lat {tlat:.5f}, lon {tlon:.5f}"
        extra = []
        if (rng := f("range_m", tgt)) is not None:
            extra.append(f"{_distance(rng)} away")
            if (fov := f("hfov_deg")) is not None and 1 <= fov <= 170:
                extra.append(f"view about {_distance(2 * rng * math.tan(math.radians(fov) / 2))} across")
        if (elev := f("elev_m", tgt)) is not None:
            extra.append(f"ground elevation {elev:.0f} m")
        if extra:
            line += f" ({', '.join(extra)})"
    activity = view.get("activity")
    if isinstance(activity, str) and ACTIVITY_RE.fullmatch(activity):
        line += f"; the drone is {activity}"
    return line + "."


# Questions about the surroundings ("what dam is this?", "where are we?") also get what
# OpenStreetMap names around the point in view, so the model can name it.
SITUATIONAL_RE = re.compile(
    r"\b(where|what|what's|which|identify|called|named|nearby|near (?:here|us|me|by)|around (?:here|us|me)|"
    r"here|this|that|these|those|we|we're|us|our|looking|facing|landmark|location|position|coordinates|"
    r"altitude|elevation|how (?:high|far|low|big))\b", re.IGNORECASE)
PHOTON_REVERSE_URL = "https://photon.komoot.io/reverse"
NOMINATIM_REVERSE_URL = "https://nominatim.openstreetmap.org/reverse"
GEO_HEADERS = {"User-Agent": "DeepGIS-XR AI pilot (https://deepgis.org)"}
NEARBY_TIMEOUT_SEC = 4
NEARBY_CACHE_SEC = 24 * 3600
NEARBY_FAIL_CACHE_SEC = 120
MAX_NEARBY = 10
NEARBY_RADII = (500, 1000, 2000, 4000)
OSM_KIND_NAMES = {"highway": "road", "building": "building", "boundary": "boundary"}


def _nearby_radius(view):
    tgt = view.get("target") if isinstance(view.get("target"), dict) else {}
    rng, fov = _view_num(tgt, "range_m"), _view_num(view, "hfov_deg")
    half = rng * math.tan(math.radians(fov) / 2) if rng and fov and 1 <= fov <= 170 else _view_num(view, "height_agl")
    return next((r for r in NEARBY_RADII if (half or 0) <= r), NEARBY_RADII[-1])


def _osm_kind(key, value):
    if key in OSM_KIND_NAMES or value in (None, "", "yes", "other"):
        return OSM_KIND_NAMES.get(key, str(key or "place").replace("_", " "))
    return str(value).replace("_", " ")


def _offset(lat, lon, plat, plon):
    """Distance (m) and compass direction from (lat, lon) to (plat, plon)."""
    dy = math.radians(plat - lat) * 6371000
    dx = math.radians(plon - lon) * 6371000 * math.cos(math.radians(lat))
    return math.hypot(dx, dy), _compass(math.degrees(math.atan2(dx, dy)))


def _photon_places(lat, lon, radius):
    """Named OpenStreetMap features around a point, nearest first: [(dist_m, name, kind, direction)].
    Photon answers in under a second; the public Overpass servers often take 15-30 s."""
    resp = requests.get(PHOTON_REVERSE_URL, headers=GEO_HEADERS, timeout=NEARBY_TIMEOUT_SEC,
                        params={"lat": f"{lat:.5f}", "lon": f"{lon:.5f}", "radius": radius / 1000,
                                "limit": 2 * MAX_NEARBY, "lang": "en"})
    resp.raise_for_status()
    found = {}
    for feat in resp.json().get("features") or []:
        props, coords = feat.get("properties") or {}, (feat.get("geometry") or {}).get("coordinates")
        name = props.get("name")
        if not isinstance(name, str) or not name.strip() or not isinstance(coords, list) or len(coords) != 2:
            continue
        plon, plat = coords
        ext = props.get("extent")  # [west, north, east, south] for ways and areas
        if isinstance(ext, list) and len(ext) == 4:
            plon, plat = min(max(lon, ext[0]), ext[2]), min(max(lat, ext[3]), ext[1])
        dist, way = _offset(lat, lon, plat, plon)
        key = name.strip().casefold()
        if key not in found or dist < found[key][0]:
            found[key] = (dist, name.strip()[:80], _osm_kind(props.get("osm_key"), props.get("osm_value")), way)
    return sorted(found.values())[:MAX_NEARBY]


def _reverse_area(lat, lon):
    resp = requests.get(NOMINATIM_REVERSE_URL, headers=GEO_HEADERS, timeout=NEARBY_TIMEOUT_SEC,
                        params={"lat": f"{lat:.5f}", "lon": f"{lon:.5f}", "format": "jsonv2",
                                "zoom": 12, "accept-language": "en"})
    resp.raise_for_status()
    name = resp.json().get("display_name")
    return name[:200] if isinstance(name, str) else ""


def nearby_places(view):
    """What OpenStreetMap names around the point in view, as a prompt line; "" if unknown."""
    if not isinstance(view, dict):
        return ""
    tgt = view.get("target") if isinstance(view.get("target"), dict) else view
    lat, lon = _view_num(tgt, "lat"), _view_num(tgt, "lon")
    if lat is None or lon is None or not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return ""
    radius = _nearby_radius(view)
    key = f"pilot-nearby:v2:{lat:.3f}:{lon:.3f}:{radius}"
    if (hit := cache.get(key)) is not None:
        return hit
    with ThreadPoolExecutor(2) as pool:
        jobs = pool.submit(_photon_places, lat, lon, radius), pool.submit(_reverse_area, lat, lon)
        places, area = [], ""
        try:
            places = jobs[0].result(timeout=NEARBY_TIMEOUT_SEC + 1)
        except (requests.RequestException, ValueError, FutureTimeout):
            pass
        try:
            area = jobs[1].result(timeout=NEARBY_TIMEOUT_SEC + 1)
        except (requests.RequestException, ValueError, FutureTimeout):
            pass
    parts = []
    if places:
        parts.append(f"Named places within {_distance(radius)} of the point in view (OpenStreetMap, nearest first): "
                     + "; ".join(f"{name} ({kind}, " + ("at the point in view" if dist < 30
                                                        else f"{_distance(dist)} {way}") + ")"
                                 for dist, name, kind, way in places) + ".")
    if area:
        parts.append(f"Area: {area}.")
    line = " ".join(parts)
    cache.set(key, line, NEARBY_CACHE_SEC if places else NEARBY_FAIL_CACHE_SEC)
    return line


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


MODEL_CACHE_KEY = "pilot-model-catalog"
MODEL_CACHE_SEC = 60


def _model_catalog(refresh=False):
    """Only expose active Gemma/Qwen choices; backend URLs never reach the browser."""
    if not refresh and (cached := cache.get(MODEL_CACHE_KEY)):
        return cached
    raw = call_mcp_tool("list_models", {}, 10)
    names = [str(name) for name in raw.get("models", [])
             if isinstance(name, str)
             and ("gemma" in name.lower() or name.lower().startswith("qwen"))]
    default = str(raw.get("default_model") or "")
    if default and "gemma" in default.lower() and default not in names:
        names.insert(0, default)
    names = list(dict.fromkeys(names))
    if default not in names:
        default = next((name for name in names if "gemma" in name.lower()), names[0] if names else "")
    out = {"default_model": default, "models": names}
    cache.set(MODEL_CACHE_KEY, out, MODEL_CACHE_SEC)
    return out


@require_GET
def pilot_models(request):
    if not request.user.is_authenticated:
        return JsonResponse({"error": "login_required",
                             "login_url": "/label/admin/login/"}, status=401)
    if not settings.DEEPGIS_PILOT_MCP_TOKEN:
        return JsonResponse({"error": "The AI pilot is not configured on this server."}, status=503)
    try:
        return JsonResponse(_model_catalog())
    except (requests.RequestException, RuntimeError, ValueError, KeyError) as e:
        return JsonResponse({"error": f"Model list unavailable: {type(e).__name__}"}, status=502)


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
    model = data.get("model", "")
    if not isinstance(model, str):
        return JsonResponse({"error": "Unknown model"}, status=400)
    model = model.strip()
    if model:
        try:
            if model not in _model_catalog()["models"]:
                return JsonResponse({"error": "Unknown model"}, status=400)
        except (requests.RequestException, RuntimeError, ValueError, KeyError) as e:
            return JsonResponse({"error": f"Model list unavailable: {type(e).__name__}"}, status=502)
    if _rate_limited(request.user.pk):
        return JsonResponse({"error": "Too many requests; wait a minute."}, status=429)

    context = [_describe_view(data.get("view"))]
    if body == "earth" and context[0] and SITUATIONAL_RE.search(message):
        context.append(nearby_places(data.get("view")))
    prompt = "".join(ln + "\n" for ln in context if ln) + "User: " + message.strip()[:MAX_MESSAGE_CHARS]
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
    if model:
        args["model"] = model
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


# describe_view: the page posts one frame of the Cesium canvas and the lab's
# (vision-capable) model lists what it sees, through dreams_mcp's describe_image.
DESCRIBE_RATE_PER_MIN = 6
MAX_IMAGE_CHARS = 3_000_000  # base64; the page sends a JPEG of at most 1280 px a side
IMAGE_DATA_URL = re.compile(r"data:image/(?:jpeg|png);base64,([A-Za-z0-9+/]+=*)")
MAX_OBSERVATIONS = 12
DESCRIBE_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "observations": {"type": "array", "maxItems": MAX_OBSERVATIONS, "items": {"type": "string"}},
    },
    "required": ["summary", "observations"],
}
VISION_PROMPT = """You are the eyes of the AI pilot in the DeepGIS viewer. The image is one frame from a virtual camera flying over a 3D globe of {body}, rendered by Cesium from {imagery} draped over the terrain. Describe only what is actually visible in it.
- observations: 4 to 10 short sentences, each about one thing you see and where it is in the frame (left, centre, upper right, foreground, near the horizon). Cover landforms and terrain (craters, ridges, mountains, valleys, channels, dunes, plains, cliffs), surface colour, brightness and texture, shadows and lighting{earth_things}. Mention colour maps, markers, labels or lines drawn on the globe, and black sky or the edge of the globe if visible.
- Say how sure you are when unsure ("possibly a small crater"). Do not invent names, sizes, ages or other facts you cannot see; name a feature only if a label in the image shows it or it fits a place listed in the location context (then say so, e.g. "an earthen dam, likely Pleasant Valley Dam per the map").
- If blurry, low-resolution or missing imagery tiles dominate the frame, say so once.
- summary: one or two sentences on the scene as a whole; if the location context names the main feature and it fits what you see, name it here and answer the user's question."""


def vision_prompt(body):
    earth = body == "earth"
    return VISION_PROMPT.format(
        body=BODIES[body], imagery="satellite and aerial imagery" if earth else "orbiter imagery",
        earth_things=", and also water, vegetation, fields, roads, buildings and clouds" if earth else "")


def _image_b64(image):
    """Plain base64 of a JPEG or PNG data URL from the page; None if it is not one."""
    if not isinstance(image, str) or len(image) > MAX_IMAGE_CHARS:
        return None
    m = IMAGE_DATA_URL.fullmatch(image)
    if not m:
        return None
    try:
        head = base64.b64decode(m.group(1)[:16])
    except ValueError:
        return None
    return m.group(1) if head.startswith((b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n")) else None


@require_POST
def pilot_describe(request):
    if not request.user.is_authenticated:
        return JsonResponse({"error": "login_required",
                             "login_url": "/label/admin/login/"}, status=401)
    if not settings.DEEPGIS_PILOT_MCP_TOKEN:
        return JsonResponse({"error": "The AI pilot is not configured on this server."}, status=503)
    try:
        data = json.loads(request.body)
    except ValueError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)
    if not isinstance(data, dict):
        return JsonResponse({"error": "Invalid JSON"}, status=400)
    body = data.get("body", "earth")
    if not isinstance(body, str) or body not in BODIES:
        return JsonResponse({"error": "Unknown body"}, status=400)
    image = _image_b64(data.get("image"))
    if not image:
        return JsonResponse({"error": "image must be a JPEG or PNG data URL under 3 MB"}, status=400)
    if _rate_limited(request.user.pk, "pilot-describe", DESCRIBE_RATE_PER_MIN):
        return JsonResponse({"error": "Too many view analyses; wait a minute."}, status=429)

    lines = [_describe_view(data.get("view"))]
    if body == "earth" and lines[0]:
        lines.append(nearby_places(data.get("view")))
    question = data.get("question")
    if isinstance(question, str) and question.strip():
        lines.append("The user asked: " + question.strip()[:MAX_MESSAGE_CHARS])
    lines.append("List what you observe in this image.")
    timeout = settings.DEEPGIS_PILOT_TIMEOUT_SEC
    args = {
        "image": image,
        "prompt": "\n".join(ln for ln in lines if ln),
        "system_prompt": vision_prompt(body),
        "json_schema": DESCRIBE_SCHEMA,
        "temperature": 0.2,
        "max_tokens": 900,
        "timeout_sec": timeout,
    }
    try:
        out = call_mcp_tool("describe_image", args, timeout + 10)
    except (requests.RequestException, RuntimeError, ValueError, KeyError) as e:
        return JsonResponse({"error": f"AI pilot unavailable: {type(e).__name__}"}, status=502)
    seen = out.get("json") if isinstance(out, dict) else None
    if not isinstance(seen, dict):
        return JsonResponse({"error": "The AI pilot could not read the view; try again."}, status=502)
    summary = seen.get("summary") if isinstance(seen.get("summary"), str) else ""
    observations = [o.strip()[:300] for o in seen.get("observations") or []
                    if isinstance(o, str) and o.strip()][:MAX_OBSERVATIONS]
    return JsonResponse({
        "summary": summary.strip()[:600],
        "observations": observations,
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


# Lidar and drone terrain models from OpenTopography for the lidar_dem layer, pulled to
# this server once as cloud-optimised GeoTIFFs (scripts/topo_pull.py, files in data/topo/,
# not in git). Keys are the file stems; when surveys tie on coverage the finer, newer wins.
TOPO_DIR = os.path.join(settings.BASE_DIR, "data", "topo")
TOPO_DATASETS = {
    "CA19_Scott_hh": {"name": "Topography of Normal Faults in the Volcanic Tablelands, CA 2019", "year": 2019,
                      "product": "drone surface model (includes shrubs and boulders)", "collected": "April 2019",
                      "source_res": "4.6 cm, stored at 0.5 m", "doi": "10.5069/G97S7KXT"},
    "CA18_Scott_hh": {"name": "Topography of Normal Faults in the Volcanic Tablelands, CA 2018", "year": 2018,
                      "product": "drone surface model (includes shrubs and boulders)", "collected": "March 2018",
                      "source_res": "10 cm, stored at 0.5 m", "doi": "10.5069/G9SF2TC5"},
    "CA14_Delano_be": {"name": "Volcanic Tablelands in Bishop, California", "year": 2014,
                       "product": "airborne lidar bare-earth model", "collected": "October 2014",
                       "source_res": "0.5 m", "doi": "10.5069/G9RJ4GCH"},
    "CA12_Lifton_be": {"name": "White Mountain Fault Zone, Owens Valley, CA", "year": 2012,
                       "product": "airborne lidar bare-earth model", "collected": "July 2012",
                       "source_res": "1 m", "doi": "10.5069/G9FF3Q99"},
    "CA09_Whelley_be": {"name": "Bishop, CA: Morphological characteristics of the Bishop Tuff", "year": 2010,
                        "product": "airborne lidar bare-earth model", "collected": "September 2010",
                        "source_res": "1 m", "doi": "10.5069/G9J1012J"},
}
TOPO_RADIUS_M = (50.0, 10000.0)
TOPO_MAX_PX = 768  # per side of the returned image
TOPO_NEAR_M = 30000.0  # a request this close to a survey moves onto it
TOPO_RATE_PER_MIN = 20
TOPO_CACHE_SEC = 24 * 3600
TOPO_NODATA = -9999.0
TOPO_SLOPE_MAX = 60.0  # degrees at blue 255
_topo_index = {}


# This GDAL build has no numpy bridge (ReadAsArray), so bands go through raw buffers
def _band(ds, k=1):
    raw = ds.GetRasterBand(k).ReadRaster(buf_type=gdal.GDT_Float32)
    return np.frombuffer(raw, np.float32).reshape(ds.RasterYSize, ds.RasterXSize)


def _wgs84():
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(4326)
    srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    return srs


def topo_index():
    """{stem: dataset} for the pulled files, with native resolution, projected box and lon/lat bounds."""
    out = {}
    for stem, meta in TOPO_DATASETS.items():
        path = os.path.join(TOPO_DIR, stem + ".tif")
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            continue
        hit = _topo_index.get(stem)
        if not hit or hit["mtime"] != mtime or hit["path"] != path:
            src = gdal.Open(path)
            gt, w, h = src.GetGeoTransform(), src.RasterXSize, src.RasterYSize
            srs = src.GetSpatialRef()
            box = (gt[0], gt[3] + gt[5] * h, gt[0] + gt[1] * w, gt[3])
            to_ll = osr.CoordinateTransformation(srs, _wgs84())
            corners = [to_ll.TransformPoint(x, y)[:2] for x in box[0::2] for y in box[1::2]]
            hit = _topo_index[stem] = {
                **meta, "id": stem, "path": path, "mtime": mtime, "res": gt[1], "wkt": srs.ExportToWkt(), "box": box,
                "bounds": [round(f(c[k] for c in corners), 5) for f, k in ((min, 0), (min, 1), (max, 0), (max, 1))]}
        out[stem] = hit
    return out


def _transform(info, to_projected):
    srs = osr.SpatialReference(wkt=info["wkt"])
    srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    return osr.CoordinateTransformation(*((_wgs84(), srs) if to_projected else (srs, _wgs84())))


def _topo_warp(info, x, y, r, res=None, size=None):
    """The square of half-width r around projected (x, y), read from the file's overviews as needed."""
    opts = {"xRes": res, "yRes": res} if res else {"width": size, "height": size}
    coarser = (res or 2 * r / size) > info["res"] * 1.01
    return gdal.Warp("", info["path"], format="MEM", outputBounds=(x - r, y - r, x + r, y + r),
                     dstNodata=TOPO_NODATA, outputType=gdal.GDT_Float32,
                     resampleAlg="average" if coarser else "bilinear", **opts)


def pick_topo(index, lon, lat, r):
    """(dataset, x, y, coverage, other names) for the survey covering most of the circle's square, or None."""
    found = []
    for info in index.values():
        x, y = _transform(info, True).TransformPoint(lon, lat)[:2]
        bx = info["box"]
        if x + r < bx[0] or x - r > bx[2] or y + r < bx[1] or y - r > bx[3]:
            continue
        cover = float((_band(_topo_warp(info, x, y, r, size=48)) != TOPO_NODATA).mean())
        if cover >= 0.02:
            found.append(((round(cover, 1), -info["res"], info["year"]), info, x, y, cover))
    if not found:
        return None
    found.sort(key=lambda f: f[0], reverse=True)
    _, info, x, y, cover = found[0]
    return info, x, y, cover, [f[1]["name"] for f in found[1:]]


def nearest_topo(index, lon, lat, r):
    """(distance_m, lon, lat) of the nearest centre whose circle is mostly surveyed ground, or None."""
    best = None
    for info in index.values():
        x, y = _transform(info, True).TransformPoint(lon, lat)[:2]
        bx = info["box"]
        cell = max(bx[2] - bx[0], bx[3] - bx[1]) / 128
        src = gdal.Warp("", info["path"], format="MEM", outputBounds=bx, xRes=cell, yRes=cell,
                        dstNodata=TOPO_NODATA, resampleAlg="average")
        gt = src.GetGeoTransform()
        valid = (_band(src) != TOPO_NODATA).astype(np.float64)
        if not valid.any():
            continue
        # Share of surveyed cells in the (2k+1)-cell square around each cell, by summed-area table
        k = int(round(r / cell))
        n = 2 * k + 1
        c = np.pad(np.pad(valid, k).cumsum(0).cumsum(1), ((1, 0), (1, 0)))
        share = (c[n:, n:] - c[:-n, n:] - c[n:, :-n] + c[:-n, :-n]) / (n * n)
        rows, cols = np.nonzero((valid > 0) & (share >= min(0.6, share.max() * 0.9)))
        cx, cy = gt[0] + (cols + 0.5) * gt[1], gt[3] + (rows + 0.5) * gt[5]
        d2 = (cx - x) ** 2 + (cy - y) ** 2
        i = int(d2.argmin())
        if best is None or d2[i] < best[0]:
            best = (float(d2[i]), info, float(cx[i]), float(cy[i]))
    if best is None:
        return None
    lon2, lat2 = _transform(best[1], False).TransformPoint(best[2], best[3])[:2]
    return math.sqrt(best[0]), lon2, lat2


def _png_data_url(ds):
    path = f"/vsimem/pilot-topo-{uuid.uuid4().hex}.png"
    gdal.Translate(path, ds, format="PNG")
    try:
        f = gdal.VSIFOpenL(path, "rb")
        gdal.VSIFSeekL(f, 0, 2)
        size = gdal.VSIFTellL(f)
        gdal.VSIFSeekL(f, 0, 0)
        data = gdal.VSIFReadL(1, size, f)
        gdal.VSIFCloseL(f)
    finally:
        gdal.Unlink(path)
    return "data:image/png;base64," + base64.b64encode(data).decode()


def topo_render(info, x, y, r):
    """Shaded-relief image and figures for the circle of radius r around projected (x, y).

    The PNG packs, per pixel, height (red, over the elev range), multidirectional
    hillshade (green), slope (blue, 0 to TOPO_SLOPE_MAX degrees) and coverage (alpha),
    so the page can colour it with any colour map.
    """
    res = max(info["res"], 2 * r / TOPO_MAX_PX)
    src = _topo_warp(info, x, y, r, res=res)
    elev = _band(src)
    valid = elev != TOPO_NODATA
    shade = _band(gdal.DEMProcessing("", src, "hillshade", format="MEM", multiDirectional=True, computeEdges=True))
    slope = _band(gdal.DEMProcessing("", src, "slope", format="MEM", computeEdges=True))

    gt = src.GetGeoTransform()
    rows, cols = np.indices(elev.shape)
    dx, dy = gt[0] + (cols + 0.5) * gt[1] - x, gt[3] + (rows + 0.5) * gt[5] - y
    circle = dx ** 2 + dy ** 2 <= r * r
    inside = valid & circle
    if inside.sum() < 10:
        return None
    e = elev[inside]
    s = slope[inside & (slope >= 0)]
    p1, p2, p50, p98, p99 = (float(v) for v in np.percentile(e, [1, 2, 50, 98, 99]))
    ci, cj = int(np.abs(dy[:, 0]).argmin()), int(np.abs(dx[0]).argmin())
    stats = {
        "min": float(e.min()), "max": float(e.max()), "p2": p2, "p98": p98, "median": p50,
        "centre": float(elev[ci, cj]) if valid[ci, cj] else None,
        "centre_slope": float(slope[ci, cj]) if valid[ci, cj] and slope[ci, cj] >= 0 else None,
        "slope_median": float(np.median(s)) if s.size else None,
        "steep_share": float((s > 30).mean()) if s.size else None,
        "coverage": float(inside.sum() / circle.sum()),
    }
    stats = {k: (round(v, 3) if isinstance(v, float) else v) for k, v in stats.items()}

    lo, hi = p1, max(p99, p1 + 1.0)
    bands = [np.clip((elev - lo) / (hi - lo) * 255, 0, 255), shade,
             np.clip(slope / TOPO_SLOPE_MAX * 255, 0, 255), valid * 255.0]
    rgba = gdal.GetDriverByName("MEM").Create("", elev.shape[1], elev.shape[0], 4, gdal.GDT_Byte)
    rgba.SetGeoTransform(gt)
    rgba.SetProjection(src.GetProjection())
    for k, band in enumerate(bands):
        rgba.GetRasterBand(k + 1).WriteRaster(0, 0, elev.shape[1], elev.shape[0],
                                              np.where(valid, band, 0).round().astype(np.uint8).tobytes())
    rgba.GetRasterBand(4).SetColorInterpretation(gdal.GCI_AlphaBand)
    # Square pixels in lon/lat so the page can drape the image on a rectangle
    ll = gdal.Warp("", rgba, format="MEM", dstSRS="EPSG:4326", width=elev.shape[1], height=elev.shape[0],
                   resampleAlg="near", srcAlpha=True, dstAlpha=True)
    lgt = ll.GetGeoTransform()
    bounds = [lgt[0], lgt[3] + lgt[5] * ll.RasterYSize, lgt[0] + lgt[1] * ll.RasterXSize, lgt[3]]
    return {"png": _png_data_url(ll), "bounds": [round(v, 7) for v in bounds], "res_m": round(res, 2),
            "elev": [round(lo, 2), round(hi, 2)], "slope_max": TOPO_SLOPE_MAX, "stats": stats}


def _topo_public(info):
    return {k: info[k] for k in ("id", "name", "product", "collected", "source_res", "doi", "bounds")}


@require_GET
def pilot_topo(request):
    if not request.user.is_authenticated:
        return JsonResponse({"error": "login_required", "login_url": "/label/admin/login/"}, status=401)
    with gdal.ExceptionMgr(useExceptions=True):
        try:
            index = topo_index()
        except RuntimeError as e:
            return JsonResponse({"error": f"The stored terrain models cannot be read ({e})"}, status=500)
        if request.GET.get("list"):
            return JsonResponse({"datasets": [_topo_public(i) for i in index.values()]})
        try:
            lat, lon = float(request.GET["lat"]), float(request.GET["lon"])
            r = float(request.GET.get("radius_m", 2000))
        except (KeyError, ValueError):
            return JsonResponse({"error": "lat and lon are required"}, status=400)
        if not (-90 <= lat <= 90 and -180 <= lon <= 180 and math.isfinite(r)):
            return JsonResponse({"error": "lat, lon or radius_m is out of range"}, status=400)
        lat, lon, r = round(lat, 5), round(lon, 5), round(max(TOPO_RADIUS_M[0], min(TOPO_RADIUS_M[1], r)))

        files = ":".join(f"{k}{int(i['mtime'])}" for k, i in index.items())
        key = f"pilot-topo:{lat}:{lon}:{r}:{files}"
        cached = cache.get(key)
        if cached:
            return JsonResponse(cached)
        if _rate_limited(request.user.pk, "pilot-topo", TOPO_RATE_PER_MIN):
            return JsonResponse({"error": "Too many requests; wait a minute."}, status=429)
        try:
            moved = None
            hit = pick_topo(index, lon, lat, r)
            if not hit or hit[3] < 0.1:
                # Off or at the edge of the surveys: move onto the nearest well-covered ground
                near = nearest_topo(index, lon, lat, r)
                there = near and near[0] <= TOPO_NEAR_M and pick_topo(index, near[1], near[2], r)
                if there:
                    hit, moved, lon, lat = there, round(near[0]), round(near[1], 5), round(near[2], 5)
            if not hit:
                names = "; ".join(i["name"] for i in index.values()) or "none yet"
                return JsonResponse({"error": "No OpenTopography lidar is stored on DeepGIS near here. "
                                              f"Stored surveys: {names}.",
                                     "datasets": [_topo_public(i) for i in index.values()]}, status=404)
            info, x, y, _, others = hit
            out = topo_render(info, x, y, r)
        except RuntimeError as e:
            return JsonResponse({"error": f"The terrain model could not be read ({e})"}, status=500)
    if not out:
        return JsonResponse({"error": "No lidar ground inside this circle"}, status=404)
    out.update({"dataset": _topo_public(info), "lat": lat, "lon": lon, "radius_m": r,
                "moved_m": moved, "others": others})
    cache.set(key, out, TOPO_CACHE_SEC)
    return JsonResponse(out)
