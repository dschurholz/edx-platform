"""
Test utilities for mobile API tests:

  MobileAPITestCase - Common base class with helper methods and common functionality.
     No tests are implemented in this base class.

  Test Mixins to be included by concrete test classes and provide implementation of common test methods:
     MobileAuthTestMixin - tests for APIs with mobile_view and is_user=False.
     MobileAuthUserTestMixin - tests for APIs with mobile_view and is_user=True.
     MobileCourseAccessTestMixin - tests for APIs with mobile_course_access and verify_enrolled=False.
     MobileEnrolledCourseAccessTestMixin - tests for APIs with mobile_course_access and verify_enrolled=True.
"""
# pylint: disable=no-member
import ddt
from mock import patch

from django.conf import settings
from django.core.urlresolvers import reverse

from rest_framework.test import APITestCase

from courseware.tests.factories import UserFactory
from courseware.tests.test_entrance_exam import (
    answer_entrance_exam_problem,
    create_mock_request,
    add_entrance_exam_milestone,
)
from opaque_keys.edx.keys import CourseKey
from student import auth
from student.models import CourseEnrollment
from util.milestones_helpers import (
    add_prerequisite_course,
    fulfill_course_milestone,
    seed_milestone_relationship_types,
)
from xmodule.modulestore.django import modulestore
from xmodule.modulestore.tests.django_utils import ModuleStoreTestCase
from xmodule.modulestore.tests.factories import CourseFactory, ItemFactory


class MobileAPITestCase(ModuleStoreTestCase, APITestCase):
    """
    Base class for testing Mobile APIs.
    Subclasses are expected to define REVERSE_INFO to be used for django reverse URL, of the form:
       REVERSE_INFO = {'name': <django reverse name>, 'params': [<list of params in the URL>]}
    They may also override any of the methods defined in this class to control the behavior of the TestMixins.
    """
    def setUp(self):
        super(MobileAPITestCase, self).setUp()
        self.course = CourseFactory.create(mobile_available=True, static_asset_path="needed_for_split")
        self.user = UserFactory.create()
        self.password = 'test'
        self.username = self.user.username

        seed_milestone_relationship_types()

    def tearDown(self):
        super(MobileAPITestCase, self).tearDown()
        self.logout()

    def login(self):
        """Login test user."""
        self.client.login(username=self.username, password=self.password)

    def logout(self):
        """Logout test user."""
        self.client.logout()

    def enroll(self, course_id=None):
        """Enroll test user in test course."""
        CourseEnrollment.enroll(self.user, course_id or self.course.id)

    def unenroll(self, course_id=None):
        """Unenroll test user in test course."""
        CourseEnrollment.unenroll(self.user, course_id or self.course.id)

    def login_and_enroll(self, course_id=None):
        """Shortcut for both login and enrollment of the user."""
        self.login()
        self.enroll(course_id)

    def api_response(self, reverse_args=None, expected_response_code=200, **kwargs):
        """
        Helper method for calling endpoint, verifying and returning response.
        If expected_response_code is None, doesn't verify the response' status_code.
        """
        url = self.reverse_url(reverse_args, **kwargs)
        response = self.url_method(url, **kwargs)
        if expected_response_code is not None:
            self.assertEqual(response.status_code, expected_response_code)
        return response

    def reverse_url(self, reverse_args=None, **kwargs):  # pylint: disable=unused-argument
        """Base implementation that returns URL for endpoint that's being tested."""
        reverse_args = reverse_args or {}
        if 'course_id' in self.REVERSE_INFO['params']:
            reverse_args.update({'course_id': unicode(kwargs.get('course_id', self.course.id))})
        if 'username' in self.REVERSE_INFO['params']:
            reverse_args.update({'username': kwargs.get('username', self.user.username)})
        return reverse(self.REVERSE_INFO['name'], kwargs=reverse_args)

    def url_method(self, url, **kwargs):  # pylint: disable=unused-argument
        """Base implementation that returns response from the GET method of the URL."""
        return self.client.get(url)


class MobileAuthTestMixin(object):
    """
    Test Mixin for testing APIs decorated with mobile_view.
    """
    def test_no_auth(self):
        self.logout()
        self.api_response(expected_response_code=401)


class MobileAuthUserTestMixin(MobileAuthTestMixin):
    """
    Test Mixin for testing APIs related to users: mobile_view with is_user=True.
    """
    def test_invalid_user(self):
        self.login_and_enroll()
        self.api_response(expected_response_code=404, username='no_user')

    def test_other_user(self):
        # login and enroll as the test user
        self.login_and_enroll()
        self.logout()

        # login and enroll as another user
        other = UserFactory.create()
        self.client.login(username=other.username, password='test')
        self.enroll()
        self.logout()

        # now login and call the API as the test user
        self.login()
        self.api_response(expected_response_code=404, username=other.username)


class MobileAPIMilestonesMixin(object):
    """
    Tests the Mobile API decorators for milestones.

    The two milestones supported in these tests are entrance exams and
    pre-requisite courses. If either of these milestones are unfulfilled,
    the mobile api will appropriately block content until the milestone is
    fulfilled.
    """
    MILESTONE_MESSAGE = {
        'developer_message':
            'Cannot access content with unfulfilled pre-requisites or unpassed entrance exam.'
    }

    ALLOW_ACCESS_TO_MILESTONE_COURSE = False  # pylint: disable=invalid-name

    def _add_entrance_exam(self):
        """ Sets up entrance exam """
        # Set up the extrance exam
        self.course.entrance_exam_enabled = True

        self.entrance_exam = ItemFactory.create(  # pylint: disable=attribute-defined-outside-init
            parent=self.course,
            category="chapter",
            display_name="Entrance Exam Chapter",
            is_entrance_exam=True,
            in_entrance_exam=True
        )
        self.problem_1 = ItemFactory.create(  # pylint: disable=attribute-defined-outside-init
            parent=self.entrance_exam,
            category='problem',
            display_name="The Only Exam Problem",
            graded=True,
            in_entrance_exam=True
        )

        add_entrance_exam_milestone(self.course, self.entrance_exam)

        self.course.entrance_exam_minimum_score_pct = 0.50
        self.course.entrance_exam_id = unicode(self.entrance_exam.location)
        modulestore().update_item(self.course, self.user.id)

    def _add_prerequisite_course(self):
        """ Helper method to set up the prerequisite course """
        self.prereq_course = CourseFactory.create()  # pylint: disable=attribute-defined-outside-init
        add_prerequisite_course(self.course.id, self.prereq_course.id)

    def _pass_entrance_exam(self):
        """ Helper function to pass the entrance exam """
        # set up the request for exam functions
        request = create_mock_request(self.user)
        answer_entrance_exam_problem(self.course, request, self.problem_1)

    def verify_response(self):
        """
        Verifies the response depending on ALLOW_ACCESS_TO_MILESTONE_COURSE

        Since different endpoints will have different behaviours towards milestones,
        setting ALLOW_ACCESS_TO_MILESTONE_COURSE (default is False) to True, will
        not return a 204. For example, when getting a list of courses a user is
        enrolled in, although a user may have unfulfilled milestones, the course
        should still show up in the course enrollments list.
        """
        if self.ALLOW_ACCESS_TO_MILESTONE_COURSE:
            self.api_response()
        else:
            response = self.api_response(expected_response_code=204)
            self.assertEqual(response.data, self.MILESTONE_MESSAGE)

    @patch.dict('django.conf.settings.FEATURES', {
        'ENABLE_PREREQUISITE_COURSES': True,
        'MILESTONES_APP': True,
        'ENTRANCE_EXAMS': True
    })
    def test_feature_flags(self):
        """
        Tests when feature flags are set/unset, content is gated appropriately
        """
        self._add_prerequisite_course()
        self._add_entrance_exam()
        self.init_course_access()
        self.verify_response()
        settings.FEATURES["MILESTONES_APP"] = False
        self.api_response()

    @patch.dict('django.conf.settings.FEATURES', {'ENABLE_PREREQUISITE_COURSES': True, 'MILESTONES_APP': True})
    def test_unfulfilled_prerequisite_course(self):
        """ Tests the case for an unfulfilled pre-requisite course """
        self._add_prerequisite_course()

        self.init_course_access()
        self.verify_response()

    @patch.dict('django.conf.settings.FEATURES', {'ENABLE_PREREQUISITE_COURSES': True, 'MILESTONES_APP': True})
    def test_unfulfilled_prerequisite_course_for_staff(self):
        self._add_prerequisite_course()

        self.user.is_staff = True
        self.user.save()
        self.init_course_access()
        self.api_response()

    @patch.dict('django.conf.settings.FEATURES', {'ENABLE_PREREQUISITE_COURSES': True, 'MILESTONES_APP': True})
    def test_fulfilled_prerequisite_course(self):
        """
        Tests the case when a user fulfills existing pre-requisite course
        """
        self._add_prerequisite_course()

        add_prerequisite_course(self.course.id, self.prereq_course.id)
        fulfill_course_milestone(self.prereq_course.id, self.user)
        self.init_course_access()
        self.api_response()

    @patch.dict('django.conf.settings.FEATURES', {'ENTRANCE_EXAMS': True, 'MILESTONES_APP': True})
    def test_unpassed_entrance_exam(self):
        """
        Tests the case where the user has not passed the entrance exam
        """
        self._add_entrance_exam()
        self.init_course_access()
        self.verify_response()

    @patch.dict('django.conf.settings.FEATURES', {'ENTRANCE_EXAMS': True, 'MILESTONES_APP': True})
    def test_unpassed_entrance_exam_for_staff(self):
        self._add_entrance_exam()
        self.user.is_staff = True
        self.user.save()
        self.init_course_access()
        self.api_response()

    @patch.dict('django.conf.settings.FEATURES', {'ENTRANCE_EXAMS': True, 'MILESTONES_APP': True})
    def test_passed_entrance_exam(self):
        """
        Tests access when user has passed the entrance exam
        """
        self._add_entrance_exam()
        self._pass_entrance_exam()
        self.init_course_access()
        self.api_response()


@ddt.ddt
class MobileCourseAccessTestMixin(MobileAPIMilestonesMixin):
    """
    Test Mixin for testing APIs marked with mobile_course_access.
    (Use MobileEnrolledCourseAccessTestMixin when verify_enrolled is set to True.)
    Subclasses are expected to inherit from MobileAPITestCase.
    Subclasses can override verify_success, verify_failure, and init_course_access methods.
    """
    ALLOW_ACCESS_TO_UNRELEASED_COURSE = False  # pylint: disable=invalid-name

    def verify_success(self, response):
        """Base implementation of verifying a successful response."""
        self.assertEqual(response.status_code, 200)

    def verify_failure(self, response):
        """Base implementation of verifying a failed response."""
        self.assertEqual(response.status_code, 404)

    def init_course_access(self, course_id=None):
        """Base implementation of initializing the user for each test."""
        self.login_and_enroll(course_id)

    def test_success(self):
        self.init_course_access()

        response = self.api_response(expected_response_code=None)
        self.verify_success(response)  # allow subclasses to override verification

    def test_course_not_found(self):
        non_existent_course_id = CourseKey.from_string('a/b/c')
        self.init_course_access(course_id=non_existent_course_id)

        response = self.api_response(expected_response_code=None, course_id=non_existent_course_id)
        self.verify_failure(response)  # allow subclasses to override verification

    @patch.dict('django.conf.settings.FEATURES', {'DISABLE_START_DATES': False})
    def test_unreleased_course(self):
        self.init_course_access()

        response = self.api_response(expected_response_code=None)
        if self.ALLOW_ACCESS_TO_UNRELEASED_COURSE:
            self.verify_success(response)
        else:
            self.verify_failure(response)

    # A tuple of Role Types and Boolean values that indicate whether access should be given to that role.
    @ddt.data(
        (auth.CourseBetaTesterRole, True),
        (auth.CourseStaffRole, True),
        (auth.CourseInstructorRole, True),
        (None, False)
    )
    @ddt.unpack
    def test_non_mobile_available(self, role, should_succeed):
        self.init_course_access()

        # set mobile_available to False for the test course
        self.course.mobile_available = False
        self.store.update_item(self.course, self.user.id)

        # set user's role in the course
        if role:
            role(self.course.id).add_users(self.user)

        # call API and verify response
        response = self.api_response(expected_response_code=None)
        if should_succeed:
            self.verify_success(response)
        else:
            self.verify_failure(response)


class MobileEnrolledCourseAccessTestMixin(MobileCourseAccessTestMixin):
    """
    Test Mixin for testing APIs marked with mobile_course_access with verify_enrolled=True.
    """
    def test_unenrolled_user(self):
        self.login()
        self.unenroll()
        response = self.api_response(expected_response_code=None)
        self.verify_failure(response)
