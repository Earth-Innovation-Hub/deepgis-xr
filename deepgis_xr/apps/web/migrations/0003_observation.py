"""Adds the Observation table for the earth_rover -> deepgis stream.

The model backs the new ``POST /api/observe`` endpoint (PR-6).  Each row
captures one packed-superquadric payload produced by an upstream
client (typically the earth_rover after running its onboard SLAM +
attribution pipeline), and the server-side decoded view in ECEF.

The schema is intentionally JSON-heavy for the same reason as
``SceneGraph`` (PR-4): the wire codec evolves in kernelcal, but the
Django table doesn't have to.
"""

from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('web', '0002_scenegraph'),
    ]

    operations = [
        migrations.CreateModel(
            name='Observation',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('session_id', models.CharField(db_index=True, help_text='Stream / mission id; multiple observations share this.', max_length=255)),
                ('source_id', models.CharField(db_index=True, help_text="Logical source of the observation, e.g. 'earth_rover_01' or 'osm_anchor'.  Used as the kernel-source key when fusing with the distinction-game pipeline.", max_length=128)),
                ('received_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('sensor_timestamp', models.DateTimeField(blank=True, help_text='Sensor / SLAM timestamp from the producer.', null=True)),
                ('n_superquadrics', models.PositiveIntegerField(default=0)),
                ('src_frame', models.JSONField(default=dict, help_text='FrameSpec.to_dict() of the producer frame (e.g. UTM zone 12N, ENU local at lat0/lon0/alt0).')),
                ('bbox_wgs84', models.JSONField(default=dict, help_text='Axis-aligned WGS84 bbox of all superquadric centroids after server-side transform: {lat_min, lat_max, lon_min, lon_max, alt_min, alt_max}.')),
                ('payload', models.BinaryField(help_text='Concatenated packed-superquadric bytes (32-byte SQ header + optional parent / property / spectrum trailers, per kernelcal.distinction_game.geometry.codec).')),
                ('payload_size', models.PositiveIntegerField(default=0, help_text='Length of the payload BLOB in bytes.')),
                ('superquadrics_ecef', models.JSONField(default=list, help_text='Server-side decoded view of the SQs: list of {class_idx, t_ecef:[X,Y,Z], R, scale, epsilon, parent_hash, properties:{name:value}, spectrum?:{...}}.  Useful for admin inspection, low-bandwidth clients, and integration with the existing scene-graph collapse pipeline.')),
                ('attributes', models.JSONField(blank=True, default=dict, help_text='Free-form metadata from the producer: pose covariance, GPS fix quality, mission tags, processing flags.')),
                ('user', models.ForeignKey(blank=True, help_text='Authenticated user who pushed this observation.', null=True, on_delete=models.SET_NULL, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'db_table': 'observations',
                'ordering': ['-received_at'],
                'indexes': [
                    models.Index(fields=['source_id', '-received_at'], name='obs_source_recv_idx'),
                    models.Index(fields=['session_id', '-received_at'], name='obs_session_recv_idx'),
                ],
            },
        ),
    ]
