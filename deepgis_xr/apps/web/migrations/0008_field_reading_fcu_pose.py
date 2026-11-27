from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("web", "0007_field_reading_adsb"),
    ]

    operations = [
        migrations.AddField(
            model_name="fieldreading",
            name="fcu_pose",
            field=models.JSONField(
                blank=True,
                null=True,
                help_text=(
                    "The flight controller's EKF pose nearest the frame, in PX4's frames: local NED "
                    "position and velocity, NED-to-FRD quaternion [w, x, y, z], body rates, and the "
                    "21-element upper-triangle pose and velocity covariances (null = unknown). Body "
                    "pose, not the camera's; mount holds the camera parameters used."
                ),
            ),
        ),
    ]
