from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("web", "0004_field_reading"),
    ]

    operations = [
        migrations.AddField(
            model_name="fieldreading",
            name="analysis",
            field=models.JSONField(blank=True, null=True),
        ),
    ]
