"""
Adds the SceneGraph table — persisted output of the Distinction-Game
SceneGraph orchestrator (`/webclient/sampler/scenegraph/build`).

Schema is intentionally JSON-heavy: geometry/posteriors/edges all live
in JSONField columns so that the kernelcal data contract
(`kernelcal.distinction_game.SceneGraph.to_dict()`) can evolve in PR-3
without schema migrations.
"""

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('web', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='SceneGraph',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('session_id', models.CharField(db_index=True, help_text='Unique scene-graph build id (e.g. scenegraph_<ts>_<latlon>)', max_length=255)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('taxonomy_name', models.CharField(default='phx_urban_v0', help_text='kernelcal.distinction_game taxonomy used for fusion', max_length=64)),
                ('kernels_used', models.JSONField(default=list, help_text="List of kernel source ids whose claims were fused (e.g. ['osm','mr_rocks'])")),
                ('viewport', models.JSONField(default=dict, help_text='Viewport metadata at capture time: {image_size, world_corners, camera, image_path}. Mirrors kernelcal Viewport.to_dict().')),
                ('nodes', models.JSONField(default=list, help_text='Fused SceneNodes as JSON (each with category_posterior, geometry, source_claims)')),
                ('edges', models.JSONField(default=list, help_text='SceneEdges as JSON (centroid-proximity adjacency by default)')),
                ('fusion_metadata', models.JSONField(default=dict, help_text='Mix lambdas, q_s ids, association params, n_claims_dropped_below_min_score, and any spectral-diagnostic stats added in PR-3.')),
                ('artifact_path', models.CharField(blank=True, default='', help_text='Optional path under /app/deepgis_results/scenegraph_results/ where the JSON payload + query image were also written for offline inspection and retraining-pipeline ingestion.', max_length=512)),
                ('sampling_session', models.ForeignKey(blank=True, help_text='Parent sampling session, if the build was launched inside one', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='scene_graphs', to='web.samplingsession')),
                ('user', models.ForeignKey(blank=True, help_text='User who triggered the build (nullable for unauth /smoke runs)', null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'db_table': 'scene_graphs',
                'ordering': ['-created_at'],
                'indexes': [
                    models.Index(fields=['session_id'], name='scene_graph_sess_idx'),
                    models.Index(fields=['-created_at'], name='scene_graph_created_idx'),
                    models.Index(fields=['user', '-created_at'], name='scene_graph_user_idx'),
                ],
            },
        ),
    ]
