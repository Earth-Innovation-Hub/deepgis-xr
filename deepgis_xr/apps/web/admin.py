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
        'last_fit_display',
        'last_collapse_display',
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
        'last_fit_display',
        'distinction_game_fit_panel',
        'last_collapse_display',
        'scene_graph_collapse_panel',
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
        ('Distinction-Game fit (PR-3)', {
            'fields': ('distinction_game_fit_panel',),
            'description': (
                'Most recent <code>fit_distinction_game</code> artifact '
                'whose contributing-rows index includes this SceneGraph '
                '(i.e. the latest MaxCal Q_s + λ refit that learned '
                'from this row). Generate new fits with the '
                '<em>Run distinction-game fit on selected</em> action '
                'or <code>python manage.py fit_distinction_game</code>.'
            ),
        }),
        ('SceneGraph collapse (PR-4)', {
            'fields': ('scene_graph_collapse_panel',),
            'description': (
                'Most recent factor-graph collapse artifact whose '
                'contributing-rows index includes this SceneGraph. '
                'Generate new fused graphs with the '
                '<em>Collapse selected SceneGraphs</em> action or '
                '<code>python manage.py collapse_scene_graphs</code>.'
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
        'action_run_distinction_game_fit',
        'action_collapse_scene_graphs',
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
                '<path:object_id>/graph.html/',
                self.admin_site.admin_view(self.serve_graph_visualization),
                name='web_scenegraph_graph',
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
            # Distinction-game fit artifact serving (PR-3).
            path(
                'fit-artifact/<path:rel_path>/',
                self.admin_site.admin_view(self.serve_fit_artifact),
                name='web_scenegraph_fit_artifact',
            ),
            path(
                '<path:object_id>/last-fit/',
                self.admin_site.admin_view(self.serve_last_fit_for_row),
                name='web_scenegraph_last_fit',
            ),
            # Factor-graph collapse artifact serving (PR-4).
            path(
                'collapse-artifact/<path:rel_path>/',
                self.admin_site.admin_view(self.serve_collapse_artifact),
                name='web_scenegraph_collapse_artifact',
            ),
            path(
                '<path:object_id>/last-collapse/',
                self.admin_site.admin_view(self.serve_last_collapse_for_row),
                name='web_scenegraph_last_collapse',
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

    def last_fit_display(self, obj):
        """Compact column showing the latest distinction-game fit that
        included this row.

        Reads the on-disk fit artifact directory (no DB hit) and shows
        a green chip with the artifact's timestamp + λ-summary if a
        fit exists; a grey "—" otherwise. The chip is a link to the
        artifact's ``fit.summary.txt`` so the auditor can drill in.
        """
        if not obj.session_id:
            return format_html('<span style="color:#94a3b8;">—</span>')
        try:
            from .world_sampler_api.distinction_game_fit import (
                latest_fit_for_session,
            )
        except Exception:
            return format_html('<span style="color:#94a3b8;">—</span>')
        entry = latest_fit_for_session(obj.session_id)
        if not entry:
            return format_html(
                '<span style="color:#94a3b8;" title="No fit has consumed '
                'this row yet.">—</span>'
            )
        url = (
            reverse('admin:web_scenegraph_fit_artifact', args=[entry['name']])
            + 'fit.summary.txt'
        )
        # Show a tiny λ summary: top-2 sources by weight.
        sources = entry.get('sources') or []
        lambdas = entry.get('lambdas') or []
        pairs = sorted(
            zip(sources, lambdas),
            key=lambda kv: -float(kv[1] or 0.0),
        )[:2]
        chip_text = ', '.join(f'{s}={float(l):.2f}' for s, l in pairs)
        return format_html(
            '<a href="{}" target="_blank" '
            'style="display:inline-block; padding:1px 6px; border-radius:3px;'
            ' background:#16a34a; color:#fff; font-size:11px; '
            ' font-family:monospace; text-decoration:none;" '
            'title="{}">{}{}</a>',
            url,
            f'Fit {entry["name"]} — {len(entry.get("contributing_session_ids") or [])} rows',
            entry['name'][:13],
            f' · {chip_text}' if chip_text else '',
        )
    last_fit_display.short_description = 'Last fit'

    def last_collapse_display(self, obj):
        """Compact column showing the latest fused SceneGraph artifact."""
        if not obj.session_id:
            return format_html('<span style="color:#94a3b8;">—</span>')
        try:
            from .world_sampler_api.scene_graph_collapse import (
                latest_collapse_for_session,
            )
        except Exception:
            return format_html('<span style="color:#94a3b8;">—</span>')
        entry = latest_collapse_for_session(obj.session_id)
        if not entry:
            return format_html(
                '<span style="color:#94a3b8;" title="No collapse has consumed '
                'this row yet.">—</span>'
            )
        url = (
            reverse('admin:web_scenegraph_collapse_artifact', args=[entry['name']])
            + 'fused.summary.txt'
        )
        label = (
            f'{entry.get("n_input_nodes", 0)}→{entry.get("n_fused_nodes", 0)} '
            f'· {entry.get("bp_n_iter", "?")} it'
        )
        return format_html(
            '<a href="{}" target="_blank" '
            'style="display:inline-block; padding:1px 6px; border-radius:3px;'
            ' background:#2563eb; color:#fff; font-size:11px; '
            ' font-family:monospace; text-decoration:none;" '
            'title="{}">{}{}</a>',
            url,
            f'Collapse {entry["name"]} — {len(entry.get("contributing_session_ids") or [])} rows',
            entry['name'][:13],
            f' · {label}',
        )
    last_collapse_display.short_description = 'Last collapse'

    def view_links(self, obj):
        """Per-row action buttons: PNG, JSON, Cesium, re-render."""
        if not obj.pk:
            return ''
        png = reverse('admin:web_scenegraph_visualization', args=[obj.pk])
        graph = reverse('admin:web_scenegraph_graph', args=[obj.pk])
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
            '<a href="{}" target="_blank">Graph</a> · '
            '<a href="{}" target="_blank">🖼 PNG</a> · '
            '<a href="{}">↻ Re-render</a> · '
            '<a href="{}" target="_blank">JSON</a>',
            graph, png, rerender, payload,
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
        graph = reverse('admin:web_scenegraph_graph', args=[obj.pk])
        rerender = reverse('admin:web_scenegraph_rerender', args=[obj.pk])
        return format_html(
            '<div style="background:#f8fafc; padding:8px; border:1px solid #e2e8f0;">'
            '<iframe src="{}" '
            'style="width:100%; height:680px; border:1px solid #cbd5e1;'
            ' border-radius:6px; background:#0f172a;" '
            'title="Interactive SceneGraph visualization for {}"></iframe>'
            '<div style="margin-top:6px; font-size:11px; color:#475569;">'
            '<a href="{}" target="_blank">open graph explorer →</a> · '
            '<a href="{}" target="_blank">open PNG fallback →</a> · '
            '<a href="{}">↻ Re-render PNG</a>'
            '</div>'
            '<details style="margin-top:8px;">'
            '<summary style="cursor:pointer; color:#475569; font-size:11px;">PNG fallback</summary>'
            '<a href="{}" target="_blank">'
            '<img src="{}" style="max-width:100%; height:auto; display:block;'
            ' margin-top:8px;'
            ' border:1px solid #cbd5e1;" '
            'alt="SceneGraph visualization for {}"/>'
            '</a>'
            '</details>'
            '</div>',
            graph, obj.session_id, graph, png, rerender,
            png, png, obj.session_id,
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

    def distinction_game_fit_panel(self, obj):
        """Render the latest fit summary that included this row (full panel).

        Surfaces λ per source + EM convergence + links to the on-disk
        ``fit.json`` / ``fit.summary.txt`` artifact. Falls back to a
        polite "no fit yet" marker when the row has not been included
        in any fit run.
        """
        if not obj or not obj.session_id:
            return format_html('<em>(save first)</em>')
        try:
            from .world_sampler_api.distinction_game_fit import (
                latest_fit_for_session,
            )
        except Exception as exc:
            return format_html(
                '<span style="color:#dc2626;">Failed to load fit module: {}</span>',
                str(exc),
            )
        entry = latest_fit_for_session(obj.session_id)
        if not entry:
            return format_html(
                '<div style="color:#64748b;">'
                'No <code>fit_distinction_game</code> run has consumed this '
                'row yet. Use the admin action <em>Run distinction-game fit '
                'on selected</em> or run '
                '<code>python manage.py fit_distinction_game --session-ids {}</code>.'
                '</div>',
                obj.session_id,
            )

        sources = entry.get('sources') or []
        lambdas = entry.get('lambdas') or []
        n_sg = entry.get('n_scene_graphs') or 0
        n_regs = entry.get('n_regions') or 0
        n_anchored = entry.get('n_anchored_regions') or 0
        converged = entry.get('converged')

        rows_html = ''
        for s, l in zip(sources, lambdas):
            try:
                lam_str = f'{float(l):.4f}'
            except Exception:
                lam_str = str(l)
            rows_html += format_html(
                '<tr><td style="padding:2px 12px 2px 0; color:#64748b;'
                ' font-family:monospace;">{}</td>'
                '<td style="font-family:monospace;">{}</td></tr>',
                s, lam_str,
            )

        json_url = (
            reverse('admin:web_scenegraph_fit_artifact', args=[entry['name']])
            + 'fit.json'
        )
        txt_url = (
            reverse('admin:web_scenegraph_fit_artifact', args=[entry['name']])
            + 'fit.summary.txt'
        )

        return mark_safe(
            f'<div>'
            f'<div style="margin-bottom:6px;">'
            f'<strong>Fit {entry["name"]}</strong> · '
            f'{n_sg} scene graphs, {n_regs} regions '
            f'({n_anchored} anchored) · '
            f'<span style="color:{"#16a34a" if converged else "#f97316"};">'
            f'{"converged" if converged else "did not fully converge"}</span>'
            f'</div>'
            f'<table style="border-collapse:collapse; margin-bottom:6px;">'
            f'{rows_html}'
            f'</table>'
            f'<div style="font-size:11px;">'
            f'<a href="{txt_url}" target="_blank">📄 fit.summary.txt</a> · '
            f'<a href="{json_url}" target="_blank">{{ }} fit.json</a>'
            f'</div>'
            f'</div>'
        )
    distinction_game_fit_panel.short_description = 'Latest distinction-game fit'

    def scene_graph_collapse_panel(self, obj):
        """Render the latest factor-graph collapse summary for this row."""
        if not obj or not obj.session_id:
            return format_html('<em>(save first)</em>')
        try:
            from .world_sampler_api.scene_graph_collapse import (
                latest_collapse_for_session,
            )
        except Exception as exc:
            return format_html(
                '<span style="color:#dc2626;">Failed to load collapse module: {}</span>',
                str(exc),
            )
        entry = latest_collapse_for_session(obj.session_id)
        if not entry:
            return format_html(
                '<div style="color:#64748b;">'
                'No <code>collapse_scene_graphs</code> run has consumed this '
                'row yet. Use the admin action <em>Collapse selected '
                'SceneGraphs</em> or run '
                '<code>python manage.py collapse_scene_graphs --session-ids {}</code>.'
                '</div>',
                obj.session_id,
            )
        json_url = (
            reverse('admin:web_scenegraph_collapse_artifact', args=[entry['name']])
            + 'fused.json'
        )
        txt_url = (
            reverse('admin:web_scenegraph_collapse_artifact', args=[entry['name']])
            + 'fused.summary.txt'
        )
        diag_url = (
            reverse('admin:web_scenegraph_collapse_artifact', args=[entry['name']])
            + 'bp_diagnostics.json'
        )
        converged = entry.get('converged')
        return mark_safe(
            f'<div>'
            f'<div style="margin-bottom:6px;">'
            f'<strong>Collapse {entry["name"]}</strong> · '
            f'{entry.get("n_scene_graphs") or 0} scene graphs, '
            f'{entry.get("n_input_nodes") or 0} input nodes → '
            f'{entry.get("n_fused_nodes") or 0} fused nodes, '
            f'{entry.get("n_edges") or 0} edges · '
            f'<span style="color:{"#16a34a" if converged else "#f97316"};">'
            f'{"BP converged" if converged else "BP did not fully converge"}</span>'
            f'</div>'
            f'<div style="font-size:11px; margin-bottom:4px;">'
            f'BP iterations: {entry.get("bp_n_iter")}; '
            f'max delta: {entry.get("bp_max_delta")}'
            f'</div>'
            f'<div style="font-size:11px;">'
            f'<a href="{txt_url}" target="_blank">fused.summary.txt</a> · '
            f'<a href="{json_url}" target="_blank">{{ }} fused.json</a> · '
            f'<a href="{diag_url}" target="_blank">{{ }} bp_diagnostics.json</a>'
            f'</div>'
            f'</div>'
        )
    scene_graph_collapse_panel.short_description = 'Latest factor-graph collapse'

    # ── custom URL handlers ────────────────────────────────────────────

    def _render_one(self, row, *, force: bool = False):
        from .world_sampler_api.scenegraph_viz import (
            default_per_scene_path, render_scene_graph_png,
        )
        target = default_per_scene_path(row.session_id)
        if force or not target.exists():
            return render_scene_graph_png(row, target)
        return target

    def _node_graph_xy(self, node, fallback_i: int, fallback_n: int):
        """Return a stable 2D point from geo/image polygons for graph seeding."""
        region = (node or {}).get('region') or {}
        ring = region.get('geo_polygon') or region.get('polygon') or []
        pts = []
        for p in ring:
            try:
                if p is not None and len(p) >= 2:
                    pts.append((float(p[0]), float(p[1])))
            except (TypeError, ValueError):
                continue
        if pts:
            return (
                sum(p[0] for p in pts) / len(pts),
                sum(p[1] for p in pts) / len(pts),
            )

        # Deterministic circle fallback for semantic-only nodes.
        import math
        theta = 2.0 * math.pi * (fallback_i / max(fallback_n, 1))
        return (math.cos(theta), math.sin(theta))

    def _graph_preview_payload(self, row, *, max_nodes: int = 360, max_edges: int = 1200):
        """Compact node-link payload for the interactive admin graph view."""
        from .world_sampler_api.scenegraph_viz import CATEGORY_COLORS

        raw_nodes = list(row.nodes or [])
        raw_edges = list(row.edges or [])
        ranked = sorted(
            enumerate(raw_nodes),
            key=lambda item: float((item[1] or {}).get('score') or 0.0),
            reverse=True,
        )
        kept_pairs = ranked[:max_nodes]
        kept_ids = {
            str((node or {}).get('id') or f'n{idx}')
            for idx, node in kept_pairs
        }

        coords = {}
        for out_i, (idx, node) in enumerate(kept_pairs):
            node_id = str((node or {}).get('id') or f'n{idx}')
            coords[node_id] = self._node_graph_xy(node, out_i, len(kept_pairs))

        xs = [p[0] for p in coords.values()] or [0.0]
        ys = [p[1] for p in coords.values()] or [0.0]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        span_x = max(max_x - min_x, 1e-9)
        span_y = max(max_y - min_y, 1e-9)

        nodes = []
        for idx, node in kept_pairs:
            node = node or {}
            node_id = str(node.get('id') or f'n{idx}')
            x, y = coords[node_id]
            category = node.get('category') or 'unknown'
            sources = node.get('sources') or []
            claims = node.get('claims') or []
            nodes.append({
                'id': node_id,
                'label': node_id,
                'category': category,
                'score': float(node.get('score') or 0.0),
                'sources': sources,
                'n_claims': len(claims),
                'color': CATEGORY_COLORS.get(category, CATEGORY_COLORS['unknown']),
                'x': 60.0 + 880.0 * ((x - min_x) / span_x),
                'y': 60.0 + 520.0 * (1.0 - ((y - min_y) / span_y)),
            })

        links = []
        for edge in sorted(
            raw_edges,
            key=lambda e: float((e or {}).get('weight') or 0.0),
            reverse=True,
        ):
            if len(links) >= max_edges:
                break
            src = str((edge or {}).get('source') or '')
            tgt = str((edge or {}).get('target') or '')
            if src in kept_ids and tgt in kept_ids and src != tgt:
                links.append({
                    'source': src,
                    'target': tgt,
                    'relation': (edge or {}).get('relation') or 'adjacent',
                    'weight': float((edge or {}).get('weight') or 1.0),
                })

        return {
            'session_id': row.session_id,
            'taxonomy_name': row.taxonomy_name,
            'nodes': nodes,
            'links': links,
            'palette': CATEGORY_COLORS,
            'stats': {
                'total_nodes': len(raw_nodes),
                'total_edges': len(raw_edges),
                'shown_nodes': len(nodes),
                'shown_edges': len(links),
                'max_nodes': max_nodes,
                'max_edges': max_edges,
            },
        }

    def serve_graph_visualization(self, request, object_id):
        """GET <id>/graph.html/ → self-contained interactive node-link view."""
        row = get_object_or_404(SceneGraph, pk=object_id)
        payload = self._graph_preview_payload(row)
        data_json = json.dumps(payload, allow_nan=False).replace('</', '<\\/')
        html = """
<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SceneGraph Explorer</title>
<style>
  :root { color-scheme: dark; }
  body { margin:0; background:#0f172a; color:#e2e8f0; font:12px system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }
  .bar { display:flex; gap:12px; align-items:center; padding:10px 12px; background:#111827; border-bottom:1px solid #334155; }
  .title { font-weight:700; color:#f8fafc; }
  .pill { padding:2px 8px; border-radius:999px; background:#1e293b; color:#cbd5e1; }
  .wrap { display:grid; grid-template-columns:minmax(0,1fr) 270px; height:calc(100vh - 43px); min-height:560px; }
  svg { width:100%; height:100%; background:radial-gradient(circle at 50% 40%, #172554 0%, #0f172a 48%, #020617 100%); cursor:grab; }
  svg.dragging { cursor:grabbing; }
  .side { border-left:1px solid #334155; background:#0b1120; padding:12px; overflow:auto; }
  .side h3 { margin:0 0 8px; font-size:13px; color:#f8fafc; }
  .muted { color:#94a3b8; }
  .legend { display:grid; gap:5px; margin-top:12px; }
  .legend-row { display:flex; align-items:center; gap:6px; }
  .swatch { width:10px; height:10px; border-radius:50%; display:inline-block; }
  input { width:100%; box-sizing:border-box; margin:8px 0 10px; padding:7px 8px; border:1px solid #475569; border-radius:6px; background:#020617; color:#e2e8f0; }
  button { margin-right:6px; padding:5px 8px; border:1px solid #475569; border-radius:6px; background:#1e293b; color:#e2e8f0; cursor:pointer; }
  button:hover { background:#334155; }
  line { stroke:#94a3b8; stroke-opacity:.18; }
  circle { stroke:#f8fafc; stroke-opacity:.7; stroke-width:1; cursor:pointer; }
  circle.dim, line.dim { opacity:.06; }
  circle.selected { stroke:#fbbf24; stroke-width:3; }
  text { fill:#cbd5e1; pointer-events:none; font-size:10px; paint-order:stroke; stroke:#020617; stroke-width:3px; }
</style>
</head>
<body>
<div class="bar">
  <span class="title" id="title"></span>
  <span class="pill" id="counts"></span>
  <span class="muted">Drag nodes, wheel to zoom, click for details.</span>
</div>
<div class="wrap">
  <svg id="graph" viewBox="0 0 1000 640" role="img" aria-label="SceneGraph node-link visualization"></svg>
  <aside class="side">
    <h3>Inspect</h3>
    <input id="search" placeholder="Filter by id/category/source">
    <div>
      <button id="fit">Fit</button>
      <button id="labels">Labels</button>
      <button id="edges">Edges</button>
    </div>
    <p id="details" class="muted">Click a node to inspect it.</p>
    <h3>Legend</h3>
    <div class="legend" id="legend"></div>
  </aside>
</div>
<script>
const DATA = __GRAPH_DATA__;
const svg = document.getElementById('graph');
const ns = 'http://www.w3.org/2000/svg';
const byId = new Map(DATA.nodes.map(n => [n.id, n]));
let showLabels = DATA.nodes.length <= 180;
let showEdges = true;
let selected = null;
let view = {x:0, y:0, w:1000, h:640};

document.getElementById('title').textContent = `SceneGraph: ${DATA.session_id}`;
document.getElementById('counts').textContent =
  `${DATA.stats.shown_nodes}/${DATA.stats.total_nodes} nodes · ${DATA.stats.shown_edges}/${DATA.stats.total_edges} edges`;

for (const [cat, color] of Object.entries(DATA.palette)) {
  const row = document.createElement('div');
  row.className = 'legend-row';
  row.innerHTML = `<span class="swatch" style="background:${color}"></span><span>${cat}</span>`;
  document.getElementById('legend').appendChild(row);
}

const linkG = document.createElementNS(ns, 'g');
const nodeG = document.createElementNS(ns, 'g');
const labelG = document.createElementNS(ns, 'g');
svg.append(linkG, nodeG, labelG);

for (const l of DATA.links) {
  const a = byId.get(l.source), b = byId.get(l.target);
  if (!a || !b) continue;
  const el = document.createElementNS(ns, 'line');
  el.dataset.source = l.source;
  el.dataset.target = l.target;
  el.dataset.weight = l.weight;
  l.el = el;
  linkG.appendChild(el);
}

for (const n of DATA.nodes) {
  n.vx = 0; n.vy = 0;
  const c = document.createElementNS(ns, 'circle');
  c.setAttribute('r', 4 + Math.min(8, Math.max(0, n.score * 8)));
  c.setAttribute('fill', n.color);
  c.dataset.id = n.id;
  c.addEventListener('pointerdown', ev => startNodeDrag(ev, n));
  c.addEventListener('click', ev => { ev.stopPropagation(); selectNode(n); });
  n.el = c;
  nodeG.appendChild(c);

  const t = document.createElementNS(ns, 'text');
  t.textContent = n.category;
  n.labelEl = t;
  labelG.appendChild(t);
}

function tick() {
  const nodes = DATA.nodes, links = DATA.links;
  for (const n of nodes) {
    n.vx += (500 - n.x) * 0.0008;
    n.vy += (320 - n.y) * 0.0008;
  }
  for (let i = 0; i < nodes.length; i++) {
    for (let j = i + 1; j < nodes.length; j++) {
      const a = nodes[i], b = nodes[j];
      let dx = b.x - a.x, dy = b.y - a.y;
      let d2 = dx * dx + dy * dy + 0.01;
      if (d2 > 36000) continue;
      const f = Math.min(1.8, 48 / d2);
      a.vx -= dx * f; a.vy -= dy * f;
      b.vx += dx * f; b.vy += dy * f;
    }
  }
  for (const l of links) {
    const a = byId.get(l.source), b = byId.get(l.target);
    if (!a || !b) continue;
    let dx = b.x - a.x, dy = b.y - a.y;
    const d = Math.max(1, Math.hypot(dx, dy));
    const target = 46 + 18 / Math.max(0.2, Math.min(4, l.weight || 1));
    const f = (d - target) * 0.004;
    dx /= d; dy /= d;
    a.vx += dx * f; a.vy += dy * f;
    b.vx -= dx * f; b.vy -= dy * f;
  }
  for (const n of nodes) {
    if (n.fixed) continue;
    n.vx *= 0.86; n.vy *= 0.86;
    n.x = Math.max(12, Math.min(988, n.x + n.vx));
    n.y = Math.max(12, Math.min(628, n.y + n.vy));
  }
  draw();
}

function draw() {
  for (const l of DATA.links) {
    const a = byId.get(l.source), b = byId.get(l.target);
    if (!a || !b || !l.el) continue;
    l.el.setAttribute('x1', a.x); l.el.setAttribute('y1', a.y);
    l.el.setAttribute('x2', b.x); l.el.setAttribute('y2', b.y);
  }
  linkG.style.display = showEdges ? '' : 'none';
  labelG.style.display = showLabels ? '' : 'none';
  for (const n of DATA.nodes) {
    n.el.setAttribute('cx', n.x); n.el.setAttribute('cy', n.y);
    n.labelEl.setAttribute('x', n.x + 8); n.labelEl.setAttribute('y', n.y + 4);
  }
}

let ticks = 0;
function animate() {
  if (ticks++ < 160) {
    tick();
    requestAnimationFrame(animate);
  } else {
    draw();
  }
}
animate();

function selectNode(n) {
  selected = n;
  for (const x of DATA.nodes) x.el.classList.toggle('selected', x === n);
  const linked = new Set([n.id]);
  for (const l of DATA.links) {
    if (l.source === n.id) linked.add(l.target);
    if (l.target === n.id) linked.add(l.source);
  }
  for (const x of DATA.nodes) x.el.classList.toggle('dim', !linked.has(x.id));
  for (const l of DATA.links) l.el?.classList.toggle('dim', l.source !== n.id && l.target !== n.id);
  document.getElementById('details').innerHTML =
    `<strong>${n.id}</strong><br>category: <code>${n.category}</code><br>` +
    `score: ${n.score.toFixed(3)}<br>sources: ${(n.sources || []).join(', ') || '—'}<br>` +
    `claims: ${n.n_claims || 0}<br>neighbors: ${linked.size - 1}`;
}

svg.addEventListener('click', () => {
  selected = null;
  for (const x of DATA.nodes) x.el.classList.remove('selected', 'dim');
  for (const l of DATA.links) l.el?.classList.remove('dim');
  document.getElementById('details').textContent = 'Click a node to inspect it.';
});

function startNodeDrag(ev, n) {
  ev.stopPropagation();
  n.fixed = true;
  n.el.setPointerCapture(ev.pointerId);
  const move = e => {
    const p = svgPoint(e);
    n.x = p.x; n.y = p.y; n.vx = 0; n.vy = 0; draw();
  };
  const up = () => {
    n.fixed = false;
    n.el.removeEventListener('pointermove', move);
    n.el.removeEventListener('pointerup', up);
  };
  n.el.addEventListener('pointermove', move);
  n.el.addEventListener('pointerup', up);
}

function svgPoint(ev) {
  const p = svg.createSVGPoint();
  p.x = ev.clientX; p.y = ev.clientY;
  return p.matrixTransform(svg.getScreenCTM().inverse());
}

svg.addEventListener('wheel', ev => {
  ev.preventDefault();
  const k = ev.deltaY > 0 ? 1.12 : 0.88;
  const p = svgPoint(ev);
  view.x = p.x - (p.x - view.x) * k;
  view.y = p.y - (p.y - view.y) * k;
  view.w *= k; view.h *= k;
  svg.setAttribute('viewBox', `${view.x} ${view.y} ${view.w} ${view.h}`);
}, {passive:false});

let pan = null;
svg.addEventListener('pointerdown', ev => {
  if (ev.target !== svg) return;
  pan = {x:ev.clientX, y:ev.clientY, vx:view.x, vy:view.y};
  svg.classList.add('dragging');
});
svg.addEventListener('pointermove', ev => {
  if (!pan) return;
  const sx = view.w / svg.clientWidth, sy = view.h / svg.clientHeight;
  view.x = pan.vx - (ev.clientX - pan.x) * sx;
  view.y = pan.vy - (ev.clientY - pan.y) * sy;
  svg.setAttribute('viewBox', `${view.x} ${view.y} ${view.w} ${view.h}`);
});
svg.addEventListener('pointerup', () => { pan = null; svg.classList.remove('dragging'); });

document.getElementById('fit').onclick = () => {
  view = {x:0, y:0, w:1000, h:640};
  svg.setAttribute('viewBox', '0 0 1000 640');
};
document.getElementById('labels').onclick = () => { showLabels = !showLabels; draw(); };
document.getElementById('edges').onclick = () => { showEdges = !showEdges; draw(); };
document.getElementById('search').addEventListener('input', ev => {
  const q = ev.target.value.toLowerCase().trim();
  for (const n of DATA.nodes) {
    const hay = `${n.id} ${n.category} ${(n.sources || []).join(' ')}`.toLowerCase();
    n.el.classList.toggle('dim', q && !hay.includes(q));
    n.labelEl.classList.toggle('dim', q && !hay.includes(q));
  }
});
</script>
</body>
</html>
"""
        return HttpResponse(
            html.replace('__GRAPH_DATA__', data_json),
            content_type='text/html; charset=utf-8',
        )

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

    def serve_fit_artifact(self, request, rel_path):
        """GET fit-artifact/<dir>/<filename> → file from the on-disk fit
        artifact tree.

        Restricts service to the configured fit-artifact root so a
        ``..`` traversal cannot escape it. Recognises ``fit.json``
        (served as JSON), ``fit.summary.txt`` (text/plain), and
        ``contributing_rows.json`` (JSON); other names get a generic
        download response with text/plain.
        """
        from .world_sampler_api.distinction_game_fit import (
            DISTINCTION_GAME_FIT_DIR,
        )
        target = (DISTINCTION_GAME_FIT_DIR / rel_path).resolve()
        try:
            target.relative_to(DISTINCTION_GAME_FIT_DIR.resolve())
        except ValueError:
            raise Http404('Path outside the fit-artifact root.')
        if not target.exists() or not target.is_file():
            raise Http404(f'Artifact file not found: {rel_path}')
        if target.name == 'fit.json' or target.name == 'contributing_rows.json':
            return FileResponse(open(target, 'rb'), content_type='application/json')
        if target.suffix == '.txt' or target.name == 'fit.summary.txt':
            return FileResponse(open(target, 'rb'), content_type='text/plain; charset=utf-8')
        return FileResponse(open(target, 'rb'), content_type='text/plain; charset=utf-8')

    def serve_last_fit_for_row(self, request, object_id):
        """Bounce to the latest fit artifact directory listing for this row.

        Convenience link for clicking from a row's change page directly
        into the on-disk artifact (without requiring the user to know
        which timestamped folder to look in).
        """
        from .world_sampler_api.distinction_game_fit import (
            latest_fit_for_session,
        )
        row = get_object_or_404(SceneGraph, pk=object_id)
        entry = latest_fit_for_session(row.session_id)
        if not entry:
            self.message_user(
                request,
                f'No fit has consumed {row.session_id} yet.',
                level=messages.WARNING,
            )
            return HttpResponseRedirect(
                reverse('admin:web_scenegraph_change', args=[object_id])
            )
        return HttpResponseRedirect(
            reverse('admin:web_scenegraph_fit_artifact', args=[entry['name']])
            + 'fit.summary.txt'
        )

    def serve_collapse_artifact(self, request, rel_path):
        """GET collapse-artifact/<dir>/<filename> from fused artifact root."""
        from .world_sampler_api.scene_graph_collapse import (
            FUSED_SCENE_GRAPH_DIR,
        )
        target = (FUSED_SCENE_GRAPH_DIR / rel_path).resolve()
        try:
            target.relative_to(FUSED_SCENE_GRAPH_DIR.resolve())
        except ValueError:
            raise Http404('Path outside the collapse-artifact root.')
        if not target.exists() or not target.is_file():
            raise Http404(f'Artifact file not found: {rel_path}')
        if target.suffix == '.json':
            return FileResponse(open(target, 'rb'), content_type='application/json')
        if target.suffix == '.txt':
            return FileResponse(open(target, 'rb'), content_type='text/plain; charset=utf-8')
        return FileResponse(open(target, 'rb'), content_type='text/plain; charset=utf-8')

    def serve_last_collapse_for_row(self, request, object_id):
        """Bounce to the latest collapse summary for this row."""
        from .world_sampler_api.scene_graph_collapse import (
            latest_collapse_for_session,
        )
        row = get_object_or_404(SceneGraph, pk=object_id)
        entry = latest_collapse_for_session(row.session_id)
        if not entry:
            self.message_user(
                request,
                f'No collapse has consumed {row.session_id} yet.',
                level=messages.WARNING,
            )
            return HttpResponseRedirect(
                reverse('admin:web_scenegraph_change', args=[object_id])
            )
        return HttpResponseRedirect(
            reverse('admin:web_scenegraph_collapse_artifact', args=[entry['name']])
            + 'fused.summary.txt'
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

    def action_run_distinction_game_fit(self, request, queryset):
        """Run :func:`fit_distinction_game` on the selected SceneGraph rows.

        Behaves identically to the
        ``python manage.py fit_distinction_game --session-ids ...``
        command: assembles the rows into a kernelcal payload, runs the
        EM fit, writes a versioned artifact under
        ``/app/deepgis_results/distinction_game_fits/<timestamp>/``,
        and links the auditor straight to ``fit.summary.txt`` via the
        admin success message.
        """
        rows = list(queryset)
        if not rows:
            self.message_user(
                request, 'No rows selected.', level=messages.WARNING,
            )
            return
        try:
            from .world_sampler_api.distinction_game_fit import (
                run_fit_for_rows,
            )
        except Exception as exc:
            self.message_user(
                request,
                f'Failed to import distinction-game fit module: {exc}',
                level=messages.ERROR,
            )
            return
        try:
            artifact = run_fit_for_rows(
                rows,
                label=f'admin_{request.user.username or "anon"}',
            )
        except Exception as exc:
            self.message_user(
                request,
                f'Fit failed: {exc}',
                level=messages.ERROR,
            )
            return

        url = (
            reverse(
                'admin:web_scenegraph_fit_artifact',
                args=[artifact.artifact_dir.name],
            )
            + 'fit.summary.txt'
        )
        lam_summary = ', '.join(
            f'{s}={l:.3f}' for s, l in artifact.lambdas.items()
        ) or '(no lambdas)'
        self.message_user(
            request,
            mark_safe(
                f'Distinction-game fit complete: {artifact.n_regions} regions '
                f'({artifact.n_anchored_regions} anchored) over {len(rows)} rows '
                f'· λ → {lam_summary} · '
                f'<a href="{url}" target="_blank">view summary →</a>'
            ),
            level=messages.SUCCESS if artifact.converged else messages.WARNING,
        )
    action_run_distinction_game_fit.short_description = (
        'Run distinction-game Q_s + λ fit on selected rows (PR-3)'
    )

    def action_collapse_scene_graphs(self, request, queryset):
        """Run the PR-4 factor-graph collapse on selected SceneGraph rows."""
        rows = list(queryset)
        if not rows:
            self.message_user(
                request, 'No rows selected.', level=messages.WARNING,
            )
            return
        try:
            from .world_sampler_api.scene_graph_collapse import (
                run_collapse_for_rows,
            )
        except Exception as exc:
            self.message_user(
                request,
                f'Failed to import SceneGraph collapse module: {exc}',
                level=messages.ERROR,
            )
            return
        try:
            artifact = run_collapse_for_rows(
                rows,
                label=f'admin_{request.user.username or "anon"}',
            )
        except Exception as exc:
            self.message_user(
                request,
                f'Collapse failed: {exc}',
                level=messages.ERROR,
            )
            return
        url = (
            reverse(
                'admin:web_scenegraph_collapse_artifact',
                args=[artifact.artifact_dir.name],
            )
            + 'fused.summary.txt'
        )
        self.message_user(
            request,
            mark_safe(
                f'SceneGraph collapse complete: {artifact.n_input_nodes} input '
                f'nodes → {artifact.n_fused_nodes} fused nodes over {len(rows)} '
                f'rows · <a href="{url}" target="_blank">view summary →</a>'
            ),
            level=messages.SUCCESS if artifact.converged else messages.WARNING,
        )
    action_collapse_scene_graphs.short_description = (
        'Collapse selected SceneGraphs into one fused graph (PR-4)'
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
