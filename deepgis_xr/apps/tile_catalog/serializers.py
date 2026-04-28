"""DRF serializers for ``GET /api/v1/tile-catalog/``.

The endpoint returns one denormalised tree per request -- the frontend
loads it once on boot and groups the existing ``/data.json`` layers by
matching ``layer_id``. We keep the response shape stable
(``"version": 1``) so future schema additions can ride alongside it
without breaking older frontends.
"""
from __future__ import annotations

from rest_framework import serializers

from .models import Dataset, Product, Site, Timestep


class ProductCatalogSerializer(serializers.ModelSerializer):
    class Meta:
        model = Product
        fields = (
            'layer_id', 'kind', 'label', 'description',
            'default_opacity', 'ordering',
        )


class TimestepCatalogSerializer(serializers.ModelSerializer):
    products = serializers.SerializerMethodField()

    class Meta:
        model = Timestep
        fields = ('label', 'sort_key', 'description', 'products')

    def get_products(self, obj: Timestep):
        qs = obj.products.filter(is_active=True).order_by('ordering', 'kind')
        return ProductCatalogSerializer(qs, many=True).data


class DatasetCatalogSerializer(serializers.ModelSerializer):
    timesteps = serializers.SerializerMethodField()
    products = serializers.SerializerMethodField()

    class Meta:
        model = Dataset
        fields = (
            'slug', 'name', 'description', 'kind', 'ordering',
            'timesteps', 'products',
        )

    def get_timesteps(self, obj: Dataset):
        if obj.kind != Dataset.KIND_TIMESERIES:
            return []
        qs = obj.timesteps.all().order_by('sort_key')
        return TimestepCatalogSerializer(qs, many=True).data

    def get_products(self, obj: Dataset):
        # For timeseries datasets, products are nested inside timesteps;
        # we omit them at the top level to keep the response unambiguous.
        if obj.kind == Dataset.KIND_TIMESERIES:
            return []
        qs = obj.products.filter(is_active=True, timestep__isnull=True).order_by('ordering', 'kind')
        return ProductCatalogSerializer(qs, many=True).data


class SiteCatalogSerializer(serializers.ModelSerializer):
    datasets = serializers.SerializerMethodField()

    class Meta:
        model = Site
        fields = (
            'slug', 'name', 'description', 'bounds',
            'default_zoom', 'default_camera_pitch', 'ordering',
            'datasets',
        )

    def get_datasets(self, obj: Site):
        qs = obj.datasets.filter(is_active=True).order_by('ordering', 'slug')
        return DatasetCatalogSerializer(qs, many=True).data
