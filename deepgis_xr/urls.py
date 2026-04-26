from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.views.generic import RedirectView
from deepgis_xr.apps.web import views as web_views

urlpatterns = [
    # Public-facing admin route. The deepgis.org nginx in front of this
    # container only proxies /label/, /webclient/, and /map-label/ to
    # port 8060 — anything under /admin/ goes to the dreams_laboratory
    # site on port 8080. Mounting the admin under label/admin/ first
    # makes Django's reverse() emit links with the same prefix, so
    # admin POSTs/redirects survive the proxy hop end-to-end.
    path('label/admin/', admin.site.urls),
    # Direct (in-container / port-8060 / staging) access redirects to
    # the canonical public prefix instead of mounting a second admin
    # namespace, which would make Django reverse() ambiguous.
    path('admin/', RedirectView.as_view(url='/label/admin/', permanent=False)),

    # Web interface
    path('', include('deepgis_xr.apps.web.urls')),

    # Authentication URLs
    path('auth/', include('deepgis_xr.apps.auth.urls')),

    # API endpoints
    path('api/v1/', include('deepgis_xr.apps.api.v1.urls')),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)