"""Audit drift between the tile catalog and what tileserver-gl actually serves.

Run::

    python manage.py validate_tile_catalog [--tileserver http://tileserver:80]

Reports two classes of issue:

1. **Catalog -> tileserver:** catalog Products whose ``layer_id`` does not
   exist in tileserver's ``/data.json``. These will silently fail to load
   for users.

2. **Tileserver -> catalog:** layers served by tileserver-gl that have
   no Product row in the catalog. These are reachable by direct URL but
   won't appear in the hierarchical UI.

Exit status is non-zero when the catalog has missing layers (class 1).
Class 2 (orphan layers) is reported but not treated as a failure --
admins are expected to add Products through the admin when activating
new layers.
"""
from __future__ import annotations

import sys

import requests
from django.conf import settings
from django.core.management.base import BaseCommand

from deepgis_xr.apps.tile_catalog.models import Product


class Command(BaseCommand):
    help = "Audit drift between the tile catalog and tileserver-gl's /data.json."

    def add_arguments(self, parser):
        parser.add_argument(
            '--tileserver',
            default=getattr(settings, 'TILESERVER_URL', 'http://tileserver:80'),
            help='Base URL of the tileserver-gl service. '
                 'Defaults to settings.TILESERVER_URL or http://tileserver:80.',
        )
        parser.add_argument(
            '--timeout',
            type=int, default=10,
            help='HTTP timeout for the /data.json probe (seconds).',
        )

    def handle(self, *args, **opts):
        tileserver = opts['tileserver'].rstrip('/')
        url = f'{tileserver}/data.json'
        self.stdout.write(f'Probing {url} ...')

        try:
            resp = requests.get(url, timeout=opts['timeout'])
            resp.raise_for_status()
            payload = resp.json()
        except requests.RequestException as exc:
            self.stderr.write(self.style.ERROR(f'Could not reach tileserver: {exc}'))
            sys.exit(2)
        except ValueError as exc:
            self.stderr.write(self.style.ERROR(f'Invalid JSON from tileserver: {exc}'))
            sys.exit(2)

        served_ids = self._extract_layer_ids(payload)
        if not served_ids:
            self.stderr.write(self.style.WARNING('Tileserver returned no layers.'))

        catalog_ids = set(
            Product.objects.filter(is_active=True).values_list('layer_id', flat=True)
        )

        catalog_missing = sorted(catalog_ids - served_ids)
        tileserver_orphans = sorted(served_ids - catalog_ids)

        ok = True

        if catalog_missing:
            ok = False
            self.stdout.write(self.style.ERROR(
                f'\n{len(catalog_missing)} catalog Product(s) reference layers tileserver does not serve:'
            ))
            for layer_id in catalog_missing:
                self.stdout.write(self.style.ERROR(f'  - {layer_id}'))
            self.stdout.write(
                "  Fix: either un-set is_active on the Product, "
                "remove it, or add the MBTiles to the tileserver config."
            )

        if tileserver_orphans:
            self.stdout.write(self.style.WARNING(
                f'\n{len(tileserver_orphans)} layer(s) served by tileserver are not in the catalog:'
            ))
            for layer_id in tileserver_orphans:
                self.stdout.write(self.style.WARNING(f'  - {layer_id}'))
            self.stdout.write(
                "  These work via direct URL but don't appear in the hierarchical UI. "
                "Add them via the Django admin if you want them visible."
            )

        if ok and not tileserver_orphans:
            self.stdout.write(self.style.SUCCESS(
                f'\nCatalog and tileserver agree: {len(catalog_ids)} layer(s) on both sides.'
            ))
        elif ok:
            self.stdout.write(self.style.SUCCESS(
                f'\nNo missing layers; {len(tileserver_orphans)} orphan(s) reported above.'
            ))
        else:
            sys.exit(1)

    @staticmethod
    def _extract_layer_ids(payload) -> set[str]:
        """tileserver-gl /data.json is normally a JSON array of objects with
        an ``id`` field, but older builds returned a dict keyed by id. Handle both.
        """
        ids: set[str] = set()
        if isinstance(payload, list):
            for entry in payload:
                if isinstance(entry, dict) and entry.get('id'):
                    ids.add(entry['id'])
        elif isinstance(payload, dict):
            ids = {key for key, value in payload.items() if isinstance(value, dict)}
        return ids
