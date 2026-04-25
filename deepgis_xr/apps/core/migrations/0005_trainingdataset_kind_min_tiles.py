# Generated for rock-label retraining pipeline

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0004_auto_20251129_1059'),
    ]

    operations = [
        migrations.AddField(
            model_name='trainingdataset',
            name='kind',
            field=models.CharField(
                choices=[
                    ('mask2former', 'Mask2Former (semantic)'),
                    ('rock_maskrcnn', 'Rock Mask R-CNN (400×400 tiles)'),
                ],
                default='mask2former',
                max_length=32,
            ),
        ),
        migrations.AddField(
            model_name='trainingdataset',
            name='min_tiles_for_training',
            field=models.PositiveIntegerField(default=50),
        ),
    ]
