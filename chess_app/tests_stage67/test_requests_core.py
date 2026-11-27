import unittest
from recognition_request import build_request, validate_request


class RequestTests(unittest.TestCase):
    def test_explicit_profile_rectangle_and_orientation(self):
        request = build_request('image ü.png', request_id=12, white_bottom=False,
                                profile_path='profile ü/profile.json', board_rect=(10, 20, 512, 512))
        self.assertEqual(request['profile_path'], 'profile ü/profile.json')
        self.assertEqual(request['board_rect'], [10, 20, 512, 512])
        self.assertFalse(request['white_bottom'])

    def test_legacy_request_has_no_new_optional_arguments(self):
        request = build_request('image.png', request_id=1)
        self.assertNotIn('profile_path', request)
        self.assertNotIn('board_rect', request)

    def test_malformed_options_rejected_before_process_start(self):
        good = build_request('image.png', request_id=1)
        for changes in (dict(request_id=True), dict(white_bottom='black'), dict(profile_path=''),
                        dict(board_rect=[-1, 0, 512, 512]), dict(board_rect=[0, 0, 0, 512]),
                        dict(board_rect=[0, False, 512, 512]), dict(board_rect=[0, 0, 512])):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_request(dict(good, **changes))
