from django.contrib.gis.db import models as gis
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("web", "0003_observation"),
    ]

    operations = [
        migrations.CreateModel(
            name="FieldReading",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("vehicle_id", models.CharField(max_length=40)),
                ("captured_usec", models.BigIntegerField()),
                ("captured", models.DateTimeField()),
                ("alt_amsl", models.FloatField(blank=True, null=True)),
                ("heading_deg", models.FloatField(blank=True, null=True)),
                ("pitch_deg", models.FloatField(blank=True, null=True)),
                ("speed_mps", models.FloatField(blank=True, null=True)),
                ("camera", gis.PointField(blank=True, geography=True, null=True, srid=4326)),
                ("range_m", models.FloatField(blank=True, null=True)),
                ("range_min_m", models.FloatField(blank=True, null=True)),
                ("range_max_m", models.FloatField(blank=True, null=True)),
                ("range_valid", models.BooleanField(default=False)),
                ("target", gis.PointField(blank=True, geography=True, null=True, srid=4326)),
                ("target_up_m", models.FloatField(blank=True, null=True)),
                ("image_relpath", models.CharField(blank=True, default="", max_length=300)),
                ("image_bytes", models.PositiveIntegerField(blank=True, null=True)),
                ("width", models.PositiveSmallIntegerField(blank=True, null=True)),
                ("height", models.PositiveSmallIntegerField(blank=True, null=True)),
                ("spectrum", models.JSONField(blank=True, null=True)),
            ],
            options={
                "db_table": "field_readings",
                "indexes": [models.Index(fields=["-captured"], name="field_reading_captured_idx")],
                "constraints": [
                    models.UniqueConstraint(fields=("vehicle_id", "captured_usec"), name="field_reading_capture")
                ],
            },
        )
    ]

