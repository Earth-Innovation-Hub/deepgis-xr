from django.apps import AppConfig


class SceneStoreConfig(AppConfig):
    name = 'deepgis_xr.apps.scene_store'
    label = 'scene_store'
    verbose_name = 'Spatiotemporal scene-graph store'
    default_auto_field = 'django.db.models.BigAutoField'
