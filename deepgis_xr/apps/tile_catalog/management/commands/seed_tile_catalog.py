"""Idempotent bootstrap of the tile catalog from the known live layers.

Run once after the initial migration::

    python manage.py seed_tile_catalog

It seeds the four Sites the team currently uses:

* Phoenix, AZ wildfire (timeseries: 5 dates, 10 products)
* Bishop, CA rock surface (single timestep, 1 product currently active)

Hawaii and Italy MBTiles exist on disk but are not currently in
``data/config.json`` so they aren't served by tileserver-gl. They're
left out of the seed; an admin can add them via the Django admin once
the underlying MBTiles are activated.

The command is idempotent: existing Sites/Datasets/Timesteps/Products
(matched by their natural keys: site.slug, dataset.slug, timestep.label,
product.layer_id) are updated in place; nothing is deleted.

Pass ``--force-update`` to overwrite editable fields (name, description,
ordering, default_opacity) on existing rows. By default these are left
alone so admin edits aren't clobbered on re-run.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from deepgis_xr.apps.tile_catalog.models import Dataset, Product, Site, Timestep


# --------------------------------------------------------------------------- #
# Catalog seed data. Edit here when adding a new site/timestep/product.       #
# --------------------------------------------------------------------------- #

SITES = [
    {
        'slug': 'phx_wildfire',
        'name': 'Phoenix wildfire site',
        'description': (
            'Multi-temporal aerial survey of a wildfire-affected site '
            'near Phoenix, Arizona. Covers Aug 2020 through Feb 2021.'
        ),
        'bounds': [-111.267, 33.781, -111.262, 33.784],
        'default_zoom': 18,
        'default_camera_pitch': None,
        'ordering': 0,
        'datasets': [
            {
                'slug': 'wildfire_orthos',
                'name': 'Wildfire orthophotos & features',
                'description': 'Orthophoto rasters, vector features, and 3D mesh per timestep.',
                'kind': Dataset.KIND_TIMESERIES,
                'ordering': 0,
                'timesteps': [
                    {
                        'label': '2020-08',
                        'sort_key': '2020-08-02',
                        'description': 'August 2020 survey.',
                        'products': [
                            {
                                'layer_id': 'bf_aug_2020_raster',
                                'kind': Product.KIND_ORTHOPHOTO,
                                'label': 'Orthophoto (Aug 2020)',
                                'default_opacity': 0.7,
                                'ordering': 0,
                            },
                            {
                                'layer_id': 'bf_aug_2020',
                                'kind': Product.KIND_VECTOR,
                                'label': 'Vector features (Aug 2020)',
                                'default_opacity': 0.8,
                                'ordering': 1,
                            },
                        ],
                    },
                    {
                        'label': '2020-10',
                        'sort_key': '2020-10-03',
                        'description': 'October 2020 survey.',
                        'products': [
                            {
                                'layer_id': 'bf_oct_2020_raster',
                                'kind': Product.KIND_ORTHOPHOTO,
                                'label': 'Orthophoto (Oct 2020)',
                                'default_opacity': 0.7,
                                'ordering': 0,
                            },
                            {
                                'layer_id': 'bf_oct_2020',
                                'kind': Product.KIND_VECTOR,
                                'label': 'Vector features (Oct 2020)',
                                'default_opacity': 0.8,
                                'ordering': 1,
                            },
                        ],
                    },
                    {
                        'label': '2020-11',
                        'sort_key': '2020-11-13',
                        'description': 'November 2020 survey (vector only).',
                        'products': [
                            {
                                'layer_id': 'bf_nov_2020',
                                'kind': Product.KIND_VECTOR,
                                'label': 'Vector features (Nov 2020)',
                                'default_opacity': 0.8,
                                'ordering': 0,
                            },
                        ],
                    },
                    {
                        'label': '2020-12',
                        'sort_key': '2020-12-20',
                        'description': 'December 2020 survey. Three vector snapshots exist; the canonical one is bf_dec_2020.',
                        'products': [
                            {
                                'layer_id': 'bf_dec_2020',
                                'kind': Product.KIND_VECTOR,
                                'label': 'Vector features (Dec 2020)',
                                'default_opacity': 0.8,
                                'ordering': 0,
                            },
                            {
                                # tileserver-gl auto-discovers this from the filename
                                # BF_12-20-2020.mbtiles. The data/config.json alias
                                # 'bf_dec_2020_alt' is not honored, so we use the served id.
                                'layer_id': 'BF_12-20-2020',
                                'kind': Product.KIND_VECTOR,
                                'label': 'Vector features (Dec 2020, alt snapshot)',
                                'default_opacity': 0.6,
                                'ordering': 1,
                            },
                            {
                                'layer_id': 'bf_dec_2020_vector',
                                'kind': Product.KIND_VECTOR,
                                'label': 'Vector features (Dec 2020, third snapshot)',
                                'default_opacity': 0.6,
                                'ordering': 2,
                            },
                        ],
                    },
                    {
                        'label': '2021-02',
                        'sort_key': '2021-02-15',
                        'description': 'February 2021 — 3D mesh / DSM only.',
                        'products': [
                            {
                                'layer_id': 'bf_feb_2021_3d',
                                'kind': Product.KIND_MESH_3D,
                                'label': '3D mesh (Feb 2021)',
                                'default_opacity': 1.0,
                                'ordering': 0,
                            },
                            {
                                'layer_id': 'bf_feb_2021_3d_43',
                                'kind': Product.KIND_MESH_3D,
                                'label': '3D mesh (Feb 2021, 4:3 variant)',
                                'default_opacity': 1.0,
                                'ordering': 1,
                            },
                        ],
                    },
                ],
            },
        ],
    },
    {
        'slug': 'bishop_ca',
        'name': 'Bishop, CA — rock surface site',
        'description': (
            'Single-time, high-resolution orthophoto of a rock-surface '
            'study area near Bishop, California. C3 / PCA / vector '
            'companion products live as MBTiles on disk and can be '
            'activated by adding them to data/config.json and then '
            'creating Product rows in the admin.'
        ),
        'bounds': [-118.444, 37.450, -118.441, 37.455],
        'default_zoom': 19,
        'default_camera_pitch': None,
        'ordering': 1,
        'datasets': [
            {
                'slug': 'rock_imagery',
                'name': 'Rock surface imagery',
                'description': 'High-resolution orthophoto of the Bishop rock-surface scene.',
                'kind': Dataset.KIND_SINGLE,
                'ordering': 0,
                'products': [
                    {
                        'layer_id': 'rock_tiles_deepgis',
                        'kind': Product.KIND_ORTHOPHOTO,
                        'label': 'RGB orthophoto (z15-23)',
                        'default_opacity': 1.0,
                        'ordering': 0,
                    },
                ],
            },
        ],
    },
]


# --------------------------------------------------------------------------- #
# Command implementation                                                      #
# --------------------------------------------------------------------------- #


class Command(BaseCommand):
    help = 'Idempotently bootstrap the tile catalog with the four known sites.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--force-update',
            action='store_true',
            help='Overwrite editable fields (name, description, ordering, default_opacity) '
                 'on existing rows. By default these are left alone so admin edits survive.',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Print what would be created/updated without writing to the database.',
        )

    def handle(self, *args, **opts):
        force = opts['force_update']
        dry_run = opts['dry_run']

        stats = {'sites': 0, 'datasets': 0, 'timesteps': 0, 'products': 0}
        with transaction.atomic():
            for site_def in SITES:
                self._upsert_site(site_def, force=force, dry_run=dry_run, stats=stats)
            if dry_run:
                self.stdout.write(self.style.WARNING('DRY RUN: rolling back.'))
                transaction.set_rollback(True)

        self.stdout.write(self.style.SUCCESS(
            f"Catalog seed complete: {stats['sites']} sites, "
            f"{stats['datasets']} datasets, {stats['timesteps']} timesteps, "
            f"{stats['products']} products."
        ))

    # ----- helpers --------------------------------------------------------- #

    def _upsert_site(self, site_def, *, force, dry_run, stats):
        slug = site_def['slug']
        defaults = {
            'name': site_def['name'],
            'description': site_def['description'],
            'bounds': site_def['bounds'],
            'default_zoom': site_def['default_zoom'],
            'default_camera_pitch': site_def['default_camera_pitch'],
            'ordering': site_def['ordering'],
            'is_active': True,
        }
        site, created = Site.objects.get_or_create(slug=slug, defaults=defaults)
        if created:
            self.stdout.write(self.style.SUCCESS(f'+ Site {slug}'))
        elif force:
            for field, value in defaults.items():
                setattr(site, field, value)
            site.save()
            self.stdout.write(f'~ Site {slug} (force-updated)')
        else:
            self.stdout.write(f'= Site {slug} (kept admin edits)')
        stats['sites'] += 1

        for ds_def in site_def['datasets']:
            self._upsert_dataset(site, ds_def, force=force, dry_run=dry_run, stats=stats)

    def _upsert_dataset(self, site, ds_def, *, force, dry_run, stats):
        defaults = {
            'name': ds_def['name'],
            'description': ds_def['description'],
            'kind': ds_def['kind'],
            'ordering': ds_def['ordering'],
            'is_active': True,
        }
        dataset, created = Dataset.objects.get_or_create(
            site=site, slug=ds_def['slug'], defaults=defaults,
        )
        if created:
            self.stdout.write(self.style.SUCCESS(
                f'  + Dataset {site.slug}/{ds_def["slug"]} ({ds_def["kind"]})'
            ))
        elif force:
            for field, value in defaults.items():
                setattr(dataset, field, value)
            dataset.save()
            self.stdout.write(f'  ~ Dataset {site.slug}/{ds_def["slug"]} (force-updated)')
        else:
            self.stdout.write(f'  = Dataset {site.slug}/{ds_def["slug"]} (kept admin edits)')
        stats['datasets'] += 1

        if ds_def['kind'] == Dataset.KIND_TIMESERIES:
            for ts_def in ds_def.get('timesteps', []):
                self._upsert_timestep(dataset, ts_def, force=force, dry_run=dry_run, stats=stats)
        else:
            for prod_def in ds_def.get('products', []):
                self._upsert_product(
                    dataset, prod_def, timestep=None,
                    force=force, dry_run=dry_run, stats=stats,
                )

    def _upsert_timestep(self, dataset, ts_def, *, force, dry_run, stats):
        defaults = {
            'sort_key': ts_def['sort_key'],
            'description': ts_def.get('description', ''),
        }
        timestep, created = Timestep.objects.get_or_create(
            dataset=dataset, label=ts_def['label'], defaults=defaults,
        )
        if created:
            self.stdout.write(self.style.SUCCESS(
                f'    + Timestep {dataset.site.slug}/{dataset.slug}@{ts_def["label"]}'
            ))
        elif force:
            for field, value in defaults.items():
                setattr(timestep, field, value)
            timestep.save()
            self.stdout.write(f'    ~ Timestep {dataset.site.slug}/{dataset.slug}@{ts_def["label"]} (force-updated)')
        else:
            self.stdout.write(f'    = Timestep {dataset.site.slug}/{dataset.slug}@{ts_def["label"]} (kept admin edits)')
        stats['timesteps'] += 1

        for prod_def in ts_def.get('products', []):
            self._upsert_product(
                dataset, prod_def, timestep=timestep,
                force=force, dry_run=dry_run, stats=stats,
            )

    def _upsert_product(self, dataset, prod_def, *, timestep, force, dry_run, stats):
        defaults = {
            'dataset': dataset,
            'timestep': timestep,
            'kind': prod_def['kind'],
            'label': prod_def['label'],
            'description': prod_def.get('description', ''),
            'default_opacity': prod_def.get('default_opacity', 0.7),
            'ordering': prod_def.get('ordering', 0),
            'is_active': True,
        }
        product, created = Product.objects.get_or_create(
            layer_id=prod_def['layer_id'], defaults=defaults,
        )
        prefix = '      '
        ts_label = f'@{timestep.label}' if timestep else ''
        if created:
            self.stdout.write(self.style.SUCCESS(
                f'{prefix}+ Product {prod_def["layer_id"]}{ts_label} [{prod_def["kind"]}]'
            ))
        elif force:
            for field, value in defaults.items():
                setattr(product, field, value)
            product.save()
            self.stdout.write(f'{prefix}~ Product {prod_def["layer_id"]}{ts_label} (force-updated)')
        else:
            self.stdout.write(f'{prefix}= Product {prod_def["layer_id"]}{ts_label} (kept admin edits)')
        stats['products'] += 1
