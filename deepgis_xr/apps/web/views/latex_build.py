"""Superuser request to build a manuscript on the lab TeX service.

The service address and bearer token live only in the environment
(DEEPGIS_LATEX_BUILD_URL, DEEPGIS_LATEX_BUILD_TOKEN). When either is
empty this view refuses. It never accepts a shell command: it sends a
tar of a manuscript that is already in this tree, or a tar the
superuser uploaded, and a relative path of the main .tex file.
"""

from __future__ import annotations

import io
import re
import tarfile
import urllib.error
import urllib.request
from pathlib import Path

from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.views.decorators.http import require_POST

NAME_RE = re.compile(r'^[a-z0-9][a-z0-9-]{0,40}$')
MAIN_RE = re.compile(
    r'^(?:[A-Za-z0-9][A-Za-z0-9_-]{0,40}/){0,6}'
    r'[A-Za-z0-9][A-Za-z0-9_.-]{0,80}\.tex$'
)
MAX_BYTES = 25 * 1024 * 1024


def _configured():
    url = getattr(settings, 'DEEPGIS_LATEX_BUILD_URL', '') or ''
    token = getattr(settings, 'DEEPGIS_LATEX_BUILD_TOKEN', '') or ''
    return url.strip(), token.strip()


def _tar_tree(root: Path, extras: list[tuple[Path, str]]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode='w:gz') as tf:
        for path in root.rglob('*'):
            if not path.is_file() or path.is_symlink():
                continue
            if any(part.startswith('.') for part in path.relative_to(root).parts):
                continue
            tf.add(path, arcname=str(path.relative_to(root.parent.parent)).replace('\\', '/'))
        for path, arc in extras:
            if path.is_file() and not path.is_symlink():
                tf.add(path, arcname=arc)
    return buf.getvalue()


def _manuscript_tar(name: str, main: str) -> tuple[bytes, str] | JsonResponse:
    if not NAME_RE.fullmatch(name):
        return JsonResponse({'error': 'Unknown manuscript.'}, status=400)
    root = Path(settings.BASE_DIR) / 'manuscripts' / name
    if not root.is_dir():
        return JsonResponse({'error': 'That manuscript is not in this tree.'}, status=404)
    if not main:
        texes = sorted(p for p in root.glob('*.tex') if p.is_file())
        if len(texes) != 1:
            return JsonResponse({'error': 'Say which .tex file to build.'}, status=400)
        main = f'manuscripts/{name}/{texes[0].name}'
    if not MAIN_RE.fullmatch(main) or not main.startswith(f'manuscripts/{name}/'):
        return JsonResponse({'error': 'main must stay inside the manuscript.'}, status=400)
    if not (Path(settings.BASE_DIR) / main).is_file():
        return JsonResponse({'error': 'main file is missing.'}, status=404)
    extras = []
    images = Path(settings.BASE_DIR) / 'docs' / 'images'
    if images.is_dir():
        for path in images.rglob('*'):
            if path.is_file() and not path.is_symlink() and path.stat().st_size < 8_000_000:
                extras.append((path, str(path.relative_to(settings.BASE_DIR)).replace('\\', '/')))
    blob = _tar_tree(root, extras)
    if len(blob) > MAX_BYTES:
        return JsonResponse({'error': 'The manuscript tree is larger than 25 MB.'}, status=413)
    return blob, main


@require_POST
def manuscript_build(request):
    """POST /label/api/manuscripts/build/ — superusers only.

    JSON ``{"manuscript": "deepgis-techreport", "main": "..."}`` builds a
    tree already in the repository. A multipart body with ``archive``
    (a .tar.gz) and ``main`` builds an uploaded tree instead.
    """
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'login_required', 'login_url': '/label/admin/login/'}, status=401)
    if not request.user.is_superuser:
        return JsonResponse({'error': 'Manuscript builds are for superusers.'}, status=403)
    url, token = _configured()
    if not url or not token:
        return JsonResponse({'error': 'LaTeX build is not configured on this server.'}, status=503)

    upload = request.FILES.get('archive') if request.FILES else None
    if upload is not None:
        main = (request.POST.get('main') or '').strip()
        if not MAIN_RE.fullmatch(main):
            return JsonResponse({'error': 'main must be a relative .tex path.'}, status=400)
        blob = upload.read(MAX_BYTES + 1)
        if len(blob) > MAX_BYTES:
            return JsonResponse({'error': 'The archive is larger than 25 MB.'}, status=413)
    else:
        try:
            import json
            data = json.loads(request.body or b'{}')
        except ValueError:
            return JsonResponse({'error': 'Invalid JSON.'}, status=400)
        if not isinstance(data, dict):
            return JsonResponse({'error': 'Invalid JSON.'}, status=400)
        packed = _manuscript_tar(str(data.get('manuscript') or ''), str(data.get('main') or ''))
        if isinstance(packed, JsonResponse):
            return packed
        blob, main = packed

    req = urllib.request.Request(
        url.rstrip('/') + '/v1/build',
        data=blob,
        method='POST',
        headers={
            'Authorization': 'Bearer ' + token,
            'Content-Type': 'application/gzip',
            'X-Latex-Main': main,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=200) as resp:
            pdf = resp.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read(4000).decode('utf-8', 'replace')
        return JsonResponse({'error': 'The TeX build failed.', 'detail': detail}, status=exc.code)
    except (urllib.error.URLError, TimeoutError, OSError):
        return JsonResponse({'error': 'The TeX build service is unreachable.'}, status=502)
    stem = Path(main).stem
    response = HttpResponse(pdf, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{stem}.pdf"'
    return response
