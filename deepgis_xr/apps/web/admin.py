"""
Django Admin for World Sampler Models
"""

import json
from collections import Counter
from pathlib import Path
from urllib.parse import urlencode

from django.contrib import admin, messages
from django.http import (
    FileResponse,
    Http404,
    HttpResponse,
    HttpResponseRedirect,
    JsonResponse,
)
from django.shortcuts import get_object_or_404
from django.urls import path, reverse
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from .models import (
    DistributionUpdate,
    SampledLocation,
    SamplingSession,
    SceneGraph,
)


def _fmt_float(v, ndigits: int = 6) -> str:
    """Format a possibly-None / possibly-tiny float for the admin grid.

    Tight-precision values like the Fiedler eigenvalue (~1e-6) should
    not be flattened to ``0.000`` by ``round``; switch to scientific
    notation under 1e-3 so the structure is still visible.
    """
    try:
        x = float(v)
    except (TypeError, ValueError):
        return '—' if v is None else str(v)
    if x == 0.0:
        return '0'
    if abs(x) < 1e-3:
        return f'{x:.3e}'
    return f'{x:.{ndigits}g}'


class HasFeedbackFilter(admin.SimpleListFilter):
    """Filter for locations with user feedback"""
    title = 'Has Feedback'
    parameter_name = 'has_feedback'
    
    def lookups(self, request, model_admin):
        return (
            ('yes', 'With Feedback'),
            ('no', 'Without Feedback'),
        )
    
    def queryset(self, request, queryset):
        if self.value() == 'yes':
            return queryset.filter(scored_at__isnull=False)
        if self.value() == 'no':
            return queryset.filter(scored_at__isnull=True)
        return queryset


class ScoreRangeFilter(admin.SimpleListFilter):
    """Filter by score range"""
    title = 'Score Range'
    parameter_name = 'score_range'
    
    def lookups(self, request, model_admin):
        return (
            ('positive', 'Positive (> 0)'),
            ('negative', 'Negative (< 0)'),
            ('neutral', 'Neutral (= 0)'),
        )
    
    def queryset(self, request, queryset):
        if self.value() == 'positive':
            return queryset.filter(score__gt=0)
        if self.value() == 'negative':
            return queryset.filter(score__lt=0)
        if self.value() == 'neutral':
            return queryset.filter(score=0)
        return queryset


@admin.register(SampledLocation)
class SampledLocationAdmin(admin.ModelAdmin):
    list_display = [
        'id',
        'location_display',
        'zoom_level',
        'score_display',
        'weight_display',
        'session_id',
        'sampled_at',
        'feedback_status',
        'view_on_map'
    ]
    list_filter = [
        HasFeedbackFilter,
        ScoreRangeFilter,
        'session_id',
        'zoom_level',
        'sampled_at',
    ]
    search_fields = [
        'latitude',
        'longitude',
        'session_id',
    ]
    readonly_fields = [
        'sampled_at',
        'view_on_map_link',
    ]
    ordering = ['-scored_at', '-sampled_at']
    list_per_page = 50
    
    fieldsets = (
        ('Location', {
            'fields': ('latitude', 'longitude', 'altitude', 'zoom_level', 'view_on_map_link')
        }),
        ('Scoring', {
            'fields': ('score', 'weight')
        }),
        ('Session', {
            'fields': ('session_id', 'user')
        }),
        ('Timestamps', {
            'fields': ('sampled_at', 'scored_at')
        }),
        ('Metadata', {
            'fields': ('metadata',),
            'classes': ('collapse',)
        }),
    )
    
    def location_display(self, obj):
        """Display location as formatted coordinates"""
        return format_html(
            '<span title="Lat: {}, Lon: {}, Alt: {}m">{:.4f}°, {:.4f}°</span>',
            obj.latitude, obj.longitude, obj.altitude,
            obj.latitude, obj.longitude
        )
    location_display.short_description = 'Location (Lat, Lon)'
    
    def score_display(self, obj):
        """Display score with color coding"""
        if obj.score > 0:
            color = '#28a745'  # Green for positive
            icon = '👍'
        elif obj.score < 0:
            color = '#dc3545'  # Red for negative
            icon = '👎'
        else:
            color = '#6c757d'  # Gray for neutral
            icon = '—'
        
        return format_html(
            '<span style="color: {}; font-weight: bold;">{} {:.2f}</span>',
            color, icon, obj.score
        )
    score_display.short_description = 'Score'
    score_display.admin_order_field = 'score'
    
    def weight_display(self, obj):
        """Display weight in scientific notation"""
        return format_html(
            '<span style="font-family: monospace;">{:.4f}</span>',
            obj.weight
        )
    weight_display.short_description = 'Weight'
    weight_display.admin_order_field = 'weight'
    
    def feedback_status(self, obj):
        """Display whether location has been scored"""
        if obj.scored_at:
            return format_html(
                '<span style="color: #28a745;">✓ Scored</span>'
            )
        return format_html(
            '<span style="color: #6c757d;">○ Not scored</span>'
        )
    feedback_status.short_description = 'Feedback'
    feedback_status.admin_order_field = 'scored_at'
    
    def view_on_map(self, obj):
        """Link to view location on DeepGIS Search"""
        url = f'/label/3d/search/#lat={obj.latitude}&lon={obj.longitude}&zoom={obj.zoom_level}'
        return format_html(
            '<a href="{}" target="_blank" style="color: #007bff;">🌍 Map</a>',
            url
        )
    view_on_map.short_description = 'View'
    
    def view_on_map_link(self, obj):
        """Full link for detail view"""
        if obj.pk:
            url = f'/label/3d/search/#lat={obj.latitude}&lon={obj.longitude}&zoom={obj.zoom_level}'
            return format_html(
                '<a href="{}" target="_blank">View this location on DeepGIS Search →</a>',
                url
            )
        return "Save to generate map link"
    view_on_map_link.short_description = 'View on Map'
    
    actions = ['export_as_csv']
    
    def export_as_csv(self, request, queryset):
        """Export selected locations as CSV"""
        import csv
        from django.http import HttpResponse
        
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="sampled_locations.csv"'
        
        writer = csv.writer(response)
        writer.writerow(['ID', 'Latitude', 'Longitude', 'Altitude', 'Zoom Level', 
                        'Score', 'Weight', 'Session ID', 'Sampled At', 'Scored At'])
        
        for obj in queryset:
            writer.writerow([
                obj.id,
                obj.latitude,
                obj.longitude,
                obj.altitude,
                obj.zoom_level,
                obj.score,
                obj.weight,
                obj.session_id,
                obj.sampled_at,
                obj.scored_at or ''
            ])
        
        return response
    export_as_csv.short_description = 'Export selected as CSV'


@admin.register(SamplingSession)
class SamplingSessionAdmin(admin.ModelAdmin):
    list_display = [
        'session_id',
        'user',
        'initialization_method',
        'num_points',
        'total_samples',
        'total_updates',
        'created_at'
    ]
    list_filter = [
        'initialization_method',
        'created_at',
    ]
    search_fields = [
        'session_id',
    ]
    readonly_fields = [
        'created_at',
        'updated_at',
        'total_samples',
        'total_updates',
    ]
    ordering = ['-created_at']
    
    fieldsets = (
        ('Session Info', {
            'fields': ('session_id', 'user')
        }),
        ('Initialization', {
            'fields': (
                'num_points',
                'initialization_method',
                'lat_range_min',
                'lat_range_max',
                'lon_range_min',
                'lon_range_max',
                'alt_range_min',
                'alt_range_max',
            )
        }),
        ('Statistics', {
            'fields': ('total_samples', 'total_updates')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at')
        }),
    )


@admin.register(DistributionUpdate)
class DistributionUpdateAdmin(admin.ModelAdmin):
    list_display = [
        'id',
        'session',
        'update_rule',
        'learning_rate',
        'radius',
        'applied_at'
    ]
    list_filter = [
        'update_rule',
        'applied_at',
    ]
    search_fields = [
        'session__session_id',
    ]
    readonly_fields = [
        'applied_at',
    ]
    ordering = ['-applied_at']
    filter_horizontal = ['feedback_locations']
    
    fieldsets = (
        ('Session', {
            'fields': ('session',)
        }),
        ('Update Parameters', {
            'fields': ('update_rule', 'learning_rate', 'radius')
        }),
        ('Feedback', {
            'fields': ('feedback_locations',)
        }),
        ('Metadata', {
            'fields': ('parameters', 'applied_at'),
            'classes': ('collapse',)
        }),
    )


# ── SceneGraph (Distinction-Game) ───────────────────────────────────────


class SceneGraphKernelFilter(admin.SimpleListFilter):
    """Filter SceneGraphs by which kernel contributed claims.

    The model stores ``kernels_used`` as a JSON list, so we can't lean on
    Django's standard ``list_filter`` machinery. This filter offers the
    canonical kernel ids; selecting one keeps rows whose JSON list
    contains that token (SQLite-safe substring match).
    """
    title = 'Kernel used'
    parameter_name = 'kernel'

    def lookups(self, request, model_admin):
        return (
            ('osm_buildings',  'OSM buildings'),
            ('osm_roads',      'OSM roads'),
            ('mr_rocks',       'Mask R-CNN (rocks)'),
            ('mr_house',       'Mask R-CNN (house/tornado)'),
            ('grounding_dino', 'Grounding DINO'),
            ('grounded_sam',   'Grounded SAM'),
            ('sam',            'SAM'),
        )

    def queryset(self, request, queryset):
        v = self.value()
        if not v:
            return queryset
        # SQLite JSONField: icontains on the serialized list works for
        # the simple "is this token present" question. Good enough for
        # admin filtering; the canonical query lives in the orchestrator.
        return queryset.filter(kernels_used__icontains=v)


@admin.register(SceneGraph)
class SceneGraphAdmin(admin.ModelAdmin):
    """
    Admin panel for fused Distinction-Game SceneGraphs.

    The detail view embeds the same PNG that
    ``apps.web.world_sampler_api.scenegraph_viz`` renders for the CLI
    batch tool — visited PNGs are cached on disk under
    ``/app/deepgis_results/scenegraph_results/<session_id>/visualization.png``
    so re-visits are free; the "Re-render" button forces a fresh build
    when the renderer or palette has changed.
    """

    list_display = [
        'session_id_short',
        'created_at',
        'user',
        'taxonomy_name',
        'kernels_used_short',
        'n_nodes_display',
        'n_edges_display',
        'edge_mode_display',
        'top_categories_display',
        'view_links',
    ]
    list_filter = [
        SceneGraphKernelFilter,
        'taxonomy_name',
        'created_at',
    ]
    search_fields = [
        'session_id',
        'user__username',
        'sampling_session__session_id',
    ]
    readonly_fields = [
        'session_id',
        'created_at',
        'user',
        'sampling_session',
        'taxonomy_name',
        'kernels_used',
        'artifact_path',
        'visualization_preview',
        'viewport_pretty',
        'fusion_metadata_pretty',
        'n_nodes_display',
        'n_edges_display',
        'edge_mode_display',
        'top_categories_display',
        'city_graph_summary',
        'view_links',
    ]
    # All scene-graph rows are write-once outputs of the orchestrator;
    # the admin is for inspection, not authoring. Hide the editable
    # JSON blobs by default — they live in artifact_path on disk and
    # are too large to scroll through in a textarea.
    fieldsets = (
        ('Identity', {
            'fields': (
                'session_id', 'created_at', 'user', 'sampling_session',
                'taxonomy_name', 'view_links',
            ),
        }),
        ('Visualization', {
            'fields': ('visualization_preview',),
        }),
        ('Fusion summary', {
            'fields': (
                'kernels_used', 'n_nodes_display',
                'n_edges_display', 'edge_mode_display',
                'top_categories_display', 'artifact_path',
            ),
        }),
        ('CityGraph backbone (Option A)', {
            'fields': ('city_graph_summary',),
            'description': (
                'Populated when the orchestrator was called with '
                '<code>use_city_graph_regions=True</code> — surfaces '
                'the road-graph + Laplacian spectrum that was spliced '
                'into this SceneGraph.'
            ),
        }),
        ('Viewport (raw)', {
            'fields': ('viewport_pretty',),
            'classes': ('collapse',),
        }),
        ('Fusion metadata (raw)', {
            'fields': ('fusion_metadata_pretty',),
            'classes': ('collapse',),
        }),
    )
    ordering = ['-created_at']
    list_per_page = 25
    actions = [
        'action_render_pngs',
        'action_render_gallery',
        'action_delete_png_artifacts',
    ]

    # ── custom admin URL routes ────────────────────────────────────────
    def get_urls(self):
        """Hang ``visualization.png`` / ``rerender`` / ``payload.json``
        endpoints off the default admin route table.

        We piggy-back on the standard ``app_label/model_name/`` prefix so
        permissions and the admin login wall apply automatically.
        """
        urls = super().get_urls()
        custom = [
            path(
                '<path:object_id>/visualization.png/',
                self.admin_site.admin_view(self.serve_visualization),
                name='web_scenegraph_visualization',
            ),
            path(
                '<path:object_id>/rerender/',
                self.admin_site.admin_view(self.rerender_visualization),
                name='web_scenegraph_rerender',
            ),
            path(
                '<path:object_id>/payload.json/',
                self.admin_site.admin_view(self.serve_payload),
                name='web_scenegraph_payload',
            ),
            path(
                'gallery.png/',
                self.admin_site.admin_view(self.serve_gallery),
                name='web_scenegraph_gallery',
            ),
        ]
        # Custom routes must come first so ``<path:object_id>`` doesn't
        # eat the literal ``gallery.png`` segment.
        return custom + urls

    # ── list-display columns ───────────────────────────────────────────

    def session_id_short(self, obj):
        sid = obj.session_id or ''
        short = sid.replace('scenegraph_', '')
        return format_html('<span style="font-family: monospace;">{}</span>', short)
    session_id_short.short_description = 'Session ID'
    session_id_short.admin_order_field = 'session_id'

    def kernels_used_short(self, obj):
        ks = obj.kernels_used or []
        if not ks:
            return format_html('<span style="color:#94a3b8;">—</span>')
        return format_html(
            '<span style="font-family: monospace; font-size: 11px;">{}</span>',
            ', '.join(ks),
        )
    kernels_used_short.short_description = 'Kernels'

    def n_nodes_display(self, obj):
        return len(obj.nodes or [])
    n_nodes_display.short_description = '# nodes'

    def n_edges_display(self, obj):
        return len(obj.edges or [])
    n_edges_display.short_description = '# edges'

    def edge_mode_display(self, obj):
        """Show how the edges were generated.

        ``adjacent`` = centroid-IoU (vanilla build_scene_graph default);
        ``road_adjacent`` = CityGraph road-aware adjacency stitched in
        by the Option-A merge. Most rows have only ``adjacent``; rows
        from the merged pipeline carry both, and we annotate the count
        of each in a tiny coloured chip. Cheap to compute (single linear
        pass over JSON edges) but cached per-row by Django's admin so
        no extra DB load.
        """
        edges = obj.edges or []
        if not edges:
            return format_html('<span style="color:#94a3b8;">—</span>')
        counts = Counter()
        for e in edges:
            counts[e.get('relation') or 'adjacent'] += 1
        chips = []
        palette = {
            'road_adjacent': '#0ea5e9',  # cyan = road-aware
            'adjacent':      '#94a3b8',  # slate = vanilla centroid-IoU
            'contains':      '#a855f7',  # purple = future PR-3
            'served_by':     '#22c55e',  # green = future PR-3
        }
        for rel, n in counts.most_common():
            color = palette.get(rel, '#64748b')
            chips.append(format_html(
                '<span style="display:inline-block; padding:1px 6px;'
                ' margin-right:3px; border-radius:3px;'
                ' background:{}; color:#fff; font-size:11px;'
                ' font-family:monospace;" title="{}">{}·{}</span>',
                color, rel, rel.split('_', 1)[0], n,
            ))
        return mark_safe(''.join(chips))
    edge_mode_display.short_description = 'Edge sources'

    def city_graph_summary(self, obj):
        """Render the Option-A CityGraph block as an inline summary.

        Pulls ``fusion_metadata.city_graph`` (set by
        :func:`scenegraph_city_graph.spectral_block`) and the
        per-orchestrator-run merge stats (``n_road_edges_added``,
        ``n_cg_annotated_nodes``, ``city_graph_options``,
        ``city_graph_warning``). Renders a small two-column table so
        the spectral diagnostics are scannable without expanding the
        raw JSON panel below. If the row was built without the merge,
        prints a one-line "not used" marker.
        """
        fmeta = obj.fusion_metadata or {}
        if not fmeta.get('use_city_graph_regions'):
            return format_html(
                '<span style="color:#64748b;">'
                'Built without the city-graph backbone '
                '(<code>use_city_graph_regions=False</code>).'
                '</span>'
            )

        warn = fmeta.get('city_graph_warning')
        if warn:
            return format_html(
                '<div style="background:#7f1d1d; color:#fee2e2;'
                ' padding:8px; border-radius:4px;">'
                '<strong>City-graph build failed.</strong> '
                'Falling back to vanilla SceneGraph for this row. '
                '<br><small><code>{}</code></small></div>',
                warn,
            )

        cg = fmeta.get('city_graph') or {}
        diag = cg.get('diagnostics') or {}
        opts = fmeta.get('city_graph_options') or {}

        rows = []
        rows.append(('graph_mode',         opts.get('graph_mode', '?')))
        rows.append(('network_type',       opts.get('network_type', '?')))
        rows.append(('CityGraph nodes',    cg.get('n_nodes', '?')))
        rows.append(('CityGraph edges',    cg.get('n_edges', '?')))
        rows.append(('road edges spliced', fmeta.get('n_road_edges_added', 0)))
        rows.append(('cg-annotated nodes', fmeta.get('n_cg_annotated_nodes', 0)))
        rows.append(('λ Fiedler',          _fmt_float(cg.get('lam_fiedler'))))
        rows.append(('Fiedler value',      _fmt_float(cg.get('fiedler_value'))))
        rows.append(('β₀ (zero modes)',    diag.get('n_zero_modes', '?')))
        rows.append(('β₁',                 diag.get('beta1', '?')))
        rows.append(('β₁ null',            diag.get('beta1_null', '?')))
        rows.append(('ΔH (H_obs - H_vac)', _fmt_float(diag.get('delta_H'))))
        rows.append(('Δ′ (mode gap)',      _fmt_float(diag.get('delta_prime'))))
        rows.append(('converged',          diag.get('converged', '?')))
        rows.append(('n iter',             diag.get('n_iter', '?')))

        # Inline row-by-row table — Django's generic admin CSS handles
        # the surrounding card; we just emit a minimal kv grid.
        cells = ''.join(
            format_html(
                '<tr><td style="padding:2px 12px 2px 0; color:#64748b;'
                ' font-family:monospace; white-space:nowrap;">{}</td>'
                '<td style="font-family:monospace;">{}</td></tr>',
                k, v,
            )
            for k, v in rows
        )
        return mark_safe(
            '<table style="border-collapse:collapse;">' + cells + '</table>'
        )
    city_graph_summary.short_description = 'CityGraph backbone'

    def top_categories_display(self, obj):
        """Inline coloured category histogram — top 4 by argmax count."""
        # Lazy import to keep admin module importable without matplotlib.
        from .world_sampler_api.scenegraph_viz import (
            CATEGORY_COLORS, category_histogram,
        )
        hist = category_histogram(obj.nodes or [])
        if not hist:
            return format_html('<span style="color:#94a3b8;">—</span>')
        chips = []
        for cat, n in hist.most_common(4):
            color = CATEGORY_COLORS.get(cat, CATEGORY_COLORS['unknown'])
            chips.append(format_html(
                '<span style="display:inline-block; padding:1px 6px;'
                ' margin-right:4px; border-radius:3px;'
                ' background:{}; color:#0f172a; font-size:11px;'
                ' font-family:monospace;">{}·{}</span>',
                color, cat, n,
            ))
        return mark_safe(''.join(chips))
    top_categories_display.short_description = 'Top categories'

    def view_links(self, obj):
        """Per-row action buttons: PNG, JSON, Cesium, re-render."""
        if not obj.pk:
            return ''
        png = reverse('admin:web_scenegraph_visualization', args=[obj.pk])
        rerender = reverse('admin:web_scenegraph_rerender', args=[obj.pk])
        payload = reverse('admin:web_scenegraph_payload', args=[obj.pk])

        # Optional Cesium deep-link: viewport.camera carries lat/lon/alt.
        cam = (obj.viewport or {}).get('camera') or {}
        lat = cam.get('latitude')
        lon = cam.get('longitude')
        alt = cam.get('altitude')
        cesium_link = ''
        if lat is not None and lon is not None:
            qs = urlencode({k: v for k, v in (
                ('lat', lat), ('lon', lon), ('zoom', alt or 1000),
            ) if v is not None})
            cesium_link = format_html(
                ' · <a href="/label/3d/search/#{}" target="_blank">🌍 Cesium</a>',
                qs,
            )

        core = format_html(
            '<a href="{}" target="_blank">🖼 PNG</a> · '
            '<a href="{}">↻ Re-render</a> · '
            '<a href="{}" target="_blank">JSON</a>',
            png, rerender, payload,
        )
        return mark_safe(str(core) + str(cesium_link))
    view_links.short_description = 'Actions'

    # ── detail-view embedded preview + pretty JSON ─────────────────────

    def visualization_preview(self, obj):
        """Inline PNG preview on the detail page.

        Renders lazily: the first call to the served URL builds the
        PNG; subsequent visits hit the disk cache. This keeps the
        admin detail page snappy and keeps matplotlib out of the
        request thread for already-rendered scenes.
        """
        if not obj.pk:
            return '(save first)'
        png = reverse('admin:web_scenegraph_visualization', args=[obj.pk])
        rerender = reverse('admin:web_scenegraph_rerender', args=[obj.pk])
        return format_html(
            '<div style="background:#f8fafc; padding:8px; border:1px solid #e2e8f0;">'
            '<a href="{}" target="_blank">'
            '<img src="{}" style="max-width:100%; height:auto; display:block;'
            ' border:1px solid #cbd5e1;" '
            'alt="SceneGraph visualization for {}"/>'
            '</a>'
            '<div style="margin-top:6px; font-size:11px; color:#475569;">'
            '<a href="{}">↻ Re-render</a> · '
            '<a href="{}" target="_blank">open full size →</a>'
            '</div></div>',
            png, png, obj.session_id, rerender, png,
        )
    visualization_preview.short_description = 'Visualization'

    def _pretty_json(self, value):
        try:
            text = json.dumps(value, indent=2, sort_keys=False, default=str)
        except (TypeError, ValueError):
            text = str(value)
        # Truncate huge blobs so the change-page stays responsive even
        # with a 50k-edge dump in fusion_metadata; full payload is one
        # click away via the JSON link.
        if len(text) > 20000:
            text = text[:20000] + '\n... [truncated, see "{ } JSON" link] ...'
        return format_html(
            '<pre style="max-height:480px; overflow:auto;'
            ' background:#0f172a; color:#e2e8f0; padding:10px;'
            ' border-radius:4px; font-size:11px;">{}</pre>',
            text,
        )

    def viewport_pretty(self, obj):
        return self._pretty_json(obj.viewport or {})
    viewport_pretty.short_description = 'Viewport (JSON)'

    def fusion_metadata_pretty(self, obj):
        return self._pretty_json(obj.fusion_metadata or {})
    fusion_metadata_pretty.short_description = 'Fusion metadata (JSON)'

    # ── custom URL handlers ────────────────────────────────────────────

    def _render_one(self, row, *, force: bool = False):
        from .world_sampler_api.scenegraph_viz import (
            default_per_scene_path, render_scene_graph_png,
        )
        target = default_per_scene_path(row.session_id)
        if force or not target.exists():
            return render_scene_graph_png(row, target)
        return target

    def serve_visualization(self, request, object_id):
        """GET <id>/visualization.png/ → PNG bytes (lazy-rendered, cached)."""
        row = get_object_or_404(SceneGraph, pk=object_id)
        try:
            target = self._render_one(row)
        except Exception as exc:
            return HttpResponse(
                f'failed to render: {exc}', status=500, content_type='text/plain',
            )
        if target is None or not Path(target).exists():
            raise Http404('No usable geometry for this SceneGraph row.')
        return FileResponse(open(target, 'rb'), content_type='image/png')

    def rerender_visualization(self, request, object_id):
        """GET <id>/rerender/ → re-render and bounce back to change page."""
        row = get_object_or_404(SceneGraph, pk=object_id)
        try:
            target = self._render_one(row, force=True)
        except Exception as exc:
            self.message_user(
                request, f'Re-render failed: {exc}', level=messages.ERROR,
            )
        else:
            if target is None:
                self.message_user(
                    request,
                    f'{row.session_id}: no usable geometry, nothing rendered.',
                    level=messages.WARNING,
                )
            else:
                self.message_user(
                    request, f'Re-rendered {row.session_id} → {target}',
                    level=messages.SUCCESS,
                )
        return HttpResponseRedirect(
            reverse('admin:web_scenegraph_change', args=[object_id])
        )

    def serve_payload(self, request, object_id):
        """GET <id>/payload.json/ → the canonical kernelcal SceneGraph dict."""
        row = get_object_or_404(SceneGraph, pk=object_id)
        return JsonResponse(
            {
                'session_id':      row.session_id,
                'created_at':      row.created_at.isoformat(),
                'taxonomy_name':   row.taxonomy_name,
                'kernels_used':    row.kernels_used,
                'viewport':        row.viewport,
                'nodes':           row.nodes,
                'edges':           row.edges,
                'fusion_metadata': row.fusion_metadata,
                'artifact_path':   row.artifact_path,
            },
            json_dumps_params={'allow_nan': False, 'indent': 2},
        )

    def serve_gallery(self, request):
        """GET gallery.png/ → multi-panel gallery rendered on the fly.

        Uses the latest 12 rows by default; pass ``?latest=N`` to override
        or ``?session_ids=a,b,c`` for a specific selection. Rendered
        on each request (no on-disk cache) since the input set is
        request-dependent.
        """
        from .world_sampler_api.scenegraph_viz import (
            DEFAULT_OUT_DIR, render_gallery_png,
        )
        try:
            latest = int(request.GET.get('latest', '12'))
        except ValueError:
            latest = 12
        ids = request.GET.get('session_ids', '').strip()
        qs = SceneGraph.objects.all().order_by('-created_at')
        if ids:
            qs = qs.filter(session_id__in=[s for s in ids.split(',') if s])
        else:
            qs = qs[:latest]
        rows = list(qs)
        if not rows:
            raise Http404('No SceneGraph rows to render.')

        target = DEFAULT_OUT_DIR / '_gallery_admin.png'
        try:
            render_gallery_png(rows, target)
        except Exception as exc:
            return HttpResponse(
                f'failed to render gallery: {exc}', status=500,
                content_type='text/plain',
            )
        return FileResponse(open(target, 'rb'), content_type='image/png')

    # ── admin actions ──────────────────────────────────────────────────

    def action_render_pngs(self, request, queryset):
        """Re-render PNGs for selected rows (forced, ignoring on-disk cache)."""
        ok = 0
        skipped = 0
        failed = 0
        for row in queryset:
            try:
                target = self._render_one(row, force=True)
            except Exception as exc:
                failed += 1
                self.message_user(
                    request,
                    f'{row.session_id}: {exc}',
                    level=messages.ERROR,
                )
                continue
            if target is None:
                skipped += 1
            else:
                ok += 1
        self.message_user(
            request,
            f'PNG re-render: {ok} ok, {skipped} skipped (no geometry), {failed} failed.',
            level=messages.SUCCESS if failed == 0 else messages.WARNING,
        )
    action_render_pngs.short_description = 'Re-render visualization PNGs (force)'

    def action_render_gallery(self, request, queryset):
        """Render a multi-panel gallery for the selected rows and link to it."""
        ids = ','.join(queryset.values_list('session_id', flat=True))
        if not ids:
            self.message_user(
                request, 'No rows selected.', level=messages.WARNING,
            )
            return
        url = reverse('admin:web_scenegraph_gallery') + '?' + urlencode(
            {'session_ids': ids}
        )
        return HttpResponseRedirect(url)
    action_render_gallery.short_description = 'Render gallery PNG for selected rows'

    def action_delete_png_artifacts(self, request, queryset):
        """Remove on-disk PNG (DB row preserved). Useful before a
        palette/renderer change that should invalidate cached
        thumbnails."""
        from .world_sampler_api.scenegraph_viz import default_per_scene_path
        removed = 0
        for row in queryset:
            target = default_per_scene_path(row.session_id)
            if target.exists():
                try:
                    target.unlink()
                    removed += 1
                except OSError as exc:
                    self.message_user(
                        request, f'{row.session_id}: {exc}',
                        level=messages.ERROR,
                    )
        self.message_user(
            request, f'Removed {removed} cached PNG artifact(s).',
            level=messages.SUCCESS,
        )
    action_delete_png_artifacts.short_description = (
        'Delete cached PNG artifacts (force re-render on next view)'
    )

    # ── safety: scene graphs are write-once orchestrator output ────────

    def has_add_permission(self, request):
        return False  # built only by the orchestrator endpoint

    def has_change_permission(self, request, obj=None):
        return True  # read-only via readonly_fields, but allow viewing

    def save_model(self, request, obj, form, change):
        # Defensive: fields are readonly so this shouldn't fire, but if
        # someone reorders readonly_fields this keeps it inert.
        return
