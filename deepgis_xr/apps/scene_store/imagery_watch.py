"""Has the basemap moved on since a capture was built?

A capture records the acquisition window of the imagery it showed. The provider replaces
its imagery without notice, so each dated capture is looked up again from time to time. The
look-up needs the provider key the page holds, and that key never leaves the page: a
signed-in page asks here which captures in view are due (``due``), repeats for each the
look-up it made when the capture was built (same points, same zoom), and posts back only
the dates (``record``). A capture whose imagery has been replaced by a later acquisition is
flagged for re-capture (``flags``) until a capture of the newer imagery covers its centre.

Nothing here changes a belief: the stored evidence stays dated by the imagery it came from.
"""

from datetime import timedelta

from django.contrib.gis.geos import Polygon
from django.db.models import Max
from django.utils import timezone

from . import fusion
from .models import Capture, ImageryCheck

RECHECK_DAYS = 7     # a capture is looked up again after this long
MAX_DUE = 6          # look-ups asked of a page at a time
LOOKUP_PREFIX = 'bing:'   # the only provider the page can date


def _dated(captures):
    return captures.filter(imagery_start__isnull=False, imagery_end__isnull=False,
                           imagery_source__startswith=LOOKUP_PREFIX)


def _in(bbox, taxonomy=None):
    caps = Capture.objects.all()
    if bbox is not None:
        caps = caps.filter(footprint__intersects=Polygon.from_bbox(bbox))
    if taxonomy:
        caps = caps.filter(taxonomy=taxonomy)
    return caps


def due(bbox, limit=MAX_DUE):
    """Dated captures meeting ``bbox`` not looked up in the last ``RECHECK_DAYS``, longest-waiting first."""
    cutoff = timezone.now() - timedelta(days=RECHECK_DAYS)
    rows = _dated(_in(bbox)).annotate(last_check=Max('imagery_checks__checked_at')).order_by('captured_at')
    waiting = sorted((c for c in rows if c.last_check is None or c.last_check < cutoff),
                     key=lambda c: (c.last_check is not None, c.last_check or c.captured_at))
    out = []
    for cap in waiting[:limit]:
        ring = [list(p) for p in cap.footprint.coords[0]][:-1]
        if len(ring) != 4 or not cap.image_size:
            continue   # the page repeats the capture's look-up from its four corners and image size
        out.append({'session_id': cap.session_id, 'source': cap.imagery_source, 'corners': ring,
                    'image_size': list(cap.image_size),
                    'start': cap.imagery_start.date().isoformat(), 'end': cap.imagery_end.date().isoformat()})
    return out


def record(cap, raw, user_id=None):
    """Store one look-up for a capture from the page's imagery record. Returns the check, or
    None when the record is of other imagery than the capture's or carries no usable dates."""
    rec = fusion.imagery_record(raw, timezone.now())
    if rec['source'] != cap.imagery_source or rec['start'] is None or cap.imagery_start is None:
        return None
    changed = (rec['start'], rec['end']) != (cap.imagery_start, cap.imagery_end)
    return ImageryCheck.objects.create(
        capture=cap, user_id=user_id, source=rec['source'], start=rec['start'], end=rec['end'],
        changed=changed, newer=changed and rec['end'] > cap.imagery_end, detail=rec['detail'])


def flags(bbox=None, taxonomy=None):
    """Captures whose imagery the provider has since replaced with a later acquisition, and
    whose centre no capture of imagery that new covers yet."""
    newest = {}
    checks = ImageryCheck.objects.filter(capture__in=_in(bbox, taxonomy)).select_related('capture') \
        .order_by('capture_id', '-checked_at')
    for chk in checks:
        newest.setdefault(chk.capture_id, chk)
    out = []
    for chk in newest.values():
        cap = chk.capture
        if not chk.newer:
            continue
        centre = cap.footprint.centroid
        if Capture.objects.filter(taxonomy=cap.taxonomy, footprint__intersects=centre,
                                  imagery_start__gte=chk.start).exclude(id=cap.id).exists():
            continue
        out.append({'session_id': cap.session_id, 'centre': [round(centre.x, 6), round(centre.y, 6)],
                    'source': cap.imagery_source,
                    'stored': {'start': cap.imagery_start.date().isoformat(), 'end': cap.imagery_end.date().isoformat()},
                    'now': {'start': chk.start.date().isoformat(), 'end': chk.end.date().isoformat()},
                    'checked_at': chk.checked_at.isoformat()})
    return sorted(out, key=lambda f: f['session_id'])


def summary(taxonomy=None):
    """How current the basemap look-ups are, and which captures are due a re-capture."""
    dated = _dated(_in(None, taxonomy)).annotate(last_check=Max('imagery_checks__checked_at'))
    cutoff = timezone.now() - timedelta(days=RECHECK_DAYS)
    last = [c.last_check for c in dated]
    flagged = flags(None, taxonomy)
    return {
        'n_dated_captures': len(last),
        'n_never_checked': sum(1 for t in last if t is None),
        'n_checked_recently': sum(1 for t in last if t is not None and t >= cutoff),
        'recheck_days': RECHECK_DAYS,
        'last_check': max((t.isoformat() for t in last if t is not None), default=None),
        'n_to_recapture': len(flagged),
        'to_recapture': flagged[:50],
    }
