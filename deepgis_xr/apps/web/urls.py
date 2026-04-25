from django.urls import path
from . import views
from deepgis_xr.apps.web.views import label_3d_sigma
from deepgis_xr.apps.web import world_sampler_api

urlpatterns = [
    # Main pages
    path('', views.index, name='index'),
    path('label/', views.label, name='label'),
    path('label/3d/', views.label_3d, name='label_3d'),
    path('label/3d/dev/', views.label_3d_dev, name='label_3d_dev'),
    path('label/3d/sigma/', label_3d_sigma, name='label_3d_sigma'),
    path('label/3d/topology/', views.label_topology_sigma, name='label_topology'),  # Now uses SIGMA (refactored)
    path('label/3d/topology/legacy/', views.label_topology, name='label_topology_legacy'),  # Original version
    path('label/3d/topology/sigma/', views.label_topology_sigma, name='label_topology_sigma'),  # Explicit SIGMA URL
    path('label/3d/search/', views.label_search, name='label_search'),  # DeepGIS Search viewer
    path('label/3d/moon/', views.label_moon_viewer, name='label_moon_viewer'),  # Moon viewer
    path('stl-viewer/', views.stl_viewer, name='stl_viewer'),
    path('view-label/', views.view_label, name='view_label'),
    path('results/', views.results, name='results'),

    # Webclient API endpoints
    path('webclient/getCategoryInfo', views.get_category_info, name='get_category_info'),
    path('webclient/getNewImage', views.get_new_image, name='get_new_image'),
    path('webclient/getAllImages', views.get_all_images, name='get_all_images'),
    path('webclient/saveLabel', views.save_label, name='save_label'),
    path('webclient/createCategory', views.create_category, name='create_category'),
    path('webclient/getRasterInfo', views.get_raster_info, name='get_raster_info'),
    path('webclient/getTileserverLayers', views.get_tileserver_layers, name='get_tileserver_layers'),

    # Used by /label/ legacy image labeller; shapefile export is admin-only.
    path('webclient/save-labels', views.save_labels, name='save_labels'),
    path('webclient/export-shapefile', views.export_shapefile, name='export_shapefile'),

    # Grid detection endpoint
    path('webclient/detect-grid', views.detect_grid, name='detect_grid'),
    
    # 3D model endpoints
    path('webclient/get-3d-model', views.get_3d_model, name='get_3d_model'),
    path('webclient/list-stl-models', views.list_stl_models, name='list_stl_models'),
    
    # API endpoints
    path('api/elevation-proxy', views.elevation_proxy, name='elevation_proxy'),
    path('api/opentopography/lidar-search', views.opentopography_lidar_search, name='opentopography_lidar_search'),
    
    # Rock Mask R-CNN labeling pipeline (replaces /map-label/ + /label/semi-supervised/).
    # Two surfaces feed the same 400x400 .npy training corpus:
    #   A. Edit-in-2D from an AI analysis report -> /label/rocks/edit/<session_id>/
    #   B. Cesium "Label Rocks" button -> POST capture -> redirect into the same editor
    path('label/rocks/edit/<str:session_id>/', views.rock_label_edit, name='rock_label_edit'),
    path('label/rocks/edit/<str:session_id>/save-tile/', views.rock_label_save_tile, name='rock_label_save_tile'),
    path('label/rocks/capture/', views.rock_label_capture, name='rock_label_capture'),
    path('label/rocks/datasets/', views.rock_dataset_list, name='rock_dataset_list'),
    path('label/rocks/categories/', views.rock_category_list, name='rock_category_list'),

    # Training dataset management
    path('api/training/datasets/', views.list_training_datasets, name='list_training_datasets'),
    path('api/training/datasets/create/', views.create_training_dataset, name='create_training_dataset'),
    path('api/training/datasets/<int:dataset_id>/', views.get_dataset_details, name='get_dataset_details'),
    path('api/training/datasets/add-label/', views.add_label_to_dataset, name='add_label_to_dataset'),
    
    # Mission planning API endpoints
    path('label/api/missions/', views.list_missions, name='list_missions'),
    path('label/api/missions/create/', views.create_mission, name='create_mission'),
    path('label/api/missions/<int:mission_id>/', views.get_mission, name='get_mission'),
    path('label/api/missions/<int:mission_id>/update/', views.update_mission, name='update_mission'),
    path('label/api/missions/<int:mission_id>/delete/', views.delete_mission, name='delete_mission'),
    path('label/api/missions/<int:mission_id>/waypoints/add/', views.add_waypoint, name='add_waypoint'),
    path('label/api/missions/<int:mission_id>/waypoints/<int:waypoint_id>/remove/', views.remove_waypoint, name='remove_waypoint'),
    
    # World Sampler API endpoints
    path('webclient/sampler/initialize', world_sampler_api.initialize_sampler, name='initialize_sampler'),
    path('webclient/sampler/sample', world_sampler_api.sample_locations, name='sample_locations'),
    path('webclient/sampler/update', world_sampler_api.update_distribution, name='update_distribution'),
    path('webclient/sampler/query', world_sampler_api.query_region, name='query_region'),
    path('webclient/sampler/statistics', world_sampler_api.get_statistics, name='get_sampler_statistics'),
    path('webclient/sampler/reset', world_sampler_api.reset_sampler, name='reset_sampler'),
    path('webclient/sampler/history', world_sampler_api.get_sample_history, name='get_sample_history'),
    path('webclient/sampler/scored', world_sampler_api.get_scored_locations, name='get_scored_locations'),
    path('webclient/sampler/analyze-viewport', world_sampler_api.analyze_viewport, name='analyze_viewport'),
    path('webclient/sampler/vegetation-targets', world_sampler_api.get_vegetation_targets, name='get_vegetation_targets'),
    path('webclient/sampler/annotation-game/save', world_sampler_api.save_annotation_game_round, name='save_annotation_game_round'),
    path('webclient/sampler/annotation-game/export-coco', world_sampler_api.export_annotation_game_coco, name='export_annotation_game_coco'),
    path('webclient/sampler/annotation-game/export-graph', world_sampler_api.export_annotation_game_graph, name='export_annotation_game_graph'),
    
    # AI Analysis Report
    path('label/ai-analysis/report/<str:session_id>/', views.ai_analysis_report, name='ai_analysis_report'),
    path('label/ai-analysis/image/<str:session_id>/<str:image_type>/', views.serve_analysis_image, name='serve_analysis_image'),
    path('label/ai-analysis/geojson/<str:session_id>/', views.serve_analysis_geojson, name='serve_analysis_geojson'),
    
    # Authentication API endpoints (AJAX)
    path('api/auth/status/', views.check_auth_status, name='check_auth_status'),
    path('api/auth/login/', views.ajax_phone_login, name='ajax_phone_login'),
    path('api/auth/logout/', views.ajax_logout, name='ajax_logout'),
] 