"""Tile catalog API.

GET /api/v1/tile-catalog/   -- the full catalog tree (read-only).
"""
from __future__ import annotations

from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from .models import Site
from .serializers import SiteCatalogSerializer


CATALOG_VERSION = 1


@api_view(['GET'])
@permission_classes([AllowAny])
def tile_catalog(_request):
    """Return the hierarchical tile catalog used by the frontend."""
    sites_qs = (
        Site.objects.filter(is_active=True)
        .order_by('ordering', 'slug')
        .prefetch_related(
            'datasets',
            'datasets__timesteps',
            'datasets__products',
            'datasets__timesteps__products',
        )
    )
    sites = SiteCatalogSerializer(sites_qs, many=True).data

    return Response({
        'version': CATALOG_VERSION,
        'generated_at': timezone.now().isoformat(),
        'sites': sites,
    })
