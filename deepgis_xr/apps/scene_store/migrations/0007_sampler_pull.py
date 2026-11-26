import django.contrib.gis.db.models.fields
import django.contrib.postgres.fields
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('scene_store', '0006_zone'),
    ]

    operations = [
        migrations.CreateModel(
            name='SamplerPull',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('policy', models.CharField(max_length=20)),
                ('run', models.CharField(blank=True, default='', max_length=40)),
                ('taxonomy', models.CharField(max_length=40)),
                ('centre', django.contrib.gis.db.models.fields.PointField(srid=4326)),
                ('band', models.IntegerField()),
                ('gsd_m', models.FloatField()),
                ('image_size', django.contrib.postgres.fields.ArrayField(base_field=models.IntegerField(), size=2)),
                ('predicted', models.JSONField(blank=True, default=dict)),
                ('realised', models.JSONField(blank=True, null=True)),
                ('user_id', models.IntegerField(blank=True, null=True)),
                ('capture', models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                                                 related_name='pull', to='scene_store.capture')),
            ],
            options={
                'db_table': 'sg_sampler_pull',
                'indexes': [models.Index(fields=['taxonomy', 'run', '-id'], name='sg_pull_run_idx')],
            },
        ),
    ]
