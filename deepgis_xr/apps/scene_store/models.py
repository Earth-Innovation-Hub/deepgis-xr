"""Spatiotemporal scene-graph store (PostGIS, observations database).

Layers, oldest evidence first:

  Capture -> Pose                                where the sensor was, with its uncertainty
  Capture -> KernelRun -> Detection -> Claim     what each kernel saw, when and where
  Entity <- Association -> Detection             one world object per variable
  Factor                                         log-potential tables over entity variables
  BeliefSnapshot                                 the posterior each time inference touched it
  Feedback, UserPreference                       user corrections and settings

Each entity has two variables: ``c<id>`` (category, taxonomy-sized) and
``x<id>`` (exists, [absent, present]). Factors store their raw log table;
time decay is applied when inference runs, so a belief can be recomputed
for any past instant from the factors valid then.

Every model here lives in the PostGIS ``observations`` database
(see ``deepgis_xr.db_router``). Users are stored as plain ids because
foreign keys cannot cross databases.
"""

from django.contrib.gis.db import models as gis
from django.contrib.postgres.fields import ArrayField, DateTimeRangeField
from django.contrib.postgres.indexes import GinIndex, GistIndex
from django.db import models


class Capture(models.Model):
    """One fused SceneGraph of one viewport at one instant."""

    session_id = models.CharField(max_length=120, unique=True)
    captured_at = models.DateTimeField()
    recorded_at = models.DateTimeField(auto_now_add=True)
    user_id = models.IntegerField(null=True, blank=True)
    taxonomy = models.CharField(max_length=40)
    footprint = gis.PolygonField(srid=4326)
    camera = gis.PointField(srid=4326, null=True, blank=True)
    camera_alt_m = models.FloatField(null=True, blank=True)
    camera_pose = models.JSONField(default=dict, blank=True)
    image_size = ArrayField(models.IntegerField(), size=2, null=True, blank=True)
    gsd_m = models.FloatField(null=True, blank=True)  # mean ground size of a pixel: sqrt(footprint / pixels)
    sources = ArrayField(models.CharField(max_length=40), default=list, blank=True)
    artifact_path = models.CharField(max_length=300, blank=True, default='')
    summary = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = 'sg_capture'
        indexes = [models.Index(fields=['-captured_at'], name='sg_capture_time_idx')]


class Pose(models.Model):
    """A sensor pose estimate for a capture (or a rover keyframe), with 1-sigma uncertainty.

    A later estimate (loop closure, RTK, imagery-bias correction) supersedes an earlier
    one instead of overwriting it. Angles are degrees, Cesium convention.
    """

    SOURCES = [
        ('virtual_camera', 'virtual_camera'),  # the 3D globe's camera; error is the imagery's
        ('vio', 'vio'),                        # visual(-inertial) odometry
        ('gps', 'gps'),
        ('rtk', 'rtk'),
        ('optimized', 'optimized'),            # pose-graph solution
    ]

    capture = models.ForeignKey(Capture, on_delete=models.CASCADE, null=True, blank=True, related_name='poses')
    source = models.CharField(max_length=20, choices=SOURCES)
    at = models.DateTimeField()
    position = gis.PointField(srid=4326)
    alt_m = models.FloatField(null=True, blank=True)
    heading_deg = models.FloatField(null=True, blank=True)
    pitch_deg = models.FloatField(null=True, blank=True)
    roll_deg = models.FloatField(null=True, blank=True)
    sigma_h_m = models.FloatField(null=True, blank=True)
    sigma_v_m = models.FloatField(null=True, blank=True)
    sigma_rot_deg = models.FloatField(null=True, blank=True)
    covariance = ArrayField(models.FloatField(), size=36, null=True, blank=True)  # 6x6 ENU m / rad, row-major
    recorded_at = models.DateTimeField(auto_now_add=True)
    superseded_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = 'sg_pose'
        indexes = [models.Index(fields=['capture', 'superseded_at'], name='sg_pose_capture_idx'),
                   models.Index(fields=['at'], name='sg_pose_time_idx')]


class KernelRun(models.Model):
    capture = models.ForeignKey(Capture, on_delete=models.CASCADE, related_name='runs')
    kernel_kind = models.CharField(max_length=40)
    source_id = models.CharField(max_length=40, blank=True, default='')
    model = models.CharField(max_length=80, blank=True, default='')
    params = models.JSONField(default=dict, blank=True)
    n_claims = models.IntegerField(default=0)

    class Meta:
        db_table = 'sg_kernel_run'


class Detection(models.Model):
    """A SceneGraph node: one region in one capture, with its fused posterior."""

    capture = models.ForeignKey(Capture, on_delete=models.CASCADE, related_name='detections')
    node_id = models.CharField(max_length=40)
    observed_at = models.DateTimeField()
    geom = gis.PolygonField(srid=4326)
    area_m2 = models.FloatField(null=True, blank=True)  # geodesic area of geom
    category = models.CharField(max_length=40)
    posterior = ArrayField(models.FloatField())
    score = models.FloatField()
    sources = ArrayField(models.CharField(max_length=40), default=list, blank=True)
    gate = models.CharField(max_length=20, blank=True, default='')  # why it is not evidence ('frame'), or ''

    class Meta:
        db_table = 'sg_detection'
        indexes = [models.Index(fields=['observed_at'], name='sg_detection_time_idx')]


class Claim(models.Model):
    """One kernel's raw claim inside a detection (the calibration signal for Q_s)."""

    detection = models.ForeignKey(Detection, on_delete=models.CASCADE, related_name='claims')
    source_id = models.CharField(max_length=40)
    native_label = models.CharField(max_length=80)
    score = models.FloatField()
    geom = gis.PolygonField(srid=4326, null=True, blank=True)

    class Meta:
        db_table = 'sg_claim'
        indexes = [models.Index(fields=['source_id', 'native_label'], name='sg_claim_label_idx')]


class Entity(models.Model):
    """A persistent world object; the cached result of the last inference."""

    taxonomy = models.CharField(max_length=40)
    category = models.CharField(max_length=40)
    posterior = ArrayField(models.FloatField())
    score = models.FloatField()
    p_exists = models.FloatField(default=0.5)
    geom = gis.PolygonField(srid=4326)
    area_m2 = models.FloatField(null=True, blank=True)  # median over its detections, not the area of geom
    first_seen = models.DateTimeField()
    last_seen = models.DateTimeField()
    n_hits = models.IntegerField(default=0)
    n_misses = models.IntegerField(default=0)
    sources = ArrayField(models.CharField(max_length=40), default=list, blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    # Retired entities keep their rows; their factors are superseded at ``retired_at``.
    retired_at = models.DateTimeField(null=True, blank=True)
    retired_reason = models.CharField(max_length=120, blank=True, default='')

    class Meta:
        db_table = 'sg_entity'
        indexes = [
            models.Index(fields=['taxonomy', 'category'], name='sg_entity_cat_idx'),
            models.Index(fields=['-last_seen'], name='sg_entity_seen_idx'),
        ]


class Association(models.Model):
    entity = models.ForeignKey(Entity, on_delete=models.CASCADE, related_name='associations')
    detection = models.OneToOneField(Detection, on_delete=models.CASCADE, related_name='association')
    iou = models.FloatField(null=True, blank=True)
    method = models.CharField(max_length=20)

    class Meta:
        db_table = 'sg_association'


class Feedback(models.Model):
    KINDS = [('confirm', 'confirm'), ('relabel', 'relabel'), ('reject', 'reject')]

    entity = models.ForeignKey(Entity, on_delete=models.CASCADE, related_name='feedback')
    user_id = models.IntegerField(null=True, blank=True)
    kind = models.CharField(max_length=20, choices=KINDS)
    category = models.CharField(max_length=40, blank=True, default='')
    note = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    superseded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'sg_feedback'


class Potential(models.Model):
    """A log table shared by many factors (context / containment priors per taxonomy)."""

    key = models.CharField(max_length=80, unique=True)
    log_table = models.JSONField()

    class Meta:
        db_table = 'sg_potential'


class Factor(models.Model):
    """A log-potential table over entity variables.

    The table is either inline (``log_table``, per-observation evidence) or
    shared (``potential``, priors that are identical for every pair).
    ``valid`` is when the evidence holds in the world; ``recorded_at`` and
    ``superseded_at`` are when the database believed it, so corrections
    never overwrite history.
    """

    KINDS = [
        ('perceptual', 'perceptual'),  # c: a detection's fused posterior
        ('hit', 'hit'),                # x: seen where expected
        ('miss', 'miss'),              # x: footprint covered it, a kernel that saw it before did not
        ('context', 'context'),        # c,c: adjacency co-occurrence
        ('contains', 'contains'),      # c,c: parent region contains child (roof -> solar panel)
        ('feedback', 'feedback'),      # c or x: user correction
        ('geometry', 'geometry'),      # c: a detection's ground area and shape against each category
    ]

    kind = models.CharField(max_length=20, choices=KINDS)
    variables = ArrayField(models.CharField(max_length=24))
    entity_ids = ArrayField(models.BigIntegerField())
    log_table = models.JSONField(null=True, blank=True)
    potential = models.ForeignKey(Potential, on_delete=models.PROTECT, null=True, blank=True)
    decays = models.BooleanField(default=True)
    valid = DateTimeRangeField()
    observed_at = models.DateTimeField()
    recorded_at = models.DateTimeField(auto_now_add=True)
    superseded_at = models.DateTimeField(null=True, blank=True)
    capture = models.ForeignKey(Capture, on_delete=models.CASCADE, null=True, blank=True, related_name='factors')
    detection = models.ForeignKey(Detection, on_delete=models.CASCADE, null=True, blank=True, related_name='factors')
    feedback = models.ForeignKey(Feedback, on_delete=models.CASCADE, null=True, blank=True, related_name='factors')
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = 'sg_factor'
        indexes = [
            GinIndex(fields=['entity_ids'], name='sg_factor_entities_gin'),
            GistIndex(fields=['valid'], name='sg_factor_valid_gist'),
            models.Index(fields=['kind'], name='sg_factor_kind_idx'),
        ]


class BeliefSnapshot(models.Model):
    entity = models.ForeignKey(Entity, on_delete=models.CASCADE, related_name='snapshots')
    at = models.DateTimeField()
    category = models.CharField(max_length=40)
    posterior = ArrayField(models.FloatField())
    p_exists = models.FloatField()
    cause = models.CharField(max_length=20)
    capture = models.ForeignKey(Capture, on_delete=models.SET_NULL, null=True, blank=True)
    feedback = models.ForeignKey(Feedback, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        db_table = 'sg_belief_snapshot'
        indexes = [models.Index(fields=['entity', '-at'], name='sg_snapshot_entity_idx')]


class UserPreference(models.Model):
    """Per-user settings: default kernels, SAM 3 prompts, thresholds, layer styling."""

    user_id = models.IntegerField()
    key = models.CharField(max_length=60)
    value = models.JSONField()
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'sg_user_preference'
        constraints = [models.UniqueConstraint(fields=['user_id', 'key'], name='sg_pref_user_key')]
