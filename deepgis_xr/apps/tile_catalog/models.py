"""Tile catalog: hierarchical metadata for the MBTiles served by tileserver-gl.

The frontend consumes this catalog to render a three-tier UI
(Site -> Dataset -> Timestep|Product) instead of the flat checkbox list
it used to scrape from ``/data.json``.

The four models map onto the natural shape of the data we have:

* :class:`Site` -- a geographic place (PHX wildfire, Bishop CA, Hawaii,
  Italy/Veneto). Every Site has a bbox so the frontend can offer a
  "fly-to" and a "filter to viewport" UX.
* :class:`Dataset` -- a coherent body of data within a Site
  (e.g. "wildfire orthophotos", "rock surface imagery", "rock polygons").
  ``kind`` controls the shape of its children: ``timeseries`` datasets
  have many :class:`Timestep` rows, each owning some products;
  ``single`` and ``multiband`` datasets attach products directly.
* :class:`Timestep` -- one date/snapshot in a timeseries dataset.
* :class:`Product` -- a single MBTiles layer (1:1 with a tileserver-gl
  layer id), tagged with its product kind and a default opacity.

Catalog editing happens in the Django admin. The ``GET
/api/v1/tile-catalog/`` view serves a denormalised JSON tree that the
frontend turns into UI directly.
"""
from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import models


class TimestampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Site(TimestampedModel):
    """A geographic place. The Tier-1 grouping in the UI."""

    slug = models.SlugField(
        max_length=80, unique=True,
        help_text="Stable identifier used in URLs and admin filters, e.g. 'phx_wildfire'.",
    )
    name = models.CharField(
        max_length=200,
        help_text="Human-readable site name, e.g. 'Phoenix wildfire site'.",
    )
    description = models.TextField(blank=True)
    bounds = models.JSONField(
        help_text="[west, south, east, north] in WGS84 degrees. "
                  "Used for fly-to and viewport-intersect filtering.",
    )
    default_zoom = models.PositiveSmallIntegerField(
        default=15,
        help_text="Initial zoom level when the user picks this site.",
    )
    default_camera_pitch = models.FloatField(
        null=True, blank=True,
        help_text="Optional camera pitch in degrees for fly-to "
                  "(useful for 3D-mesh sites; null for top-down).",
    )
    ordering = models.PositiveSmallIntegerField(
        default=0,
        help_text="Lower values render first in the site picker.",
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Hide from frontend without deleting (keeps history).",
    )

    class Meta:
        ordering = ['ordering', 'slug']
        verbose_name = 'site'
        verbose_name_plural = 'sites'

    def __str__(self) -> str:
        return f"{self.name} ({self.slug})"

    def clean(self):
        super().clean()
        if not isinstance(self.bounds, (list, tuple)) or len(self.bounds) != 4:
            raise ValidationError({'bounds': 'Must be a 4-element [west, south, east, north] array.'})
        try:
            w, s, e, n = (float(v) for v in self.bounds)
        except (TypeError, ValueError) as exc:
            raise ValidationError({'bounds': f'All four values must be numeric: {exc}'})
        if not (-180.0 <= w <= 180.0 and -180.0 <= e <= 180.0):
            raise ValidationError({'bounds': 'Longitudes must be in [-180, 180].'})
        if not (-90.0 <= s <= 90.0 and -90.0 <= n <= 90.0):
            raise ValidationError({'bounds': 'Latitudes must be in [-90, 90].'})
        if s > n:
            raise ValidationError({'bounds': 'south must be <= north.'})


class Dataset(TimestampedModel):
    """A coherent body of data within a Site."""

    KIND_TIMESERIES = 'timeseries'
    KIND_SINGLE = 'single'
    KIND_MULTIBAND = 'multiband'
    KIND_CHOICES = [
        (KIND_TIMESERIES, 'Time series (multiple timesteps)'),
        (KIND_SINGLE, 'Single timestep, multi-product'),
        (KIND_MULTIBAND, 'Single timestep, multi-band'),
    ]

    site = models.ForeignKey(
        Site, on_delete=models.CASCADE, related_name='datasets',
    )
    slug = models.SlugField(max_length=80)
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    kind = models.CharField(max_length=20, choices=KIND_CHOICES)
    ordering = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = [('site', 'slug')]
        ordering = ['site', 'ordering', 'slug']
        verbose_name = 'dataset'
        verbose_name_plural = 'datasets'

    def __str__(self) -> str:
        return f"{self.site.slug} / {self.slug} ({self.kind})"


class Timestep(TimestampedModel):
    """One snapshot in a timeseries Dataset."""

    dataset = models.ForeignKey(
        Dataset, on_delete=models.CASCADE, related_name='timesteps',
    )
    label = models.CharField(
        max_length=50,
        help_text="UI label, e.g. '2020-08' or 'Q4 2020'.",
    )
    sort_key = models.CharField(
        max_length=50,
        help_text="Sortable key (ISO date is ideal). Used to order the time scrubber.",
    )
    description = models.TextField(blank=True)

    class Meta:
        unique_together = [('dataset', 'label')]
        ordering = ['dataset', 'sort_key']
        verbose_name = 'timestep'
        verbose_name_plural = 'timesteps'

    def __str__(self) -> str:
        return f"{self.dataset.site.slug} / {self.dataset.slug} @ {self.label}"

    def clean(self):
        super().clean()
        if self.dataset_id and self.dataset.kind != Dataset.KIND_TIMESERIES:
            raise ValidationError(
                {'dataset': f"Timesteps may only attach to datasets of kind 'timeseries'; "
                            f"this dataset is '{self.dataset.kind}'."}
            )


class Product(TimestampedModel):
    """One layer in tileserver-gl. The atomic unit the frontend toggles on/off."""

    KIND_ORTHOPHOTO = 'orthophoto'
    KIND_VECTOR = 'vector'
    KIND_MESH_3D = 'mesh_3d'
    KIND_PCA = 'pca'
    KIND_RGB_LOW_ZOOM = 'rgb_low_zoom'
    KIND_KMEANS = 'kmeans'
    KIND_POLYGONS = 'polygons'
    KIND_RAW = 'raw'
    KIND_OTHER = 'other'
    KIND_CHOICES = [
        (KIND_ORTHOPHOTO, 'Orthophoto / RGB raster'),
        (KIND_VECTOR, 'Vector features'),
        (KIND_MESH_3D, '3D mesh / DSM'),
        (KIND_PCA, 'PCA composite / band'),
        (KIND_RGB_LOW_ZOOM, 'RGB at coarse zoom'),
        (KIND_KMEANS, 'Classification (k-means etc.)'),
        (KIND_POLYGONS, 'Vector polygons'),
        (KIND_RAW, 'Raw point cloud / source data'),
        (KIND_OTHER, 'Other'),
    ]

    dataset = models.ForeignKey(
        Dataset, on_delete=models.CASCADE, related_name='products',
    )
    timestep = models.ForeignKey(
        Timestep, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='products',
        help_text="Required for timeseries datasets; must be empty for single/multiband datasets.",
    )
    layer_id = models.CharField(
        max_length=200, unique=True,
        help_text="The tileserver-gl layer id (e.g. 'bf_aug_2020_raster'). "
                  "Must exist in /data.json for the layer to be usable.",
    )
    kind = models.CharField(max_length=20, choices=KIND_CHOICES)
    label = models.CharField(
        max_length=200,
        help_text="Human-friendly label shown in the UI, e.g. 'RGB orthophoto (z15-23)'.",
    )
    description = models.TextField(blank=True)
    default_opacity = models.FloatField(
        default=0.7,
        help_text="Initial opacity slider position, 0-1.",
    )
    ordering = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['dataset', 'timestep__sort_key', 'ordering', 'kind']
        verbose_name = 'product'
        verbose_name_plural = 'products'

    def __str__(self) -> str:
        time_part = f" @ {self.timestep.label}" if self.timestep_id else ''
        return f"{self.layer_id} [{self.kind}]{time_part}"

    def clean(self):
        super().clean()
        if not (0.0 <= float(self.default_opacity) <= 1.0):
            raise ValidationError({'default_opacity': 'Must be between 0 and 1.'})
        if not self.dataset_id:
            return
        if self.dataset.kind == Dataset.KIND_TIMESERIES and self.timestep_id is None:
            raise ValidationError(
                {'timestep': "Required for products in timeseries datasets."}
            )
        if self.dataset.kind in (Dataset.KIND_SINGLE, Dataset.KIND_MULTIBAND) and self.timestep_id is not None:
            raise ValidationError(
                {'timestep': "Must be empty for single/multiband datasets."}
            )
        if self.timestep_id and self.timestep.dataset_id != self.dataset_id:
            raise ValidationError(
                {'timestep': "Timestep must belong to the same dataset as this product."}
            )
