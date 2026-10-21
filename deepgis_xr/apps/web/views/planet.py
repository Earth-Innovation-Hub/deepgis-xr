"""The Moon viewer template opened on any body in the planetary registry."""

from django.conf import settings
from django.http import Http404
from django.shortcuts import render

# The ids in staticfiles/web/js/planet-bodies.js (tests/test_planet.py keeps them in step).
PLANET_BODIES = (
    "moon", "mars", "mercury", "venus", "io", "europa", "ganymede",
    "callisto", "titan", "pluto", "charon",
)


def label_planet_viewer(request, body):
    body = body.lower()
    if body not in PLANET_BODIES:
        raise Http404(f"Unknown body: {body}")
    return render(request, "web/label_moon_viewer.html", {
        "planet_body": body,
        "cesium_ion_token": settings.CESIUM_ION_TOKEN,
    })
