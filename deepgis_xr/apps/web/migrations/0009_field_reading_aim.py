from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("web", "0008_field_reading_fcu_pose"),
    ]

    operations = [
        migrations.AddField(
            model_name="fieldreading",
            name="aim",
            field=models.JSONField(
                blank=True,
                null=True,
                help_text=(
                    "How the target was placed: source (ekf or heading), azimuth and elevation of the "
                    "camera axis, its 1-sigma, the target's 1-sigma ground error, and with the EKF the "
                    "laser hit's height above the ground under the rover."
                ),
            ),
        ),
    ]
