"""
World Sampler Models

Django models for persisting geospatial sampling data and feedback.
"""

from django.db import models
from django.conf import settings
from django.utils import timezone


class SampledLocation(models.Model):
    """
    Stores sampled locations with their scores/feedback.
    Records (lat, lon, zoom) triples along with user feedback.
    """
    # Location data
    latitude = models.FloatField(help_text="Latitude in degrees [-90, 90]")
    longitude = models.FloatField(help_text="Longitude in degrees [-180, 180]")
    altitude = models.FloatField(help_text="Altitude in meters")
    zoom_level = models.IntegerField(help_text="Cesium zoom level (0-28)")
    
    # Scoring data
    score = models.FloatField(
        default=0.0,
        help_text="User feedback score (positive = interesting, negative = avoid)"
    )
    weight = models.FloatField(
        default=1.0,
        help_text="Sampling weight/probability at time of sampling"
    )
    
    # Metadata
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        help_text="User who provided feedback"
    )
    session_id = models.CharField(
        max_length=255,
        default='default',
        help_text="Session identifier for grouping samples"
    )
    sampled_at = models.DateTimeField(
        auto_now_add=True,
        help_text="When this location was sampled"
    )
    scored_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When user provided feedback"
    )
    
    # Additional context
    metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text="Additional metadata (camera params, terrain info, etc.)"
    )
    
    class Meta:
        db_table = 'sampled_locations'
        ordering = ['-sampled_at']
        indexes = [
            models.Index(fields=['latitude', 'longitude']),
            models.Index(fields=['session_id', 'sampled_at']),
            models.Index(fields=['score']),
            models.Index(fields=['-sampled_at']),
        ]
    
    def __str__(self):
        return f"({self.latitude:.4f}, {self.longitude:.4f}, z{self.zoom_level}) score={self.score}"


class SamplingSession(models.Model):
    """
    Tracks sampling sessions with initialization parameters and statistics.
    """
    session_id = models.CharField(
        max_length=255,
        unique=True,
        help_text="Unique session identifier"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="User who created the session"
    )
    
    # Initialization parameters
    num_points = models.IntegerField(default=1000)
    initialization_method = models.CharField(
        max_length=50,
        choices=[
            ('uniform', 'Uniform Distribution'),
            ('gaussian_mixture', 'Gaussian Mixture'),
            ('population_weighted', 'Population Weighted'),
        ],
        default='uniform'
    )
    lat_range_min = models.FloatField(default=-90)
    lat_range_max = models.FloatField(default=90)
    lon_range_min = models.FloatField(default=-180)
    lon_range_max = models.FloatField(default=180)
    alt_range_min = models.FloatField(default=0)
    alt_range_max = models.FloatField(default=5000)
    
    # Session metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    # Statistics
    total_samples = models.IntegerField(default=0)
    total_updates = models.IntegerField(default=0)
    
    class Meta:
        db_table = 'sampling_sessions'
        ordering = ['-created_at']
    
    def __str__(self):
        return f"Session {self.session_id} ({self.initialization_method})"


class DistributionUpdate(models.Model):
    """
    Logs updates to the sampling distribution.
    """
    session = models.ForeignKey(
        SamplingSession,
        on_delete=models.CASCADE,
        related_name='updates'
    )
    
    # Update details
    update_rule = models.CharField(
        max_length=50,
        choices=[
            ('reward', 'Reward'),
            ('exploration', 'Exploration'),
            ('concentration', 'Concentration'),
            ('custom', 'Custom'),
        ],
        help_text="Update rule applied"
    )
    learning_rate = models.FloatField(help_text="Learning rate used")
    radius = models.FloatField(
        null=True,
        blank=True,
        help_text="Influence radius in meters"
    )
    
    # Feedback points that triggered this update
    feedback_locations = models.ManyToManyField(
        SampledLocation,
        related_name='caused_updates',
        blank=True,
        help_text="Locations whose feedback triggered this update"
    )
    
    # Metadata
    applied_at = models.DateTimeField(auto_now_add=True)
    parameters = models.JSONField(
        default=dict,
        help_text="Additional update parameters"
    )
    
    class Meta:
        db_table = 'distribution_updates'
        ordering = ['-applied_at']
    
    def __str__(self):
        return f"{self.update_rule} update at {self.applied_at}"


class SceneGraph(models.Model):
    """
    Persisted output of the Distinction-Game SceneGraph orchestrator.

    One row = one fused multi-kernel reading of a single Cesium viewport.
    Geometry is stored as JSON (no PostGIS); the canonical structure is
    whatever ``kernelcal.distinction_game.SceneGraph.to_dict()`` emits,
    so consumers can round-trip with::

        from kernelcal.distinction_game import SceneGraph as KCSceneGraph
        kc = KCSceneGraph.from_dict({
            "viewport": row.viewport,
            "nodes": row.nodes,
            "edges": row.edges,
            "fusion_metadata": row.fusion_metadata,
        })

    The model is deliberately schema-light: as the kernel-mix evolves
    (PR-3 Lagrange fit, retraining trigger), only the JSON payload
    changes, not the Django schema.
    """

    session_id = models.CharField(
        max_length=255,
        db_index=True,
        help_text="Unique scene-graph build id (e.g. scenegraph_<ts>_<latlon>)",
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="User who triggered the build (nullable for unauth /smoke runs)",
    )

    sampling_session = models.ForeignKey(
        SamplingSession,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='scene_graphs',
        help_text="Parent sampling session, if the build was launched inside one",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    taxonomy_name = models.CharField(
        max_length=64,
        default='phx_urban_v0',
        help_text="kernelcal.distinction_game taxonomy used for fusion",
    )

    kernels_used = models.JSONField(
        default=list,
        help_text="List of kernel source ids whose claims were fused (e.g. ['osm','mr_rocks'])",
    )

    viewport = models.JSONField(
        default=dict,
        help_text=(
            "Viewport metadata at capture time: {image_size, world_corners, "
            "camera, image_path}. Mirrors kernelcal Viewport.to_dict()."
        ),
    )

    nodes = models.JSONField(
        default=list,
        help_text="Fused SceneNodes as JSON (each with category_posterior, geometry, source_claims)",
    )

    edges = models.JSONField(
        default=list,
        help_text="SceneEdges as JSON (centroid-proximity adjacency by default)",
    )

    fusion_metadata = models.JSONField(
        default=dict,
        help_text=(
            "Mix lambdas, q_s ids, association params, n_claims_dropped_below_min_score, "
            "and any spectral-diagnostic stats added in PR-3."
        ),
    )

    artifact_path = models.CharField(
        max_length=512,
        blank=True,
        default='',
        help_text=(
            "Optional path under /app/deepgis_results/scenegraph_results/ "
            "where the JSON payload + query image were also written for offline "
            "inspection and retraining-pipeline ingestion."
        ),
    )

    class Meta:
        db_table = 'scene_graphs'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['session_id'], name='scene_graph_sess_idx'),
            models.Index(fields=['-created_at'], name='scene_graph_created_idx'),
            models.Index(fields=['user', '-created_at'], name='scene_graph_user_idx'),
        ]

    def __str__(self):
        return (
            f"SceneGraph {self.session_id} "
            f"(n_nodes={len(self.nodes or [])}, n_edges={len(self.edges or [])})"
        )

