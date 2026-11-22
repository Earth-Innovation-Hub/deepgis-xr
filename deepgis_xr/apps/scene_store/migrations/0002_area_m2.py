from django.db import migrations, models

DETECTION_AREA_SQL = 'UPDATE sg_detection SET area_m2 = ST_Area(geom::geography)'

ENTITY_AREA_SQL = """
UPDATE sg_entity e SET area_m2 = m.area
FROM (SELECT a.entity_id, percentile_cont(0.5) WITHIN GROUP (ORDER BY d.area_m2) AS area
      FROM sg_association a JOIN sg_detection d ON d.id = a.detection_id
      GROUP BY a.entity_id) m
WHERE e.id = m.entity_id
"""


class Migration(migrations.Migration):

    dependencies = [
        ('scene_store', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='detection',
            name='area_m2',
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='entity',
            name='area_m2',
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.RunSQL(DETECTION_AREA_SQL, migrations.RunSQL.noop),
        migrations.RunSQL(ENTITY_AREA_SQL, migrations.RunSQL.noop),
    ]
