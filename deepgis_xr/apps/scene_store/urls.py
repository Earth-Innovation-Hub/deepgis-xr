from django.urls import path

from . import views

urlpatterns = [
    path('webclient/sampler/world/entities', views.entities_view, name='world_entities'),
    path('webclient/sampler/world/entities/<int:entity_id>', views.entity_detail_view, name='world_entity'),
    path('webclient/sampler/world/feedback', views.feedback_view, name='world_feedback'),
    path('webclient/sampler/world/preferences', views.preferences_view, name='world_preferences'),
    path('webclient/sampler/world/stats', views.stats_view, name='world_stats'),
    path('webclient/sampler/world/histogram', views.histogram_view, name='world_histogram'),
    path('webclient/sampler/world/captures', views.captures_view, name='world_captures'),
    path('webclient/sampler/world/captures/<str:session_id>', views.capture_detail_view, name='world_capture'),
]
