"""
Django Admin for World Sampler Models
"""

from django.contrib import admin
from django.utils.html import format_html
from django.db.models import Q
from .models import SampledLocation, SamplingSession, DistributionUpdate


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

