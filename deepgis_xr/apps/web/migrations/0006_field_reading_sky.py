from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("web", "0005_field_reading_analysis"),
    ]

    operations = [
        migrations.AddField(
            model_name="fieldreading",
            name="sky",
            field=models.JSONField(blank=True, null=True),
        ),
    ]
