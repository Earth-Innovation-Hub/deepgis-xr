"""
SceneGraph collapse runner for deepgis-xr (PR-4).

This mirrors ``distinction_game_fit.py``: Django selects persisted
SceneGraph rows, kernelcal owns inference, and deepgis-xr persists a
timestamped artifact that the admin and CLI can inspect.
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from ..models import SceneGraph
from .distinction_game_fit import (
    DISTINCTION_GAME_FIT_DIR,
    list_fit_artifacts,
    scene_graph_row_to_kc_dict,
)

log = logging.getLogger(__name__)


FUSED_SCENE_GRAPH_DIR = Path('/app/deepgis_results') / 'fused_scene_graphs'


@dataclass(frozen=True)
class CollapseArtifact:
    timestamp: str
    artifact_dir: Path
    payload: Dict[str, Any]
    n_scene_graphs: int
    n_input_nodes: int
    n_fused_nodes: int
    n_edges: int
    contributing_session_ids: List[str]
    converged: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            'timestamp': self.timestamp,
            'artifact_dir': str(self.artifact_dir),
            'n_scene_graphs': int(self.n_scene_graphs),
            'n_input_nodes': int(self.n_input_nodes),
            'n_fused_nodes': int(self.n_fused_nodes),
            'n_edges': int(self.n_edges),
            'contributing_session_ids': list(self.contributing_session_ids),
            'converged': bool(self.converged),
        }


def _now_stamp() -> str:
    return datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')


def _sanitize_for_json(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize_for_json(v) for v in obj]
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj
    return obj


def _safe_label(label: Optional[str]) -> str:
    if not label:
        return ''
    return ''.join(ch if ch.isalnum() or ch in ('-', '_') else '_' for ch in label)[:32]


def _load_fit_payload(fit_artifact_dir: Optional[Path]) -> Dict[str, Any]:
    if fit_artifact_dir is None:
        artifacts = list_fit_artifacts(artifact_root=DISTINCTION_GAME_FIT_DIR, limit=1)
        if not artifacts:
            raise ValueError(
                'no distinction-game fit artifact found; run fit_distinction_game first '
                'or pass fit_artifact_dir explicitly'
            )
        fit_artifact_dir = Path(artifacts[0]['path'])
    fit_json = Path(fit_artifact_dir) / 'fit.json'
    if not fit_json.exists():
        raise ValueError(f'fit artifact has no fit.json: {fit_json}')
    with fit_json.open() as f:
        return json.load(f)


def _q_s_table_from_fit(payload: Mapping[str, Any]):
    from kernelcal.distinction_game import PHX_URBAN_V0
    from kernelcal.distinction_game.q_s import ConfusionMatrix
    from kernelcal.distinction_game.taxonomy import by_name

    out = {}
    for sid, raw in (payload.get('q_s_table') or {}).items():
        tax_name = raw.get('taxonomy') or PHX_URBAN_V0.name
        try:
            taxonomy = by_name(tax_name)
        except KeyError:
            taxonomy = PHX_URBAN_V0
        out[sid] = ConfusionMatrix(
            source_id=sid,
            taxonomy=taxonomy,
            native_labels=tuple(raw.get('native_labels') or []),
            matrix=raw.get('matrix') or [],
            description=raw.get('description') or '',
        )
    if not out:
        raise ValueError('fit artifact q_s_table is empty')
    return out


def _lambdas_from_fit(payload: Mapping[str, Any]) -> Dict[str, float]:
    mix = payload.get('mix') or {}
    sources = mix.get('sources') or []
    lambdas = mix.get('lambdas') or []
    out = {str(s): float(l) for s, l in zip(sources, lambdas) if l is not None}
    if not out:
        raise ValueError('fit artifact mix.lambdas is empty')
    return out


def _fill_anchor_lambdas(
    lambdas: Dict[str, float],
    q_s_table: Mapping[str, Any],
    fit_payload: Mapping[str, Any],
    *,
    default_anchor_lambda: float = 1.0,
) -> Dict[str, float]:
    """Insert λ=1.0 for sources present in ``q_s_table`` but missing
    from the fit's λ vector.

    ``fit_distinction_game`` defaults to
    ``exclude_anchor_sources_from_fit=True`` so anchor sources (typically
    ``osm``) never get a λ written into ``mix.lambdas``. Without this
    fill-in those anchor claims would be silently dropped from the
    fused unary likelihood (see :class:`UnaryPerceptualFactor`: any
    claim whose ``λ == 0`` is skipped). We restore them with a neutral
    weight so that the anchor evidence still informs the fused
    posterior, mirroring its anchor role during fitting.

    The anchor set is read from
    ``fit_payload['used_osm_anchor_sources']`` (the top-level key
    written by :class:`DistinctionGameFit.to_dict`). Any other source
    that has a ``Q_s`` entry but no λ is also backfilled — the only
    way that happens in practice is when a kernel gained a ``Q_s``
    prior but was excluded from the fit.
    """
    if not lambdas:
        return lambdas
    out = dict(lambdas)
    anchor_sources = set(
        str(s) for s in ((fit_payload or {}).get('used_osm_anchor_sources') or [])
    )
    backfilled: List[str] = []
    for sid in q_s_table:
        if sid in out:
            continue
        # Anchor sources are filled with the configured default; any
        # other Q_s-only source is also filled so the operator gets a
        # warning chance instead of silent zero-weighted evidence.
        out[sid] = float(default_anchor_lambda)
        backfilled.append(sid)
    if backfilled:
        anchors_filled = [s for s in backfilled if s in anchor_sources]
        non_anchors_filled = [s for s in backfilled if s not in anchor_sources]
        if anchors_filled:
            log.info(
                "scene_graph_collapse: backfilled \u03bb=%.3f for anchor "
                "sources missing from fit: %s",
                default_anchor_lambda,
                sorted(anchors_filled),
            )
        if non_anchors_filled:
            log.warning(
                "scene_graph_collapse: backfilled \u03bb=%.3f for "
                "non-anchor sources that have Q_s but no fitted \u03bb "
                "(%s); consider re-running fit_distinction_game with "
                "these sources included.",
                default_anchor_lambda,
                sorted(non_anchors_filled),
            )
    return out


def _write_summary(artifact_dir: Path, art: CollapseArtifact, payload: Mapping[str, Any]) -> None:
    diag = payload.get('bp_diagnostics') or {}
    prov = payload.get('provenance') or {}
    lines = [
        'Fused SceneGraph Summary',
        '=' * 60,
        f'Timestamp                : {art.timestamp}',
        f'Artifact directory       : {art.artifact_dir}',
        f'Scene graphs contributing: {art.n_scene_graphs}',
        f'Input nodes              : {art.n_input_nodes}',
        f'Fused nodes              : {art.n_fused_nodes}',
        f'Edges                    : {art.n_edges}',
        f'BP converged             : {art.converged}',
        f'BP iterations            : {diag.get("n_iter")}',
        f'BP max delta             : {diag.get("max_delta")}',
        f'BP MAP energy            : {diag.get("map_energy")}',
        '',
        'Association:',
    ]
    for k, v in (prov.get('association') or {}).items():
        lines.append(f'  {k:24s}  {v}')
    lines.append('')
    lines.append('Contributing scene graphs:')
    for sid in art.contributing_session_ids[:64]:
        lines.append(f'  - {sid}')
    if len(art.contributing_session_ids) > 64:
        lines.append(f'  ... (+{len(art.contributing_session_ids) - 64} more)')
    (artifact_dir / 'fused.summary.txt').write_text('\n'.join(lines) + '\n')


def run_collapse_for_rows(
    rows: Sequence[Any],
    *,
    fit_artifact_dir: Optional[Path] = None,
    iou_thresh: float = 0.5,
    osm_id_match: bool = True,
    centroid_eps: float = 0.0002,
    persistence_alpha: float = 0.95,
    beta_spatial: float = 1.0,
    spatial_degree_cap: Optional[int] = 8,
    bp_max_iter: int = 30,
    bp_damping: float = 0.5,
    bp_tol: float = 1e-4,
    artifact_root: Path = FUSED_SCENE_GRAPH_DIR,
    label: Optional[str] = None,
) -> CollapseArtifact:
    from kernelcal.distinction_game import collapse_scene_graphs

    rows = list(rows)
    if not rows:
        raise ValueError('run_collapse_for_rows requires at least one SceneGraph row')

    fit_payload = _load_fit_payload(fit_artifact_dir)
    q_s_table = _q_s_table_from_fit(fit_payload)
    lambdas = _lambdas_from_fit(fit_payload)
    lambdas = _fill_anchor_lambdas(lambdas, q_s_table, fit_payload)
    taxonomy = next(iter(q_s_table.values())).taxonomy

    sg_dicts = [scene_graph_row_to_kc_dict(r) for r in rows]
    fused = collapse_scene_graphs(
        sg_dicts,
        q_s_table=q_s_table,
        lambdas=lambdas,
        taxonomy=taxonomy,
        beta_spatial=beta_spatial,
        spatial_degree_cap=spatial_degree_cap,
        iou_thresh=iou_thresh,
        osm_id_match=osm_id_match,
        centroid_eps=centroid_eps,
        persistence_alpha=persistence_alpha,
        bp_max_iter=bp_max_iter,
        bp_damping=bp_damping,
        bp_tol=bp_tol,
    )
    payload = _sanitize_for_json(fused.to_dict())

    stamp = _now_stamp()
    suffix = _safe_label(label)
    artifact_dir = artifact_root / (f'{stamp}_{suffix}' if suffix else stamp)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    (artifact_dir / 'fused.json').write_text(
        json.dumps(payload, indent=2, allow_nan=False) + '\n'
    )
    (artifact_dir / 'bp_diagnostics.json').write_text(
        json.dumps(payload.get('bp_diagnostics') or {}, indent=2, allow_nan=False) + '\n'
    )
    (artifact_dir / 'contributing_rows.json').write_text(
        json.dumps([
            {
                'pk': getattr(r, 'pk', None),
                'session_id': r.session_id,
                'created_at': r.created_at.isoformat() if getattr(r, 'created_at', None) else None,
                'n_nodes': len(r.nodes or []),
            }
            for r in rows
        ], indent=2) + '\n'
    )

    prov = payload.get('provenance') or {}
    diag = payload.get('bp_diagnostics') or {}
    art = CollapseArtifact(
        timestamp=stamp,
        artifact_dir=artifact_dir,
        payload=payload,
        n_scene_graphs=int(prov.get('n_scene_graphs', len(rows))),
        n_input_nodes=int(prov.get('n_input_nodes', sum(len(r.nodes or []) for r in rows))),
        n_fused_nodes=len(payload.get('nodes') or []),
        n_edges=len(payload.get('edges') or []),
        contributing_session_ids=[r.session_id for r in rows],
        converged=bool(diag.get('converged', False)),
    )
    _write_summary(artifact_dir, art, payload)
    return art


def list_collapse_artifacts(
    *,
    artifact_root: Path = FUSED_SCENE_GRAPH_DIR,
    limit: Optional[int] = None,
) -> List[Dict[str, Any]]:
    if not artifact_root.exists():
        return []
    out: List[Dict[str, Any]] = []
    for p in sorted(artifact_root.iterdir(), reverse=True):
        if not p.is_dir():
            continue
        fused_json = p / 'fused.json'
        contrib_json = p / 'contributing_rows.json'
        if not fused_json.exists():
            continue
        try:
            with fused_json.open() as f:
                payload = json.load(f)
        except Exception:
            continue
        contributing = []
        if contrib_json.exists():
            try:
                with contrib_json.open() as f:
                    contributing = json.load(f)
            except Exception:
                contributing = []
        prov = payload.get('provenance') or {}
        diag = payload.get('bp_diagnostics') or {}
        out.append({
            'name': p.name,
            'path': str(p),
            'mtime': p.stat().st_mtime,
            'n_scene_graphs': prov.get('n_scene_graphs'),
            'n_input_nodes': prov.get('n_input_nodes'),
            'n_fused_nodes': len(payload.get('nodes') or []),
            'n_edges': len(payload.get('edges') or []),
            'converged': diag.get('converged'),
            'bp_n_iter': diag.get('n_iter'),
            'bp_max_delta': diag.get('max_delta'),
            'contributing_session_ids': [c.get('session_id') for c in contributing],
        })
        if limit is not None and len(out) >= limit:
            break
    return out


def latest_collapse_for_session(
    session_id: str,
    *,
    artifact_root: Path = FUSED_SCENE_GRAPH_DIR,
) -> Optional[Dict[str, Any]]:
    for entry in list_collapse_artifacts(artifact_root=artifact_root):
        if session_id in (entry.get('contributing_session_ids') or []):
            return entry
    return None


def latest_fused_scene_graph_view(request):
    """Return the latest PR-4 fused SceneGraph artifact as JSON.

    Optional query param ``session_id`` restricts lookup to collapse
    artifacts whose contributing-rows index includes that SceneGraph.
    Without it, the newest fused artifact is returned.
    """
    session_id = request.GET.get('session_id')
    entry = (
        latest_collapse_for_session(session_id)
        if session_id else
        (list_collapse_artifacts(limit=1) or [None])[0]
    )
    if not entry:
        return JsonResponse(
            {
                'status': 'not_found',
                'message': 'No fused SceneGraph artifact found. Run collapse_scene_graphs first.',
            },
            status=404,
        )
    fused_json = Path(entry['path']) / 'fused.json'
    try:
        with fused_json.open() as f:
            payload = json.load(f)
    except Exception as exc:
        return JsonResponse(
            {
                'status': 'error',
                'message': f'Failed to read fused SceneGraph artifact: {exc}',
                'artifact': entry,
            },
            status=500,
        )
    return JsonResponse(
        {
            'status': 'success',
            'artifact': entry,
            'fused_scene_graph': payload,
        },
        json_dumps_params={'allow_nan': False},
    )


def _select_scene_graph_rows_from_request(data: Mapping[str, Any]) -> List[SceneGraph]:
    session_ids = data.get('session_ids') or []
    latest = int(data.get('latest') or 1)
    taxonomy = data.get('taxonomy')

    qs = SceneGraph.objects.all()
    if session_ids:
        qs = qs.filter(session_id__in=[str(s) for s in session_ids if s])
    if taxonomy:
        qs = qs.filter(taxonomy_name=str(taxonomy))
    qs = qs.order_by('-created_at')
    if not session_ids:
        qs = qs[:max(1, min(latest, 25))]
    return list(qs)


def _row_preview(row: SceneGraph) -> Dict[str, Any]:
    return {
        'pk': row.pk,
        'session_id': row.session_id,
        'created_at': row.created_at.isoformat() if row.created_at else None,
        'taxonomy_name': row.taxonomy_name,
        'n_nodes': len(row.nodes or []),
        'n_edges': len(row.edges or []),
        'kernels_used': list(row.kernels_used or []),
    }


@require_http_methods(["GET"])
def preview_fused_scene_graph_view(request):
    """Return the rows that a frontend-triggered collapse would consume."""
    data = {
        'latest': request.GET.get('latest') or 1,
        'taxonomy': request.GET.get('taxonomy') or None,
        'session_ids': [
            s for s in (request.GET.get('session_ids') or '').split(',')
            if s
        ],
    }
    rows = _select_scene_graph_rows_from_request(data)
    fit_artifacts = list_fit_artifacts(artifact_root=DISTINCTION_GAME_FIT_DIR, limit=1)
    latest_fit = fit_artifacts[0] if fit_artifacts else None
    return JsonResponse({
        'status': 'success',
        'rows': [_row_preview(r) for r in rows],
        'n_scene_graphs': len(rows),
        'n_input_nodes': sum(len(r.nodes or []) for r in rows),
        'n_input_edges': sum(len(r.edges or []) for r in rows),
        'latest_fit_artifact': latest_fit,
    })


@require_http_methods(["POST"])
@csrf_exempt
def build_fused_scene_graph_view(request):
    """Run PR-4 factor-graph collapse from the frontend and return fused.json."""
    try:
        data = json.loads(request.body or b'{}')
    except Exception as exc:
        return JsonResponse({
            'status': 'error',
            'message': f'Invalid JSON body: {exc}',
        }, status=400)

    rows = _select_scene_graph_rows_from_request(data)
    if not rows:
        return JsonResponse({
            'status': 'error',
            'message': 'No SceneGraph rows matched the requested fuse selection.',
        }, status=404)

    try:
        artifact = run_collapse_for_rows(
            rows,
            fit_artifact_dir=Path(data['fit_artifact']) if data.get('fit_artifact') else None,
            iou_thresh=float(data.get('iou_thresh', 0.5)),
            osm_id_match=bool(data.get('osm_id_match', True)),
            centroid_eps=float(data.get('centroid_eps', 0.0002)),
            persistence_alpha=float(data.get('persistence_alpha', 0.95)),
            beta_spatial=float(data.get('beta_spatial', 1.0)),
            spatial_degree_cap=int(data.get('spatial_degree_cap', 8)),
            bp_max_iter=int(data.get('bp_max_iter', 30)),
            bp_damping=float(data.get('bp_damping', 0.5)),
            bp_tol=float(data.get('bp_tol', 1e-4)),
            label='frontend',
        )
    except Exception as exc:
        return JsonResponse({
            'status': 'error',
            'message': f'Fused SceneGraph build failed: {exc}',
            'rows': [_row_preview(r) for r in rows],
        }, status=500)

    diag = artifact.payload.get('bp_diagnostics') or {}
    return JsonResponse(
        {
            'status': 'success',
            'artifact': artifact.to_dict(),
            'rows': [_row_preview(r) for r in rows],
            'fused_scene_graph': artifact.payload,
            'bp': {
                'converged': bool(diag.get('converged', False)),
                'n_iter': diag.get('n_iter'),
                'max_delta': diag.get('max_delta'),
                'n_variables': diag.get('n_variables'),
                'n_factors': diag.get('n_factors'),
                'n_spatial_edges_used': diag.get('n_spatial_edges_used'),
                'n_spatial_edges_skipped_degree_cap': diag.get(
                    'n_spatial_edges_skipped_degree_cap'
                ),
                'n_unknown_source_claims': diag.get('n_unknown_source_claims', 0),
                'unknown_sources': diag.get('unknown_sources') or [],
            },
        },
        json_dumps_params={'allow_nan': False},
    )


__all__ = [
    'CollapseArtifact',
    'FUSED_SCENE_GRAPH_DIR',
    'run_collapse_for_rows',
    'list_collapse_artifacts',
    'latest_collapse_for_session',
    'latest_fused_scene_graph_view',
    'preview_fused_scene_graph_view',
    'build_fused_scene_graph_view',
]
