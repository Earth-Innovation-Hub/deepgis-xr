import django.contrib.gis.db.models.fields
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('scene_store', '0005_layers_imagery_checks'),
    ]

    operations = [
        migrations.CreateModel(
            name='Zone',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('slug', models.CharField(max_length=80, unique=True)),
                ('name', models.CharField(max_length=120)),
                ('taxonomy', models.CharField(default='urban_v1', max_length=40)),
                ('area', django.contrib.gis.db.models.fields.MultiPolygonField(srid=4326)),
                ('source', models.CharField(blank=True, default='', max_length=200)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'db_table': 'sg_zone',
                'ordering': ['slug'],
            },
        ),
    ]
