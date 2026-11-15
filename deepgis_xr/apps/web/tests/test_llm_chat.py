import importlib
import json
from unittest import mock

from django.contrib.auth import get_user_model
from django.core import signing
from django.test import Client, TestCase, override_settings

from deepgis_xr.apps.web.views.llm_access import COOKIE_NAME, COOKIE_SALT

chat = importlib.import_module("deepgis_xr.apps.web.views.llm_chat")

URL = "/label/api/llm-chat/"
MODELS = "/label/api/llm-chat/models/"


CATALOG = {"default_model": "gemma-test", "models": ["gemma-test", "qwen3.8:27b"]}


def catalog(name, arguments, timeout, control=False):
    if name == "list_models":
        return {"default_model": "gemma-test", "models": ["gemma-test", "qwen3.8:27b"]}
    if name == "ask_robot_llm":
        return {"response": "from gemma", "model": arguments.get("model") or "gemma-test",
                "duration_sec": 0.4, "echo": arguments.get("prompt")}
    if name == "describe_image":
        return {"response": "a pad", "model": "gemma-test", "duration_sec": 0.5}
    raise AssertionError(name)


@override_settings(DEEPGIS_PILOT_MCP_TOKEN="test-token")
class LlmChatTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_superuser("owner", "o@example.com", "pw")
        self.client = Client()
        self.cookie = signing.dumps({"u": self.user.pk}, salt=COOKIE_SALT)

    def test_cookie_is_required(self):
        response = self.client.post(URL, data=json.dumps({"message": "hi"}),
                                    content_type="application/json")
        self.assertEqual(response.status_code, 401)

    @mock.patch.object(chat, "call_mcp_tool", side_effect=catalog)
    def test_text_uses_the_pilot_model_call(self, mcp):
        self.client.cookies[COOKIE_NAME] = self.cookie
        response = self.client.post(URL, data=json.dumps({
            "message": "hello",
            "history": [{"role": "user", "content": "earlier"}, {"role": "assistant", "content": "yes"}],
        }), content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["response"], "from gemma")
        name, arguments = mcp.call_args.args[0], mcp.call_args.args[1]
        self.assertEqual(name, "ask_robot_llm")
        self.assertEqual(arguments["prompt"], "hello")
        self.assertEqual(arguments["history"][0]["content"], "earlier")
        self.assertEqual(arguments["reasoning_effort"], "none")

    @mock.patch.object(chat, "call_mcp_tool", side_effect=catalog)
    def test_image_uses_describe_image(self, mcp):
        self.client.cookies[COOKIE_NAME] = self.cookie
        response = self.client.post(URL, data=json.dumps({
            "message": "what is this", "image": "abc",
        }), content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["response"], "a pad")
        self.assertEqual(mcp.call_args.args[0], "describe_image")

    @mock.patch.object(chat, "_model_catalog", return_value=CATALOG)
    @mock.patch.object(chat, "call_mcp_tool", side_effect=catalog)
    def test_unknown_model_is_refused(self, _mcp, _catalog):
        self.client.cookies[COOKIE_NAME] = self.cookie
        response = self.client.post(URL, data=json.dumps({
            "message": "hi", "model": "qwen3.5:35b-a3b-q8_0",
        }), content_type="application/json")
        self.assertEqual(response.status_code, 400)

    @mock.patch.object(chat, "_model_catalog", return_value=CATALOG)
    def test_models_lists_the_catalog(self, _catalog):
        self.client.cookies[COOKIE_NAME] = self.cookie
        response = self.client.get(MODELS)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["models"], ["gemma-test", "qwen3.8:27b"])
