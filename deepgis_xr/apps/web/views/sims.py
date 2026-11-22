"""Lab OpenUAV desktops for the search page.

GET /label/api/sims/ lists kind=lab rows for any signed-in DeepGIS account.
Each url is a path on this site. Signed-out requests get 401.
"""

import json

import requests
from django.conf import settings
from django.core.cache import caches
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_POST

from deepgis_xr.apps.core.models import Simulation

from . import robots

PORT_MIN = 40000
PORT_MAX = 40999
LAB_PORTS = frozenset({40077, 40088, 40099})
SESSION_PORT_MIN = 40100
SESSION_PORT_MAX = 40199


def panel_path(port):
    """Path the hub already proxies. None when the port is outside that range."""
    if isinstance(port, bool) or not isinstance(port, int):
        return None
    if not PORT_MIN <= port <= PORT_MAX:
        return None
    return f"/openuav/llm/{port}/"


def public_row(sim):
    url = panel_path(sim.host_port)
    if url is None:
        return None
    robots = sim.robots if isinstance(sim.robots, list) else []
    return {
        "slug": sim.slug,
        "name": sim.name,
        "world": sim.world,
        "robots": [r for r in robots if isinstance(r, str)],
        "commands": bool(sim.commands),
        "kind": sim.kind,
        "status": sim.status if sim.status in ("unknown", "up", "down") else "unknown",
        "url": url,
    }


@require_GET
def sims_list(request):
    if not request.user.is_authenticated:
        return JsonResponse(
            {"error": "login_required", "login_url": "/label/admin/login/?next=/label/3d/search/"},
            status=401,
        )
    rows = []
    visible = Simulation.objects.filter(
        Q(kind="lab") | Q(kind="session", owner=request.user, status__in=("unknown", "up", "down"))
    ).order_by("position", "name")
    for sim in visible:
        row = public_row(sim)
        if row:
            rows.append(row)
    return JsonResponse({"sims": rows})


def allocate_session_port():
    used = set(Simulation.objects.values_list("host_port", flat=True)) | LAB_PORTS
    for port in range(SESSION_PORT_MIN, SESSION_PORT_MAX + 1):
        if port not in used:
            return port
    raise ValueError("No free session desktop port.")


def _check_session_port(port):
    if isinstance(port, bool) or not isinstance(port, int):
        raise ValueError("Session desktop port must be an integer.")
    if port in LAB_PORTS or not SESSION_PORT_MIN <= port <= SESSION_PORT_MAX:
        raise ValueError("Session desktop port is outside the session band.")


def _place_label(look_at):
    look = look_at if isinstance(look_at, dict) else {}
    lat, lon = look.get("lat"), look.get("lon")
    if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
        return f"{float(lat):.3f}, {float(lon):.3f}"
    return "Session twin"


def register_session(*, callsign, owner, look_at, host_port=None):
    if not isinstance(callsign, str) or not callsign.startswith("ktwin-"):
        raise ValueError("Refusing a session name that is not a ktwin callsign.")
    label = _place_label(look_at)
    slug = callsign[:40]
    last_error = None
    for _attempt in range(8):
        port = host_port if host_port is not None else allocate_session_port()
        _check_session_port(port)
        try:
            with transaction.atomic():
                sim, _created = Simulation.objects.update_or_create(
                    slug=slug,
                    defaults={
                        "name": label[:80],
                        "container": f"digital-twin-session-{callsign}"[:80],
                        "host_port": port,
                        "world": label[:120],
                        "robots": [callsign],
                        "commands": False,
                        "kind": "session",
                        "status": "unknown",
                        "owner": owner,
                        "position": 50,
                    },
                )
            return sim
        except IntegrityError as exc:
            last_error = exc
            if host_port is not None:
                break
    raise ValueError("No free session desktop port.") from last_error


def set_session_status(callsign, status):
    if not callsign:
        return
    Simulation.objects.filter(slug=str(callsign)[:40], kind="session").update(status=status)


def drop_session(callsign):
    if not callsign:
        return
    Simulation.objects.filter(slug=str(callsign)[:40], kind="session").delete()

def _own_session(user, slug):
    if not isinstance(slug, str) or not slug.startswith("ktwin-") or len(slug) > 40:
        return None
    if not all(c.isalnum() or c in "-_" for c in slug):
        return None
    return Simulation.objects.filter(slug=slug, kind="session", owner=user).first()


def _forget_live(slug):
    """Drop the chase pose and camera frame for a purged twin."""
    live = caches["live"]
    live.delete(f"vehicle:{slug}")
    live.delete(f"frame:{slug}")
    live.delete(f"frame_info:{slug}")
    ids = live.get(robots.IDS_KEY) or []
    if slug in ids:
        live.set(robots.IDS_KEY, [item for item in ids if item != slug], None)


def _builder_ready():
    return bool(getattr(settings, "DEEPGIS_TWIN_BUILDER_URL", "")
                and getattr(settings, "DEEPGIS_TWIN_BUILDER_TOKEN", ""))


@require_POST
def sims_control(request, slug):
    """Stop, start, or purge the signed-in owner's session twin."""
    if not request.user.is_authenticated:
        return JsonResponse(
            {"error": "login_required", "login_url": "/label/admin/login/?next=/label/3d/search/"},
            status=401,
        )
    sim = _own_session(request.user, slug)
    if sim is None:
        return JsonResponse({"error": "No such twin."}, status=404)
    expected = f"digital-twin-session-{slug}"[:80]
    if sim.container != expected:
        return JsonResponse({"error": "This desktop is not a session twin."}, status=400)
    try:
        data = json.loads(request.body or b"{}")
    except ValueError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)
    action = data.get("action") if isinstance(data, dict) else None
    if action not in ("stop", "start", "purge"):
        return JsonResponse({"error": "action must be stop, start, or purge"}, status=400)
    if not _builder_ready():
        return JsonResponse({"error": "Twin builder is not configured"}, status=503)
    url = settings.DEEPGIS_TWIN_BUILDER_URL.rstrip("/") + f"/sessions/{slug}/{action}"
    try:
        resp = requests.post(
            url,
            headers={"Authorization": f"Bearer {settings.DEEPGIS_TWIN_BUILDER_TOKEN}"},
            timeout=45,
        )
    except requests.RequestException:
        return JsonResponse({"error": "Twin builder did not answer"}, status=502)
    if resp.status_code >= 400:
        message = "The twin builder refused that."
        try:
            err = resp.json().get("error")
        except ValueError:
            err = ""
        if isinstance(err, str) and err:
            message = err[:200]
        return JsonResponse({"error": message}, status=502)
    if action == "purge":
        drop_session(slug)
        try:
            _forget_live(slug)
        except Exception:
            pass
        return JsonResponse({"ok": True, "status": "purged"})
    status = "down" if action == "stop" else "up"
    set_session_status(slug, status)
    return JsonResponse({"ok": True, "status": status})
