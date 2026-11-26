from django.urls import path

from . import mcp, views

urlpatterns = [
    path('webclient/sampler/world/entities', views.entities_view, name='world_entities'),
    path('webclient/sampler/world/entities/<int:entity_id>', views.entity_detail_view, name='world_entity'),
    path('webclient/sampler/world/feedback', views.feedback_view, name='world_feedback'),
    path('webclient/sampler/world/preferences', views.preferences_view, name='world_preferences'),
    path('webclient/sampler/world/stats', views.stats_view, name='world_stats'),
    path('webclient/sampler/world/histogram', views.histogram_view, name='world_histogram'),
    path('webclient/sampler/world/trait_map', views.trait_map_view, name='world_trait_map'),
    path('webclient/sampler/world/captures', views.captures_view, name='world_captures'),
    path('webclient/sampler/world/captures/<str:session_id>', views.capture_detail_view, name='world_capture'),
    path('webclient/sampler/world/summary', views.summary_view, name='world_summary'),
    path('webclient/sampler/world/changes', views.changes_view, name='world_changes'),
    path('webclient/sampler/world/review', views.review_view, name='world_review'),
    path('webclient/sampler/world/retire', views.retire_view, name='world_retire'),
    path('webclient/sampler/world/restore', views.restore_view, name='world_restore'),
    path('api/v1/mcp', mcp.mcp_view, name='scene_mcp'),
]
