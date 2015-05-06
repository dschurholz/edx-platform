"""
Tests for the fake software secure response.
"""

from django.conf import settings
from django.test import TestCase

from mock import patch
from student.tests.factories import UserFactory
from verify_student.models import SoftwareSecurePhotoVerification


class SoftwareSecureFakeViewTest(TestCase):
    """
    Test the fake software secure response.
    """

    def setUp(self):
        super(SoftwareSecureFakeViewTest, self).setUp()
        self.user = UserFactory.create(username="test", password="test")
        self.attempt = SoftwareSecurePhotoVerification.objects.create(user=self.user)
        self.client.login(username="test", password="test")

    @patch.dict(settings.FEATURES, {'ENABLE_SOFTWARE_SECURE_FAKE': True})
    def test_get_method_without_logged_in_user(self):
        """
        Without logging in the user it will return the 302 response.
        """
        self.client.logout()
        response = self.client.get(
            '/verify_student/software-secure-fake-response'
        )

        self.assertEqual(response.status_code, 302)

    @patch.dict(settings.FEATURES, {'ENABLE_SOFTWARE_SECURE_FAKE': True})
    def test_get_method(self):
        """
        Test that GET method of fake software secure view uses the most
        recent attempt for the logged-in user.
        """
        response = self.client.get(
            '/verify_student/software-secure-fake-response'
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn('EdX-ID', response.content)
        self.assertIn('results_callback', response.content)
