from django.urls import include, path

from .views import observe, prediction, training

urlpatterns = [
    # Tile catalog (Site -> Dataset -> Timestep -> Product hierarchy)
    path('tile-catalog/', include('deepgis_xr.apps.tile_catalog.urls')),


    # Prediction endpoints
    path('predict/tile/',
         prediction.predict_tile,
         name='predict_tile'),

    path('predict/save/',
         prediction.save_predictions,
         name='save_predictions'),

    # Training endpoints
    path('train/start/',
         training.start_training,
         name='start_training'),

    path('train/status/<str:task_id>/',
         training.get_training_status,
         name='get_training_status'),

    # earth_rover -> deepgis observation stream + scene-graph publish (PR-6)
    path('observe/',
         observe.post_observation,
         name='post_observation'),

    path('scene-graph/',
         observe.get_scene_graph,
         name='get_scene_graph'),
]
