"""Keep field readings and the scene-graph store off the SQLite registry.

FieldReading and every model in the scene_store app belong in the
observations database (PostGIS). Every other model stays on the default
database, which is SQLite in production.
"""


class FieldReadingRouter:
    model = "fieldreading"
    apps = {"scene_store"}
    db = "observations"

    def _routed(self, app_label, model_name):
        return model_name == self.model or app_label in self.apps

    def db_for_read(self, model, **hints):
        if self._routed(model._meta.app_label, model._meta.model_name):
            return self.db
        return None

    db_for_write = db_for_read

    def allow_relation(self, obj1, obj2, **hints):
        return None

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        routed = self._routed(app_label, model_name)
        if db == self.db:
            return routed
        if routed:
            return False
        return None
