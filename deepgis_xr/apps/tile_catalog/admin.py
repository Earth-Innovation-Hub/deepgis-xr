"""Admin pages for the tile catalog.

The intended editing flow is top-down:

1. Open a Site, see a panel of its Datasets inline.
2. Click into a Dataset; if it's a timeseries the Timesteps appear inline,
   otherwise its Products appear inline directly.
3. Click into a Timestep; its Products appear inline.

We use stacked inlines for Datasets/Timesteps (rich form fields) and
tabular inlines for Products (compact: many products per page).
"""
from __future__ import annotations

from django.contrib import admin
from django.utils.html import format_html

from .models import Dataset, Product, Site, Timestep


class ProductInline(admin.TabularInline):
    model = Product
    extra = 0
    fields = ('layer_id', 'kind', 'label', 'timestep', 'default_opacity', 'ordering', 'is_active')
    autocomplete_fields = ('timestep',)
    show_change_link = True


class TimestepInline(admin.StackedInline):
    model = Timestep
    extra = 0
    fields = ('label', 'sort_key', 'description')
    show_change_link = True


class DatasetInline(admin.StackedInline):
    model = Dataset
    extra = 0
    fields = ('slug', 'name', 'kind', 'description', 'ordering', 'is_active')
    show_change_link = True


@admin.register(Site)
class SiteAdmin(admin.ModelAdmin):
    list_display = ('slug', 'name', 'dataset_count', 'product_count', 'ordering', 'is_active')
    list_filter = ('is_active',)
    search_fields = ('slug', 'name', 'description')
    ordering = ('ordering', 'slug')
    inlines = [DatasetInline]
    fieldsets = (
        (None, {
            'fields': ('slug', 'name', 'description', 'is_active', 'ordering'),
        }),
        ('Geography', {
            'fields': ('bounds', 'default_zoom', 'default_camera_pitch'),
            'description': "bounds is a JSON array [west, south, east, north] in WGS84 degrees.",
        }),
    )

    @admin.display(description='datasets')
    def dataset_count(self, obj: Site) -> int:
        return obj.datasets.count()

    @admin.display(description='products')
    def product_count(self, obj: Site) -> int:
        return Product.objects.filter(dataset__site=obj).count()


@admin.register(Dataset)
class DatasetAdmin(admin.ModelAdmin):
    list_display = ('site', 'slug', 'name', 'kind', 'product_count', 'ordering', 'is_active')
    list_filter = ('kind', 'is_active', 'site')
    search_fields = ('slug', 'name', 'description', 'site__slug', 'site__name')
    autocomplete_fields = ('site',)
    ordering = ('site', 'ordering', 'slug')

    def get_inlines(self, request, obj):
        # Show Timesteps inline only for timeseries datasets, otherwise Products.
        if obj is None:
            return []
        if obj.kind == Dataset.KIND_TIMESERIES:
            return [TimestepInline, ProductInline]
        return [ProductInline]

    @admin.display(description='products')
    def product_count(self, obj: Dataset) -> int:
        return obj.products.count()


@admin.register(Timestep)
class TimestepAdmin(admin.ModelAdmin):
    list_display = ('dataset', 'label', 'sort_key', 'product_count')
    list_filter = ('dataset__site', 'dataset')
    search_fields = ('label', 'description', 'dataset__slug', 'dataset__site__slug')
    autocomplete_fields = ('dataset',)
    ordering = ('dataset', 'sort_key')
    inlines = [ProductInline]

    @admin.display(description='products')
    def product_count(self, obj: Timestep) -> int:
        return obj.products.count()


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = (
        'layer_id', 'kind', 'site_label', 'dataset_label',
        'timestep_label', 'default_opacity', 'is_active',
    )
    list_filter = ('kind', 'is_active', 'dataset__site', 'dataset')
    search_fields = ('layer_id', 'label', 'description', 'dataset__slug', 'dataset__site__slug')
    autocomplete_fields = ('dataset', 'timestep')
    ordering = ('dataset', 'timestep__sort_key', 'ordering')

    @admin.display(description='site', ordering='dataset__site__slug')
    def site_label(self, obj: Product) -> str:
        return obj.dataset.site.slug if obj.dataset_id else '-'

    @admin.display(description='dataset', ordering='dataset__slug')
    def dataset_label(self, obj: Product) -> str:
        return obj.dataset.slug if obj.dataset_id else '-'

    @admin.display(description='timestep')
    def timestep_label(self, obj: Product) -> str:
        return format_html('<code>{}</code>', obj.timestep.label) if obj.timestep_id else '—'
