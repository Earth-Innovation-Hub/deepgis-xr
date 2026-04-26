"""
Distinction-game fit runner for deepgis-xr (PR-3).

Glue layer between the persisted ``SceneGraph`` rows and the
``kernelcal.distinction_game`` MaxCal Q_s + λ fit. Used both by the
``fit_distinction_game`` management command and by the
``SceneGraphAdmin`` "Run fit on selected" admin action so the two
entry points share a single, tested pipeline.

The fit consumes the JSON payload that the orchestrator already
persists on each row (``viewport``, ``nodes``, ``edges``,
``fusion_metadata``) — kernelcal needs only ``nodes`` for the actual
Q_s/λ refit, but the rest is round-tripped into the artifact for
provenance.

A successful run produces a versioned artifact under::

    /app/deepgis_results/distinction_game_fits/<timestamp>/
    ├── fit.json                 # full kernelcal DistinctionGameFit dict
    ├── fit.summary.txt          # human-readable one-page summary
    └── contributing_rows.json   # session_id ↔ row pk index for replay

so the admin / CLI can show "last fit at X" by listing this directory
without a new DB table.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence


DISTINCTION_GAME_FIT_DIR = Path('/app/deepgis_results') / 'distinction_game_fits'


# ---------------------------------------------------------------------------
# Result bundle
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FitArtifact:
    """A persisted fit result on disk + the in-memory dict.

    The two are kept side-by-side so callers can either consume the
    result inline (admin success message) or hand off the path
    (management command output).
    """

    timestamp: str                # ISO-8601 UTC (filename-friendly)
    artifact_dir: Path
    payload: Dict[str, Any]       # full kernelcal DistinctionGameFit.to_dict()
    n_scene_graphs: int
    n_regions: int
    n_anchored_regions: int
    n_unsupervised_regions: int
    contributing_session_ids: List[str]
    sources: List[str]
    lambdas: Dict[str, float]
    converged: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            'timestamp': self.timestamp,
            'artifact_dir': str(self.artifact_dir),
            'n_scene_graphs': int(self.n_scene_graphs),
            'n_regions': int(self.n_regions),
            'n_anchored_regions': int(self.n_anchored_regions),
            'n_unsupervised_regions': int(self.n_unsupervised_regions),
            'contributing_session_ids': list(self.contributing_session_ids),
            'sources': list(self.sources),
            'lambdas': dict(self.lambdas),
            'converged': bool(self.converged),
        }


# ---------------------------------------------------------------------------
# Row → kernelcal payload conversion
# ---------------------------------------------------------------------------

def scene_graph_row_to_kc_dict(
    row,
    *,
    drop_claim_sources: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """Map a Django ``SceneGraph`` row to the dict shape kernelcal's
    ``fit_distinction_game`` expects.

    ``kernels_queried`` is filled from ``row.kernels_used``, which is
    the orchestrator's canonical "what we asked" list. ``session_id``
    is round-tripped so the kernelcal pipeline can list contributing
    rows without re-querying the DB.

    ``drop_claim_sources`` filters out claims with these ``source_id``s
    from every node before serialisation. Used by :func:`run_fit_for_rows`
    to remove anchor sources (typically ``'osm'``) from the per-region
    observations: anchor sources provide the *truth* for a region but
    must not also appear as a per-region feature, otherwise the EM
    fit collapses onto λ_anchor → 1 by trivial circularity.
    """
    drop_set = set(drop_claim_sources or ())
    nodes_in = list(row.nodes or [])
    if drop_set:
        nodes_out: List[Dict[str, Any]] = []
        for node in nodes_in:
            new_node = dict(node)
            new_node['claims'] = [
                c for c in (node.get('claims') or [])
                if c.get('source_id') not in drop_set
            ]
            nodes_out.append(new_node)
        nodes_in = nodes_out
    return {
        'schema_version': '0.1',
        'session_id': row.session_id,
        'taxonomy': {'name': row.taxonomy_name},
        'viewport': dict(row.viewport or {}),
        'kernels_queried': list(row.kernels_used or []),
        'nodes': nodes_in,
        'edges': list(row.edges or []),
        'fusion_metadata': dict(row.fusion_metadata or {}),
    }


# ---------------------------------------------------------------------------
# Filesystem helpers
# ---------------------------------------------------------------------------

def _now_stamp() -> str:
    return datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')


def _sanitize_for_json(obj: Any) -> Any:
    """Recursively replace non-finite floats with ``None`` so SQLite's
    ``json_valid`` and any downstream RFC-8259 consumer is happy.

    The kernelcal fit can produce ``nan`` if a column had zero mass on
    every native label (degenerate prior + zero data); the Bayesian
    refit guards against this, but defence in depth is cheap.
    """
    if isinstance(obj, dict):
        return {k: _sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize_for_json(v) for v in obj]
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj
    return obj


def _write_summary(artifact_dir: Path, art: FitArtifact, payload: Mapping[str, Any]) -> None:
    """One-page human-readable summary alongside the JSON dump."""
    mix = payload.get('mix') or {}
    qs_table = payload.get('q_s_table') or {}
    lines: List[str] = []
    lines.append('Distinction-Game Fit Summary')
    lines.append('=' * 60)
    lines.append(f'Timestamp                : {art.timestamp}')
    lines.append(f'Artifact directory       : {art.artifact_dir}')
    lines.append(f'Scene graphs contributing: {art.n_scene_graphs}')
    lines.append(f'Regions used             : {art.n_regions} '
                 f'({art.n_anchored_regions} anchored, '
                 f'{art.n_unsupervised_regions} unsupervised)')
    lines.append(f'Converged                : {art.converged}')
    lines.append(f'Method                   : {mix.get("method", "?")}')
    lines.append('')
    lines.append('Lambdas (per source):')
    for src, lam in art.lambdas.items():
        lines.append(f'  {src:24s}  {lam:.4f}')
    history = payload.get('log_likelihood_history') or []
    if history:
        lines.append('')
        lines.append('EM log-likelihood trajectory:')
        for i, ll in enumerate(history):
            lines.append(f'  iter {i+1:3d}: {ll:.4f}')
    if qs_table:
        lines.append('')
        lines.append('Per-source Q_s posterior (diagonal, peak per native label):')
        for sid, qm in qs_table.items():
            mat = qm.get('matrix') or []
            native = qm.get('native_labels') or []
            if not mat or not native:
                continue
            lines.append(f'  {sid}:')
            for i, label in enumerate(native):
                row = mat[i] if i < len(mat) else []
                if not row:
                    continue
                peak_idx = max(range(len(row)), key=lambda j: row[j])
                lines.append(
                    f'    {label:24s}  peak P(c={peak_idx})={row[peak_idx]:.3f}'
                )
    contributing = payload.get('contributing_scene_graph_ids') or []
    if contributing:
        lines.append('')
        lines.append('Contributing scene graphs:')
        for sid in contributing[:64]:
            lines.append(f'  - {sid}')
        if len(contributing) > 64:
            lines.append(f'  … (+{len(contributing) - 64} more)')

    (artifact_dir / 'fit.summary.txt').write_text('\n'.join(lines) + '\n')


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run_fit_for_rows(
    rows: Sequence[Any],
    *,
    # Only kernelcal-canonical names; OSM claims are always stamped
    # ``source_id='osm'`` by ``adapt_osm`` regardless of whether they
    # came from the buildings or roads layer. (The raw ``osm_buildings``
    # / ``osm_roads`` strings only appear in the row's ``kernels_used``
    # provenance list.)
    osm_anchor_sources: Sequence[str] = ('osm',),
    use_consensus_fallback: bool = False,
    exclude_anchor_sources_from_fit: bool = True,
    fit_q_s: bool = True,
    alpha_q_s: float = 10.0,
    max_iter: int = 20,
    tol: float = 1e-5,
    min_score: float = 0.0,
    artifact_root: Path = DISTINCTION_GAME_FIT_DIR,
    label: Optional[str] = None,
) -> FitArtifact:
    """Run the distinction-game EM fit on a list of ``SceneGraph`` rows.

    Parameters
    ----------
    rows
        Iterable of Django ``SceneGraph`` instances (the orchestrator's
        per-tile output rows). At least one row is required.
    osm_anchor_sources
        Source ids whose presence on a node anchors that node's true
        category to the fused argmax. Defaults cover the three OSM
        adapters the orchestrator currently emits.
    use_consensus_fallback
        Treat the fused argmax as the anchor for non-OSM regions too.
        Off by default — biased toward the prior, but useful for
        bootstrapping when no OSM coverage exists for a tile.
    fit_q_s
        Update Q_s each EM iteration. Set False to fit only λ.
    alpha_q_s
        Dirichlet pseudo-count strength for the Q_s update.
    max_iter, tol
        EM outer loop knobs.
    min_score
        Drop claims below this confidence floor before fitting.
    artifact_root
        Where to write the timestamped artifact directory.
    label
        Optional human-readable suffix on the artifact directory name.

    Returns
    -------
    FitArtifact
    """
    # Lazy-imported so the rest of the world_sampler_api package does
    # not pull kernelcal at import time (it's a heavy dep on the web
    # container's startup).
    from kernelcal.distinction_game import (
        default_q_s_table,
        fit_distinction_game,
    )

    rows = list(rows)
    if not rows:
        raise ValueError('run_fit_for_rows requires at least one SceneGraph row')

    # Don't pre-filter at the row level: kernelcal's
    # ``fit_distinction_game`` needs to see anchor-source claims so it
    # can detect anchors per node, and only then strip them from the
    # per-region observations. We just pass the flag through.
    sg_dicts = [scene_graph_row_to_kc_dict(r) for r in rows]

    # Discover sources from the actual claim source_ids (the canonical
    # kernelcal names, set by the adapters when each KernelClaim was
    # built). The row's ``kernels_used`` field carries the *raw*
    # analyser ids ('maskrcnn_rocks', 'sam', 'osm_buildings', ...),
    # which differ from kernelcal's defaults — using them here would
    # silently shrink the fit to whichever raw id happens to match
    # verbatim (typically only 'grounding_dino').
    sources_seen: List[str] = []
    seen_set = set()
    for sg in sg_dicts:
        for node in sg.get('nodes') or []:
            for claim in node.get('claims') or []:
                sid = claim.get('source_id')
                if sid and sid not in seen_set:
                    sources_seen.append(sid)
                    seen_set.add(sid)
    prior_table_full = default_q_s_table()
    sources_for_fit = [s for s in sources_seen if s in prior_table_full]
    if not sources_for_fit:
        raise ValueError(
            'none of the claim source_ids across the supplied rows have a '
            f'default Q_s in kernelcal. Saw: {sorted(seen_set)} — '
            f'expected any of {sorted(prior_table_full.keys())}.'
        )
    prior_table = {s: prior_table_full[s] for s in sources_for_fit}

    fit = fit_distinction_game(
        sg_dicts,
        prior_q_s_table=prior_table,
        sources=sources_for_fit,
        osm_anchor_sources=tuple(osm_anchor_sources),
        use_consensus_fallback=use_consensus_fallback,
        exclude_anchor_sources_from_fit=exclude_anchor_sources_from_fit,
        fit_q_s=fit_q_s,
        alpha_q_s=alpha_q_s,
        max_iter=max_iter,
        tol=tol,
        min_score=min_score,
    )

    payload = _sanitize_for_json(fit.to_dict())

    stamp = _now_stamp()
    if label:
        # Keep the label filesystem-friendly.
        safe_label = ''.join(ch if ch.isalnum() or ch in ('-', '_') else '_'
                             for ch in label)[:32]
        dirname = f'{stamp}_{safe_label}'
    else:
        dirname = stamp
    artifact_dir = artifact_root / dirname
    artifact_dir.mkdir(parents=True, exist_ok=True)

    (artifact_dir / 'fit.json').write_text(
        json.dumps(payload, indent=2, allow_nan=False) + '\n'
    )
    (artifact_dir / 'contributing_rows.json').write_text(
        json.dumps(
            [
                {
                    'pk': getattr(r, 'pk', None),
                    'session_id': r.session_id,
                    'created_at': r.created_at.isoformat() if getattr(r, 'created_at', None) else None,
                    'kernels_used': list(r.kernels_used or []),
                    'n_nodes': len(r.nodes or []),
                }
                for r in rows
            ],
            indent=2,
        ) + '\n'
    )

    lambdas_arr = (payload.get('mix') or {}).get('lambdas') or []
    sources_payload = (payload.get('mix') or {}).get('sources') or sources_for_fit
    lambdas_dict = {
        s: float(l) for s, l in zip(sources_payload, lambdas_arr)
        if l is not None
    }

    art = FitArtifact(
        timestamp=stamp,
        artifact_dir=artifact_dir,
        payload=payload,
        n_scene_graphs=int(payload.get('n_scene_graphs', len(sg_dicts))),
        n_regions=int(payload.get('n_regions', 0)),
        n_anchored_regions=int(payload.get('n_anchored_regions', 0)),
        n_unsupervised_regions=int(payload.get('n_unsupervised_regions', 0)),
        contributing_session_ids=[r.session_id for r in rows],
        sources=list(sources_payload),
        lambdas=lambdas_dict,
        converged=bool(payload.get('converged', False)),
    )
    _write_summary(artifact_dir, art, payload)
    return art


# ---------------------------------------------------------------------------
# Artifact discovery (used by admin column)
# ---------------------------------------------------------------------------

def list_fit_artifacts(
    *,
    artifact_root: Path = DISTINCTION_GAME_FIT_DIR,
    limit: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """List previous fit artifacts on disk, newest first.

    Returns a list of small summary dicts (no payload expansion) so
    callers can quickly populate the admin "Fit history" panel
    without parsing every fit.json.
    """
    if not artifact_root.exists():
        return []
    out: List[Dict[str, Any]] = []
    for p in sorted(artifact_root.iterdir(), reverse=True):
        if not p.is_dir():
            continue
        fit_json = p / 'fit.json'
        contrib_json = p / 'contributing_rows.json'
        if not fit_json.exists():
            continue
        try:
            with fit_json.open() as f:
                payload = json.load(f)
        except Exception:
            continue
        contributing: List[Dict[str, Any]] = []
        if contrib_json.exists():
            try:
                with contrib_json.open() as f:
                    contributing = json.load(f)
            except Exception:
                contributing = []
        out.append({
            'name': p.name,
            'path': str(p),
            'mtime': p.stat().st_mtime,
            'n_scene_graphs': payload.get('n_scene_graphs'),
            'n_regions': payload.get('n_regions'),
            'n_anchored_regions': payload.get('n_anchored_regions'),
            'sources': (payload.get('mix') or {}).get('sources') or [],
            'lambdas': (payload.get('mix') or {}).get('lambdas') or [],
            'converged': payload.get('converged'),
            'contributing_session_ids': [c.get('session_id') for c in contributing],
        })
        if limit is not None and len(out) >= limit:
            break
    return out


def latest_fit_for_session(
    session_id: str,
    *,
    artifact_root: Path = DISTINCTION_GAME_FIT_DIR,
) -> Optional[Dict[str, Any]]:
    """Return the most recent fit artifact that included this session,
    or ``None`` if no such fit exists yet."""
    for entry in list_fit_artifacts(artifact_root=artifact_root):
        if session_id in (entry.get('contributing_session_ids') or []):
            return entry
    return None


__all__ = [
    'DISTINCTION_GAME_FIT_DIR',
    'FitArtifact',
    'scene_graph_row_to_kc_dict',
    'run_fit_for_rows',
    'list_fit_artifacts',
    'latest_fit_for_session',
]
