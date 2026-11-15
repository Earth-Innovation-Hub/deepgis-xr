"""
Access check for the OpenUAV twin panel (https://deepgis.org/openuav/llm/<port>/).

The hub's nginx sends an auth_request subrequest here, with the browser's
cookies, before serving the panel, its noVNC desktop or its MCP proxy. The
panel can command the simulated vehicle, so it takes a DeepGIS sign-in (the
same /label/admin/login/ as the AI pilot). Any signed-in account is allowed.
"""

from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt

# The admin group still exists. The panel no longer checks it: a DeepGIS
# sign-in is the gate.
TWIN_PILOTS_GROUP = "twin-pilots"


# The subrequest carries the panel's own method (POST for MCP) and no CSRF
# token; nothing here changes state.
@csrf_exempt
def twin_access(request):
    if not request.user.is_authenticated:
        return HttpResponse(status=401)
    return HttpResponse(status=204)
