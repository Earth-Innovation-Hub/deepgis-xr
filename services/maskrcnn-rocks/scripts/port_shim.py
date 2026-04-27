#!/usr/bin/env python3
"""
port_shim.py — backward-compatibility proxy for the legacy maskrcnn-* ports.

Context
-------

Before consolidation, the deepgis-xr GPU host (192.168.0.232) ran 8
copies of the same `maskrcnn-rocks:latest` image, one per port:

    :5002  rocks       (DEFAULT_MODEL_ID=bishop_hero_e0004)
    :5003  house       (DEFAULT_MODEL_ID=tornado_detector_eureka_aug_mult_e0039)
    :5004  hypolith    (DEFAULT_MODEL_ID=gobabeb_hero_e0011)
    :5005  litter      (DEFAULT_MODEL_ID=litter_dynamics_hero_e0008)
    :5006  roadkill    (DEFAULT_MODEL_ID=roadkill__sarah_e0004)
    :5007  newlife     (DEFAULT_MODEL_ID=new_life_hero_e0008)
    :5008  brent moon  (DEFAULT_MODEL_ID=moon_craters_brent_brent_e0009)
    :5009  harish moon (DEFAULT_MODEL_ID=hanand_stragglers_download.openuas.us_e0099)

After consolidation, ONE container exposes the full registry on a
single port (typically 5002). The deepgis-xr web client now dispatches
through `MASKRCNN_API_URL` and injects the family `model_id` itself
(see analyzers/_maskrcnn_remote.py::resolve_remote_maskrcnn_url), so it
needs nothing further.

But other clients exist — operator `curl` commands, ad-hoc scripts,
external integrations — that still POST to ports 5003-5009 expecting
the per-family default. This shim catches those, injects the right
`model_id` form field, and proxies to the unified container.

Usage
-----

Run one shim process per legacy port. systemd unit (preferred):

    [Unit]
    Description=deepgis-xr maskrcnn port shim (port %i)
    After=network.target maskrcnn-unified.service

    [Service]
    Environment=SHIM_LISTEN_PORT=%i
    Environment=SHIM_UPSTREAM=http://127.0.0.1:5002
    ExecStart=/usr/bin/python3 /opt/deepgis-xr/scripts/port_shim.py
    Restart=on-failure

    [Install]
    WantedBy=multi-user.target

Then `systemctl enable --now port-shim@5003.service` etc.

Or one-off for testing:

    SHIM_LISTEN_PORT=5003 \\
    SHIM_UPSTREAM=http://192.168.0.232:5002 \\
    python3 port_shim.py

Implementation
--------------

Pure Python stdlib + `requests`. No nginx, no lua. The shim binds one
port, accepts multipart/form-data POSTs to /api/predict, and:

  1. Parses the multipart body with `email.parser`.
  2. Looks for an existing `model_id` part. If present, leaves the
     body untouched (caller's choice wins).
  3. If absent, appends a `model_id=<family default>` part keyed off
     the listen port via FAMILY_DEFAULTS below.
  4. Forwards to the unified upstream and streams the response back.

All other paths (/, /health, /api/info, /api/models, /api/result/...)
are pure pass-through.

Long timeouts (180s) match the deepgis-xr web client's request budget
and the Mask R-CNN inference cost on big viewports.
"""

from __future__ import annotations

import logging
import os
import sys
from email import policy
from email.message import Message
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import requests


# Family defaults. Keep in lockstep with the `default_model_id=`
# declarations in deepgis-xr's analyzers/maskrcnn_*.py and with
# `services/maskrcnn-rocks/nginx-port-shims.conf` map block. These
# three places ARE the unified-service migration contract; do not let
# them drift.
FAMILY_DEFAULTS: dict[int, str] = {
    5002: 'bishop_hero_e0004',
    5003: 'tornado_detector_eureka_aug_mult_e0039',
    5004: 'gobabeb_hero_e0011',
    5005: 'litter_dynamics_hero_e0008',
    5006: 'roadkill__sarah_e0004',
    5007: 'new_life_hero_e0008',
    5008: 'moon_craters_brent_brent_e0009',
    5009: 'hanand_stragglers_download.openuas.us_e0099',
}

UPSTREAM_BASE = os.environ.get('SHIM_UPSTREAM', 'http://127.0.0.1:5002').rstrip('/')
LISTEN_PORT = int(os.environ.get('SHIM_LISTEN_PORT', '5003'))
LISTEN_HOST = os.environ.get('SHIM_LISTEN_HOST', '0.0.0.0')
TIMEOUT_S = float(os.environ.get('SHIM_TIMEOUT_S', '180'))

logging.basicConfig(
    level=os.environ.get('SHIM_LOG_LEVEL', 'INFO'),
    format='%(asctime)s %(levelname)s shim:%(message)s',
)
log = logging.getLogger(__name__)


def _inject_model_id(body: bytes, content_type: str, model_id: str) -> tuple[bytes, str]:
    """
    If `body` (multipart/form-data) lacks a ``model_id`` part, append
    one carrying ``model_id``. If a ``model_id`` part is already
    present, return the body unchanged.

    Returns ``(new_body, new_content_type)`` — content_type may pick
    up a different boundary if the body was rewritten.
    """
    headers = (
        f'Content-Type: {content_type}\r\n'
        f'MIME-Version: 1.0\r\n'
        f'\r\n'
    ).encode('latin-1')
    msg: Message = BytesParser(policy=policy.default).parsebytes(headers + body)

    if not msg.is_multipart():
        log.warning('expected multipart but got %s; passing through unchanged', content_type)
        return body, content_type

    for part in msg.iter_parts():
        cd = part.get('Content-Disposition', '')
        if 'name="model_id"' in cd:
            return body, content_type

    # Append a new part. Use the existing boundary so we don't
    # rewrite the whole body — just stitch in one more chunk before
    # the closing boundary.
    boundary = msg.get_boundary()
    if not boundary:
        log.warning('no boundary in multipart; passing through unchanged')
        return body, content_type

    boundary_bytes = boundary.encode('latin-1')
    closing = b'--' + boundary_bytes + b'--'
    if closing not in body:
        log.warning('multipart body has no closing boundary; passing through')
        return body, content_type

    new_part = (
        b'--' + boundary_bytes + b'\r\n'
        b'Content-Disposition: form-data; name="model_id"\r\n\r\n'
        + model_id.encode('latin-1') + b'\r\n'
    )
    new_body = body.replace(closing, new_part + closing, 1)
    log.debug('injected model_id=%s; body grew %d bytes', model_id, len(new_body) - len(body))
    return new_body, content_type


class ShimHandler(BaseHTTPRequestHandler):
    server_version = 'maskrcnn-port-shim/1.0'

    def log_message(self, fmt: str, *args) -> None:
        log.info('%s - ' + fmt, self.address_string(), *args)

    def _proxy(self, *, inject_model_id: bool) -> None:
        method = self.command
        path = self.path
        upstream_url = UPSTREAM_BASE + path

        # Pull body if any. content-length is required for POSTs;
        # chunked uploads are not used by the deepgis-xr client and
        # not supported here.
        length_header = self.headers.get('Content-Length')
        body = b''
        if length_header is not None:
            try:
                length = int(length_header)
            except ValueError:
                length = 0
            if length > 0:
                body = self.rfile.read(length)

        content_type = self.headers.get('Content-Type', '') or ''

        if (
            inject_model_id
            and method == 'POST'
            and content_type.startswith('multipart/form-data')
        ):
            family_default = FAMILY_DEFAULTS.get(LISTEN_PORT)
            if family_default:
                body, content_type = _inject_model_id(body, content_type, family_default)
            else:
                log.warning('no FAMILY_DEFAULTS entry for port %d', LISTEN_PORT)

        # Forward headers, but drop hop-by-hop ones.
        forward_headers = {
            k: v for k, v in self.headers.items()
            if k.lower() not in {
                'host', 'connection', 'content-length', 'transfer-encoding',
            }
        }
        if content_type:
            forward_headers['Content-Type'] = content_type
        forward_headers['X-Legacy-Port'] = str(LISTEN_PORT)

        try:
            upstream = requests.request(
                method,
                upstream_url,
                data=body,
                headers=forward_headers,
                timeout=TIMEOUT_S,
                stream=True,
                allow_redirects=False,
            )
        except requests.exceptions.RequestException as exc:
            log.error('upstream %s failed: %s', upstream_url, exc)
            self.send_error(502, f'upstream error: {exc}')
            return

        self.send_response(upstream.status_code)
        for k, v in upstream.headers.items():
            if k.lower() in {'transfer-encoding', 'connection', 'content-encoding'}:
                continue
            self.send_header(k, v)
        self.end_headers()

        for chunk in upstream.iter_content(chunk_size=64 * 1024):
            if chunk:
                try:
                    self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    log.info('client disconnected mid-response')
                    return

    def do_GET(self) -> None:
        self._proxy(inject_model_id=False)

    def do_POST(self) -> None:
        self._proxy(inject_model_id=self.path == '/api/predict')


def main() -> int:
    log.info(
        'maskrcnn port shim: listening on %s:%d, upstream=%s, family=%s',
        LISTEN_HOST,
        LISTEN_PORT,
        UPSTREAM_BASE,
        FAMILY_DEFAULTS.get(LISTEN_PORT, '<unknown port>'),
    )
    server = ThreadingHTTPServer((LISTEN_HOST, LISTEN_PORT), ShimHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info('shutting down')
    finally:
        server.server_close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
