"""Vectorised inference for the entity factor graph.

``category_bp`` is log-domain loopy sum-product over unary + pairwise
tables, the same update order, normalisation and damping as
``kernelcal.distinction_game.factor_graph.loopy_bp`` but on arrays, so a
10k-factor neighbourhood takes milliseconds instead of minutes.

``existence_marginal`` is the exact forward filter along one entity's
existence chain; the query state is the last node, so no backward pass
is needed.
"""

import math

import numpy as np


def _lse(a, axis):
    m = np.max(a, axis=axis, keepdims=True)
    m = np.where(np.isfinite(m), m, 0.0)
    return np.squeeze(m, axis=axis) + np.log(np.sum(np.exp(a - m), axis=axis))


def _normalise(msg):
    return msg - _lse(msg, axis=-1)[..., None]


def category_bp(unary, a, b, tables, *, max_iter=30, damping=0.5, tol=1e-4):
    """Posteriors (V, K) for unary log tables ``unary`` (V, K) and pairwise
    log tables ``tables`` (E, K, K) between variables ``a[e]`` and ``b[e]``."""
    unary = np.asarray(unary, dtype=float)
    n_vars, k = unary.shape
    a, b = np.asarray(a, dtype=int), np.asarray(b, dtype=int)
    tables = np.asarray(tables, dtype=float).reshape(len(a), k, k)
    if len(a) == 0:
        return np.exp(_normalise(unary)), 0, True, 0.0
    to_a = np.full((len(a), k), -math.log(k))
    to_b = to_a.copy()
    converged, delta, it = False, float('inf'), 0
    for it in range(1, max_iter + 1):
        belief = unary.copy()
        np.add.at(belief, a, to_a)
        np.add.at(belief, b, to_b)
        cav_a = _normalise(belief[a] - to_a)
        cav_b = _normalise(belief[b] - to_b)
        new_b = _normalise(_lse(tables + cav_a[:, :, None], axis=1))
        new_a = _normalise(_lse(tables + cav_b[:, None, :], axis=2))
        new_a = _normalise(damping * to_a + (1 - damping) * new_a)
        new_b = _normalise(damping * to_b + (1 - damping) * new_b)
        delta = float(max(np.abs(new_a - to_a).max(), np.abs(new_b - to_b).max()))
        to_a, to_b = new_a, new_b
        if delta < tol:
            converged = True
            break
    belief = unary.copy()
    np.add.at(belief, a, to_a)
    np.add.at(belief, b, to_b)
    return np.exp(_normalise(belief)), it, converged, delta


def existence_marginal(observations, at, transition):
    """P(present at ``at``) from time-sorted ``(t, log_table[2])`` and
    ``transition(dt) -> log P(next | prev)`` (2, 2)."""
    log_alpha = np.log([0.5, 0.5])
    prev_t = None
    for t, table in observations:
        if prev_t is not None:
            log_alpha = _lse(log_alpha[:, None] + transition(t - prev_t), axis=0)
        log_alpha = _normalise(log_alpha + np.asarray(table, dtype=float))
        prev_t = t
    if prev_t is not None:
        log_alpha = _normalise(_lse(log_alpha[:, None] + transition(at - prev_t), axis=0))
    return float(np.exp(log_alpha[1]))
