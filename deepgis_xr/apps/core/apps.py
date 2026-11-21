from __future__ import unicode_literals

from django.apps import AppConfig


class CoreConfig(AppConfig):
    name = 'deepgis_xr.apps.core'
    verbose_name = 'Core'

    def ready(self):
        from deepgis_xr.apps.core.label_dashboard import install
        install()
