from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("web", "0006_field_reading_sky"),
    ]

    operations = [
        migrations.AddField(
            model_name="fieldreading",
            name="adsb",
            field=models.JSONField(blank=True, null=True),
        ),
    ]
