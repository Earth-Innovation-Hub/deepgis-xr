from django.urls import path
from . import views
from deepgis_xr.apps.web.views import label_3d_sigma

urlpatterns = [
    # Main pages
    path('', views.index, name='index'),
    path('label/', views.label, name='label'),
    path('label/3d/', views.label_3d, name='label_3d'),
    path('label/3d/dev/', views.label_3d_dev, name='label_3d_dev'),
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
    
    # Add this new URL pattern
    path('label/3d/sigma/', label_3d_sigma, name='label_3d_sigma'),
] 