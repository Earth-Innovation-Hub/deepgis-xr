"""Spatiotemporal scene-graph store (PostGIS, observations database).

Layers, oldest evidence first:

  Capture -> Pose                                where the sensor was, with its uncertainty
  Capture -> KernelRun -> Detection -> Claim     what each kernel saw, when and where
  Entity <- Association -> Detection             one world object per variable
  Factor                                         log-potential tables over entity variables
  BeliefSnapshot                                 the posterior each time inference touched it
  Feedback, UserPreference                       user corrections and settings
  FieldLink                                      a robot's field reading registered to an entity
  DetectionModel                                 fitted chance that a later look finds an entity again
  LayerScene -> LayerSample <- Entity            what a satellite pass, aerial photograph or lidar survey
                                                 measured over an entity: a record, not a factor
  ImageryCheck                                   what the basemap provider serves now where a capture was taken
  Zone                                           a named area whose fused map is kept drawn

Each entity has two variables: ``c<id>`` (category, taxonomy-sized) and
``x<id>`` (exists, [absent, present]). Factors store their raw log table;
time decay is applied when inference runs, so a belief can be recomputed
for any past instant from the factors valid then.

Two clocks. World time is when the ground was as the evidence shows it: a capture's
``observed_at`` (its imagery's acquisition date when known, else when the view was taken),
copied to its detections' and factors' ``observed_at`` and to entities' ``first_seen`` /
``last_seen``. Record time is when a row was written or withdrawn: ``captured_at`` (the
view), ``recorded_at``, ``superseded_at``, and a belief snapshot's ``at``.

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
    # What the pixels showed. ``captured_at`` is when the view was taken; ``observed_at`` is when
    # the ground looked like that (the middle of the imagery's acquisition window) and dates the
    # capture's evidence. Null until the imagery date is known: the evidence is then dated captured_at.
    imagery_source = models.CharField(max_length=120, blank=True, default='')  # e.g. 'bing:Aerial'
    imagery_start = models.DateTimeField(null=True, blank=True)
    imagery_end = models.DateTimeField(null=True, blank=True)
    imagery = models.JSONField(default=dict, blank=True)  # layers drawn, zoom asked, how the dates were found
    observed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'sg_capture'
        indexes = [models.Index(fields=['-captured_at'], name='sg_capture_time_idx')]

    @property
    def world_time(self):
        """When the ground was as this capture shows it."""
        return self.observed_at or self.captured_at


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
    # why it is not evidence: 'frame' (covers most of the view), 'fragment' (too few pixels), or ''
    gate = models.CharField(max_length=20, blank=True, default='')

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
        ('field', 'field'),            # c: a day of field readings registered to the entity (see field_evidence)
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


class DetectionModel(models.Model):
    """A fitted P(a later look finds an entity again); one active row per taxonomy.

    ``coefficients`` holds ``intercept``, ``log2_pixels``, ``coarser``, ``finer`` and a
    ``category`` map of offsets (see ``detection_model``). Rows are kept, so a miss factor's
    ``metadata['model']`` always names the fit that weighed it.
    """

    taxonomy = models.CharField(max_length=40)
    version = models.IntegerField()
    fitted_at = models.DateTimeField(auto_now_add=True)
    active = models.BooleanField(default=False)
    coefficients = models.JSONField()
    n_looks = models.IntegerField()
    metrics = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = 'sg_detection_model'
        constraints = [models.UniqueConstraint(fields=['taxonomy', 'version'], name='sg_detmodel_version')]


class FieldLink(models.Model):
    """One field reading registered to the entity under its laser target.

    ``reading_id`` is a ``web.FieldReading`` id, kept as a plain number like user ids. No
    position is copied here: where the robot was stays in the readings table, which only
    signed-in users can query.
    """

    reading_id = models.BigIntegerField(unique=True)
    entity = models.ForeignKey(Entity, on_delete=models.CASCADE, related_name='field_links')
    vehicle_id = models.CharField(max_length=40)
    observed_at = models.DateTimeField()
    weight = models.FloatField()  # share of the target's position uncertainty that falls on the entity
    range_m = models.FloatField(null=True, blank=True)
    usable = models.BooleanField(default=False)  # daylight and an index: it counts as evidence
    signal = models.JSONField(default=dict, blank=True)  # {'nir_red': ..., 'green': ..., 'sun_deg': ...}
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'sg_field_link'
        indexes = [models.Index(fields=['entity', 'observed_at'], name='sg_field_link_entity_idx')]


class LayerScene(models.Model):
    """One look by one remote sensor that entities were sampled from: a satellite pass, an
    aerial photograph, a lidar survey.

    ``observed_at`` is when the sensor looked (the middle of ``window_start`` .. ``window_end``
    for a survey flown over several days). ``sampled_through`` is the highest entity id that
    had been considered when the scene was last sampled, so entities added later are filled in.
    """

    source = models.CharField(max_length=40)    # 'sentinel-2-l2a', 'naip', 'usgs-3dep-lidar'
    item_id = models.CharField(max_length=160)  # the provider's id for the scene
    layer = models.CharField(max_length=24)     # what a sample's value is: 'ndvi', 'height'
    observed_at = models.DateTimeField()
    window_start = models.DateTimeField(null=True, blank=True)
    window_end = models.DateTimeField(null=True, blank=True)
    gsd_m = models.FloatField()
    footprint = gis.PolygonField(srid=4326)
    cloud_cover = models.FloatField(null=True, blank=True)  # percent of the whole scene
    sampled_through = models.BigIntegerField(default=0)
    n_samples = models.IntegerField(default=0)
    metadata = models.JSONField(default=dict, blank=True)   # platform, band order, where the pixels are kept
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'sg_layer_scene'
        constraints = [models.UniqueConstraint(fields=['source', 'item_id'], name='sg_layer_scene_item')]
        indexes = [models.Index(fields=['source', 'observed_at'], name='sg_layer_scene_time_idx')]


class LayerSample(models.Model):
    """What one scene measured over one entity. A record, not evidence: no factor is made of it.

    ``value`` is the layer's quantity over the pixels the entity covers, each weighted by the
    share of its signal that comes from inside the outline. ``purity`` is that share for the
    sample as a whole (1 = only pixels wholly inside), ``clear`` the share of the entity's
    weight on usable pixels (inside the image, not cloud), ``n_pixels`` the weight in pixels,
    and ``bands`` the weighted band values in the order of ``scene.metadata['bands']``.
    """

    entity = models.ForeignKey(Entity, on_delete=models.CASCADE, related_name='layer_samples')
    scene = models.ForeignKey(LayerScene, on_delete=models.CASCADE, related_name='samples')
    value = models.FloatField()
    purity = models.FloatField()
    clear = models.FloatField()
    n_pixels = models.FloatField()
    bands = ArrayField(models.FloatField(), default=list, blank=True)

    class Meta:
        db_table = 'sg_layer_sample'
        constraints = [models.UniqueConstraint(fields=['entity', 'scene'], name='sg_layer_sample_once')]


class ImageryCheck(models.Model):
    """A later look-up of what the basemap provider serves where a capture was taken.

    The look-up is made by a signed-in page, the same way and at the same zoom as when the
    capture was built, and only the dates are sent here. ``newer`` is set when the provider now
    serves imagery acquired after the capture's: the capture's area is due a re-capture.
    """

    capture = models.ForeignKey(Capture, on_delete=models.CASCADE, related_name='imagery_checks')
    checked_at = models.DateTimeField(auto_now_add=True)
    user_id = models.IntegerField(null=True, blank=True)
    source = models.CharField(max_length=120, blank=True, default='')
    start = models.DateTimeField(null=True, blank=True)
    end = models.DateTimeField(null=True, blank=True)
    changed = models.BooleanField(default=False)  # the acquisition window differs from the capture's
    newer = models.BooleanField(default=False)    # and ends later
    detail = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = 'sg_imagery_check'
        indexes = [models.Index(fields=['capture', '-checked_at'], name='sg_imagery_check_idx')]


class Zone(models.Model):
    """A named area whose fused map is kept drawn: a city, a field site.

    ``slug`` is its path under /world-model/zones/ ('az/tempe'). ``area`` selects the entities
    and captures the map is made from; ``source`` says where that outline came from.
    """

    slug = models.CharField(max_length=80, unique=True)
    name = models.CharField(max_length=120)
    taxonomy = models.CharField(max_length=40, default='urban_v1')
    area = gis.MultiPolygonField(srid=4326)
    source = models.CharField(max_length=200, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'sg_zone'
        ordering = ['slug']


class UserPreference(models.Model):
    """Per-user settings: default kernels, SAM 3 prompts, thresholds, layer styling."""

    user_id = models.IntegerField()
    key = models.CharField(max_length=60)
    value = models.JSONField()
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'sg_user_preference'
        constraints = [models.UniqueConstraint(fields=['user_id', 'key'], name='sg_pref_user_key')]
