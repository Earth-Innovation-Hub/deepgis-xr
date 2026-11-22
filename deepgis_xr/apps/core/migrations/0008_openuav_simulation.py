"""Registry of OpenUAV desktops. One row per desktop, not per robot.

Seeds the three lab sims. The public tab is derived from host_port as
/openuav/llm/<port>/; no host address is stored.
"""

from django.conf import settings
from django.db import migrations, models
import django.core.validators
import django.db.models.deletion


LAB_SIMS = [
    {
        "slug": "aquatic",
        "name": "Kiwanis Lake",
        "container": "digital-twin-aquatic",
        "host_port": 40077,
        "world": "Kiwanis Lake",
        "robots": ["otter_k", "xudrone"],
        "commands": True,
        "kind": "lab",
        "position": 1,
    },
    {
        "slug": "locutus",
        "name": "Locutus",
        "container": "digital-twin-locutus",
        "host_port": 40088,
        "world": "Locutus",
        "robots": ["kestrel", "badger"],
        "commands": True,
        "kind": "lab",
        "position": 2,
    },
    {
        "slug": "tempe-lake",
        "name": "Tempe Town Lake",
        "container": "digital-twin-water-tempe-lake",
        "host_port": 40099,
        "world": "Tempe Town Lake",
        "robots": ["otter"],
        "commands": True,
        "kind": "lab",
        "position": 3,
    },
]


def seed(apps, schema_editor):
    Simulation = apps.get_model("core", "Simulation")
    for row in LAB_SIMS:
        Simulation.objects.update_or_create(slug=row["slug"], defaults=row)


def unseed(apps, schema_editor):
    Simulation = apps.get_model("core", "Simulation")
    Simulation.objects.filter(slug__in=[row["slug"] for row in LAB_SIMS]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0007_robot_callsigns"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Simulation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("slug", models.SlugField(max_length=40, unique=True)),
                ("name", models.CharField(max_length=80)),
                ("container", models.CharField(max_length=80)),
                ("host_port", models.PositiveIntegerField(
                    help_text="Published noVNC port. The hub only proxies 40000-40999.",
                    unique=True,
                    validators=[
                        django.core.validators.MinValueValidator(40000),
                        django.core.validators.MaxValueValidator(40999),
                    ],
                )),
                ("world", models.CharField(max_length=120)),
                ("robots", models.JSONField(blank=True, default=list, help_text="Callsigns that share this desktop")),
                ("commands", models.BooleanField(
                    default=False,
                    help_text="The OpenUAV panel on this port can fly, not only show the desktop",
                )),
                ("kind", models.CharField(
                    choices=[("lab", "Lab twin"), ("session", "Session"), ("course", "Course")],
                    default="lab",
                    max_length=10,
                )),
                ("status", models.CharField(
                    choices=[("unknown", "Unknown"), ("up", "Up"), ("down", "Down")],
                    default="unknown",
                    max_length=10,
                )),
                ("last_seen", models.DateTimeField(blank=True, null=True)),
                ("position", models.PositiveSmallIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("owner", models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="openuav_sims",
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                "ordering": ["position", "name"],
            },
        ),
        migrations.RunPython(seed, unseed),
    ]
