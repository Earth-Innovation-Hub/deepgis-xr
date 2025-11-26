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
    path('map-label/', views.map_label, name='map_label'),
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
    
    # Map label endpoints
    path('webclient/save-labels', views.save_labels, name='save_labels'),
    path('webclient/export-shapefile', views.export_shapefile, name='export_shapefile'),
    
    # Grid detection endpoint
    path('webclient/detect-grid', views.detect_grid, name='detect_grid'),
    
    # 3D model endpoints
    path('webclient/get-3d-model', views.get_3d_model, name='get_3d_model'),
    path('webclient/list-stl-models', views.list_stl_models, name='list_stl_models'),
    
    # API endpoints
    path('api/elevation-proxy', views.elevation_proxy, name='elevation_proxy'),
    
    # Semi-supervised labeling (Mask2Former / Segment Anything)
    path('label/semi-supervised/', views.label_semi_supervised, name='label_semi_supervised'),
    path('label/semi-supervised/api/generate-labels/', views.generate_assisted_labels, name='generate_assisted_labels'),
    path('label/semi-supervised/api/save-labels/', views.save_assisted_labels, name='save_assisted_labels'),
    path('label/semi-supervised/api/get-images/', views.get_label_images, name='get_label_images'),
    
    # World Sampler API endpoints
    path('webclient/sampler/initialize', world_sampler_api.initialize_sampler, name='initialize_sampler'),
    path('webclient/sampler/sample', world_sampler_api.sample_locations, name='sample_locations'),
    path('webclient/sampler/update', world_sampler_api.update_distribution, name='update_distribution'),
    path('webclient/sampler/query', world_sampler_api.query_region, name='query_region'),
    path('webclient/sampler/statistics', world_sampler_api.get_statistics, name='get_sampler_statistics'),
    path('webclient/sampler/reset', world_sampler_api.reset_sampler, name='reset_sampler'),
    path('webclient/sampler/history', world_sampler_api.get_sample_history, name='get_sample_history'),
] 