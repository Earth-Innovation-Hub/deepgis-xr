"""Chat for https://llm.deepgis.org/.

Same read-only model path as the AI pilot: one MCP call to the resident Gemma,
or to qwen3.8:27b when that name is chosen. Studio is not on this path, so a
chat here does not load another copy of a model onto the GPUs.

The browser on llm.deepgis.org holds the llm_super cookie, not the deepgis.org
session, so this view accepts that cookie. A signed-in superuser on deepgis.org
is accepted too.
"""

import json

import requests
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import signing
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from .llm_access import COOKIE_MAX_AGE, COOKIE_NAME, COOKIE_SALT
from .pilot import _model_catalog, _rate_limited, call_mcp_tool

SYSTEM_PROMPT = (
    "You are the DeepGIS lab assistant. Answer directly. "
    "You are reached through the same models the AI pilot uses."
)
MAX_MESSAGE = 8000
MAX_HISTORY = 12
MAX_TURN = 4000
MAX_IMAGE_CHARS = 4_500_000
CHAT_TIMEOUT = 150


def _superuser_id(request):
    raw = request.COOKIES.get(COOKIE_NAME)
    if raw:
        try:
            data = signing.loads(raw, salt=COOKIE_SALT, max_age=COOKIE_MAX_AGE)
            uid = int(data["u"])
        except (signing.BadSignature, signing.SignatureExpired, KeyError, TypeError, ValueError):
            return None
        User = get_user_model()
        if User.objects.filter(pk=uid, is_active=True, is_superuser=True).exists():
            return uid
        return None
    user = request.user
    if user.is_authenticated and user.is_active and user.is_superuser:
        return user.pk
    return None


def _history(raw):
    if raw is None:
        return []
    if not isinstance(raw, list) or len(raw) > MAX_HISTORY:
        raise ValueError("history must be a short list of turns")
    out = []
    for turn in raw:
        if not isinstance(turn, dict):
            raise ValueError("history must be a short list of turns")
        role = turn.get("role")
        content = turn.get("content")
        if role not in ("user", "assistant") or not isinstance(content, str):
            raise ValueError("history must be a short list of turns")
        text = content.strip()
        if not text:
            continue
        out.append({"role": role, "content": text[:MAX_TURN]})
    return out


def _chosen_model(raw):
    if raw is None:
        return ""
    if not isinstance(raw, str):
        raise ValueError("Unknown model")
    model = raw.strip()
    if not model:
        return ""
    if model not in _model_catalog()["models"]:
        raise ValueError("Unknown model")
    return model


@csrf_exempt
@require_GET
def llm_chat_models(request):
    if _superuser_id(request) is None:
        return JsonResponse({"error": "Sign in as a DeepGIS superuser."}, status=401)
    if not settings.DEEPGIS_PILOT_MCP_TOKEN:
        return JsonResponse({"error": "The lab model is not configured on this server."}, status=503)
    try:
        return JsonResponse(_model_catalog())
    except (requests.RequestException, RuntimeError, ValueError, KeyError) as exc:
        return JsonResponse({"error": f"Model list unavailable: {type(exc).__name__}"}, status=502)


@csrf_exempt
@require_POST
def llm_chat(request):
    uid = _superuser_id(request)
    if uid is None:
        return JsonResponse({"error": "Sign in as a DeepGIS superuser."}, status=401)
    if not settings.DEEPGIS_PILOT_MCP_TOKEN:
        return JsonResponse({"error": "The lab model is not configured on this server."}, status=503)
    try:
        data = json.loads(request.body)
    except ValueError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)
    if not isinstance(data, dict):
        return JsonResponse({"error": "Invalid JSON"}, status=400)
    message = data.get("message", "")
    if not isinstance(message, str):
        return JsonResponse({"error": "Empty message"}, status=400)
    message = message.strip()
    image = data.get("image") or ""
    if not isinstance(image, str) or len(image) > MAX_IMAGE_CHARS:
        return JsonResponse({"error": "Image is too large."}, status=400)
    if not message and not image:
        return JsonResponse({"error": "Empty message"}, status=400)
    if len(message) > MAX_MESSAGE:
        return JsonResponse({"error": "Message is too long."}, status=400)
    try:
        history = _history(data.get("history"))
        model = _chosen_model(data.get("model"))
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    except (requests.RequestException, RuntimeError, KeyError) as exc:
        return JsonResponse({"error": f"Model list unavailable: {type(exc).__name__}"}, status=502)
    if _rate_limited(uid, scope="llm-chat"):
        return JsonResponse({"error": "Too many requests; wait a minute."}, status=429)

    try:
        if image:
            prompt = message or "Describe what you see."
            if history:
                prior = "\n".join(f"{t['role']}: {t['content']}" for t in history[-4:])
                prompt = "Prior conversation:\n" + prior + "\n\n" + prompt
            result = call_mcp_tool("describe_image", {
                "image": image,
                "prompt": prompt,
                "system_prompt": SYSTEM_PROMPT,
                "model": model,
                "temperature": 0.2,
            }, CHAT_TIMEOUT)
        else:
            result = call_mcp_tool("ask_robot_llm", {
                "prompt": message,
                "system_prompt": SYSTEM_PROMPT,
                "model": model,
                "history": history,
                "reasoning_effort": "none",
            }, CHAT_TIMEOUT)
    except (requests.RequestException, RuntimeError, ValueError, KeyError) as exc:
        return JsonResponse({"error": f"The model did not answer: {type(exc).__name__}"}, status=502)
    if not isinstance(result, dict):
        return JsonResponse({"error": "The model did not answer."}, status=502)
    return JsonResponse({
        "response": str(result.get("response") or ""),
        "model": str(result.get("model") or model),
        "duration_sec": result.get("duration_sec"),
    })
