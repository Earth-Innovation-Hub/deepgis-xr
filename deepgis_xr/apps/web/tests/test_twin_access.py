from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import Client, TestCase

from deepgis_xr.apps.web.views.twin_access import TWIN_PILOTS_GROUP

URL = "/label/api/twin-access/"


class TwinAccessTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.member = User.objects.create_user(username="pilot", password="pw", phone_number="+12015550101")
        self.member.groups.add(Group.objects.create(name=TWIN_PILOTS_GROUP))
        self.other = User.objects.create_user(username="visitor", password="pw", phone_number="+12015550102")

    def test_signed_out_is_401(self):
        self.assertEqual(self.client.get(URL).status_code, 401)

    def test_signed_in_outside_group_is_403(self):
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(URL).status_code, 403)

    def test_member_is_204_for_any_method(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.member)
        self.assertEqual(client.get(URL).status_code, 204)
        self.assertEqual(client.post(URL).status_code, 204)
