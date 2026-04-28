from django.urls import path

from .views import tile_catalog


urlpatterns = [
    path('', tile_catalog, name='tile_catalog'),
]
