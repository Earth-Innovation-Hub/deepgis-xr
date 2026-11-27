"""Fit what a capture of each cell should find, per category, from an area's covariates.

    python manage.py fit_area_contents --name tempe --taxonomy urban_v1           # report only
    python manage.py fit_area_contents --name tempe --taxonomy urban_v1 --apply   # store it

Stored as ``<name>.<taxonomy>.json`` beside the covariates; the sampler uses it from the next
proposal. Fitted on every SAM 3 capture of the taxonomy over the area; re-run it when there
are many new captures.
"""

from django.core.management.base import BaseCommand, CommandError

from deepgis_xr.apps.scene_store import contents


class Command(BaseCommand):
    help = 'Fit the expected detections per category and cell from the covariates (dry run unless --apply).'

    def add_arguments(self, parser):
        parser.add_argument('--name', required=True)
        parser.add_argument('--taxonomy', default='urban_v1')
        parser.add_argument('--apply', action='store_true')

    def handle(self, *args, name, taxonomy, apply, **opts):
        try:
            model = contents.fit(name, taxonomy, write=apply)
        except ValueError as exc:
            raise CommandError(str(exc))
        cv = model['cv_deviance_per_row']
        self.stdout.write(f"{name} / {taxonomy}: {model['n_captures']} captures, {model['n_rows']} cell rows, "
                          f"categories {', '.join(model['categories'])}")
        self.stdout.write(f"  held-out deviance per row: zoom band alone {cv['band_only']}, with covariates {cv['model']}")
        self.stdout.write(f"  ridge per category: {dict(zip(model['categories'], model['lambdas']))}")
        self.stdout.write(f"  expected detections in a default view, area median by band: "
                          f"{[round(v, 1) for v in model['band_mean']]}")
        self.stdout.write(f"  content held at most at, by band: {model['content_cap']}")
        self.stdout.write('stored' if apply else 'dry run: nothing stored (add --apply)')
