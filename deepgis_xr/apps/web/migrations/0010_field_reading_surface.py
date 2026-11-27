from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("web", "0009_field_reading_aim"),
    ]

    operations = [
        migrations.AddField(
            model_name="fieldreading",
            name="surface",
            field=models.JSONField(
                blank=True,
                null=True,
                help_text=(
                    "What the keyframe shows under the spectrometer's patch: label (the surface filling "
                    "at least half of it, else mixed), share, shares per surface, the patch [u, v, width "
                    "as a share of the image], the model, and the reading it was copied from when the "
                    "view had already been segmented."
                ),
            ),
        ),
    ]
