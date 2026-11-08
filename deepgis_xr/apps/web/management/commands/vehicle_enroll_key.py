"""Print a field robot's enrollment key for VEHICLE_ENROLL_SECRET.

The key is a credential: pipe it straight into a mode-600 file on the robot rather than
printing it, e.g.
    python manage.py vehicle_enroll_key <id> | ssh <robot> 'umask 077; cat > <key file>'
"""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from deepgis_xr.apps.web.views import vehicles


class Command(BaseCommand):
    help = "Print the enrollment key a field robot posts its pose with."

    def add_arguments(self, parser):
        parser.add_argument("vehicle_id")

    def handle(self, vehicle_id, **options):
        if not settings.VEHICLE_ENROLL_SECRET:
            raise CommandError("VEHICLE_ENROLL_SECRET is not set")
        if not vehicles.VEHICLE_ID.fullmatch(vehicle_id):
            raise CommandError("ids are 1-40 characters of a-z, 0-9, _ and -")
        prefix = settings.VEHICLE_FLEET_PREFIX
        if ((prefix and vehicle_id.startswith(prefix)) or vehicle_id in vehicles.pose_tokens().values()
                or not vehicles.robots.field_id_free(vehicle_id, refresh=True)):
            raise CommandError(f"{vehicle_id} is reserved for a sim or a configured publisher")
        self.stdout.write(vehicles.enroll_token(settings.VEHICLE_ENROLL_SECRET, vehicle_id))
