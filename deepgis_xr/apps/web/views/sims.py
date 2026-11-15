"""OpenUAV desktops for the search page.

GET /label/api/sims/ lists kind=lab rows for any signed-in DeepGIS account,
plus that account's own kind=session rows (a create_twin desktop). Each url
is a path on this site. Signed-out requests get 401. Course rows stay hidden.
"""

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import JsonResponse
from django.views.decorators.http import require_GET

from deepgis_xr.apps.core.models import Simulation

PORT_MIN = 40000
PORT_MAX = 40999
# Lab desktops already published on the hub. A session twin never takes one.
LAB_PORTS = frozenset({40077, 40088, 40099})
# Session band inside the hub's 40000-40999 proxy range, clear of the lab ports.
SESSION_PORT_MIN = 40100
SESSION_PORT_MAX = 40199


def panel_path(port):
    """Path the hub already proxies. None when the port is outside that range."""
    if isinstance(port, bool) or not isinstance(port, int):
        return None
    if not PORT_MIN <= port <= PORT_MAX:
        return None
    return f"/openuav/llm/{port}/"


def allocate_session_port():
    """Lowest free port in the session band, skipping anything already registered."""
    used = set(Simulation.objects.values_list("host_port", flat=True)) | LAB_PORTS
    for port in range(SESSION_PORT_MIN, SESSION_PORT_MAX + 1):
        if port not in used:
            return port
    raise ValueError("No free session desktop port.")


def _place_label(look_at):
    look = look_at if isinstance(look_at, dict) else {}
    lat, lon = look.get("lat"), look.get("lon")
    if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
        return f"{float(lat):.3f}, {float(lon):.3f}"
    return "Session twin"


def _check_session_port(port):
    if isinstance(port, bool) or not isinstance(port, int):
        raise ValueError("Session desktop port must be an integer.")
    if port in LAB_PORTS or not SESSION_PORT_MIN <= port <= SESSION_PORT_MAX:
        raise ValueError("Session desktop port is outside the session band.")


def register_session(*, callsign, owner, look_at, host_port=None):
    """One Simulation row for a create_twin desktop. The slug is the callsign."""
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
    """Free the desktop port. Lab rows are a different kind and are left alone."""
    if not callsign:
        return
    Simulation.objects.filter(slug=str(callsign)[:40], kind="session").delete()


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
        Q(kind="lab") | Q(kind="session", owner=request.user, status__in=("unknown", "up"))
    ).order_by("position", "name")
    for sim in visible:
        row = public_row(sim)
        if row:
            rows.append(row)
    return JsonResponse({"sims": rows})
