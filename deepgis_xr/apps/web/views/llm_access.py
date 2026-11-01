"""
Gate for https://llm.deepgis.org/ (Unsloth Studio).

The studio hostname cannot see the deepgis.org session cookie, so a superuser
signs in on deepgis.org, the gate redirects to /_auth with a 90-second signed
token, and that response sets an HttpOnly cookie scoped to llm.deepgis.org.
nginx auth_request calls llm_access with that cookie on every later request.

Only an active DeepGIS superuser (deepgis-xr is_superuser) passes. The shared
Studio password is unchanged and still applies after this gate.
"""

from urllib.parse import quote

from django.contrib.auth import get_user_model
from django.core import signing
from django.http import HttpResponse, HttpResponseForbidden, HttpResponseRedirect
from django.views.decorators.csrf import csrf_exempt

EXCHANGE_SALT = "llm.deepgis.org.exchange"
COOKIE_SALT = "llm.deepgis.org.superuser"
COOKIE_NAME = "llm_super"
COOKIE_MAX_AGE = 12 * 3600
EXCHANGE_MAX_AGE = 90
LLM_ORIGIN = "https://llm.deepgis.org"


def _safe_next(raw):
    """A same-host path. Anything else becomes /. """
    if not isinstance(raw, str):
        return "/"
    raw = raw.strip()
    if not raw or len(raw) > 512:
        return "/"
    if not raw.startswith("/") or raw.startswith("//") or raw.startswith("/\\"):
        return "/"
    if any(ch in raw for ch in ("\\", "\n", "\r", "\x00")) or "://" in raw:
        return "/"
    return raw


def _deny(message):
    body = (
        "<!doctype html><html><head><meta charset=\"utf-8\"><title>DeepGIS</title>"
        "<style>body{margin:0;background:#161616;color:#f2f2f2;"
        "font:18px/1.45 sans-serif}main{max-width:36rem;margin:14vh auto;padding:0 1.5rem}"
        "</style></head><body><main><p>"
        + message
        + "</p></main></body></html>"
    )
    return HttpResponseForbidden(body)


def llm_gate(request):
    """Browser entry on deepgis.org. Sends a superuser on to the studio host."""
    nxt = _safe_next(request.GET.get("next"))
    if not request.user.is_authenticated:
        gate = "/label/llm-gate/?next=" + quote(nxt, safe="")
        return HttpResponseRedirect("/label/admin/login/?next=" + quote(gate, safe=""))
    if not request.user.is_active or not request.user.is_superuser:
        return _deny("This site is for DeepGIS superusers.")
    token = signing.dumps({"u": request.user.pk, "n": nxt}, salt=EXCHANGE_SALT)
    url = (
        LLM_ORIGIN
        + "/_auth?t="
        + quote(token, safe="")
        + "&next="
        + quote(nxt, safe="")
    )
    return HttpResponseRedirect(url)


@csrf_exempt
def llm_exchange(request):
    """Reached via llm.deepgis.org/_auth. Sets the studio cookie and redirects."""
    try:
        data = signing.loads(request.GET.get("t") or "", salt=EXCHANGE_SALT, max_age=EXCHANGE_MAX_AGE)
        uid = int(data["u"])
        nxt = _safe_next(data.get("n"))
    except (signing.BadSignature, signing.SignatureExpired, KeyError, TypeError, ValueError):
        return _deny("Sign-in link expired. Open the studio address again.")
    User = get_user_model()
    if not User.objects.filter(pk=uid, is_active=True, is_superuser=True).exists():
        return _deny("This site is for DeepGIS superusers.")
    response = HttpResponseRedirect(nxt)
    response.set_cookie(
        COOKIE_NAME,
        signing.dumps({"u": uid}, salt=COOKIE_SALT),
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        secure=True,
        samesite="Lax",
        path="/",
    )
    response["Referrer-Policy"] = "no-referrer"
    response["Cache-Control"] = "no-store"
    return response


@csrf_exempt
def llm_access(request):
    """nginx auth_request. 204 with X-LLM-Ok when the cookie is a live superuser."""
    raw = request.COOKIES.get(COOKIE_NAME)
    if not raw:
        return HttpResponse(status=401)
    try:
        data = signing.loads(raw, salt=COOKIE_SALT, max_age=COOKIE_MAX_AGE)
        uid = int(data["u"])
    except (signing.BadSignature, signing.SignatureExpired, KeyError, TypeError, ValueError):
        return HttpResponse(status=401)
    User = get_user_model()
    if not User.objects.filter(pk=uid, is_active=True, is_superuser=True).exists():
        return HttpResponse(status=401)
    response = HttpResponse(status=204)
    response["X-LLM-Ok"] = "1"
    return response

