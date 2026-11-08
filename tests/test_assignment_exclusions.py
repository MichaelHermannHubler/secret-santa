import os
import tempfile
import unittest
from unittest.mock import patch

import app as secret_santa


class AssignmentExclusionTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_paths = (
            secret_santa.PARTICIPANTS_FILE,
            secret_santa.ASSIGNMENTS_FILE,
            secret_santa.CONFIG_FILE,
        )
        secret_santa.PARTICIPANTS_FILE = os.path.join(self.temp_dir.name, 'participants.json')
        secret_santa.ASSIGNMENTS_FILE = os.path.join(self.temp_dir.name, 'assignments.json')
        secret_santa.CONFIG_FILE = os.path.join(self.temp_dir.name, 'config.json')
        self.participants = [
            {'name': 'Alice', 'email': 'alice@example.com'},
            {'name': 'Bob', 'email': 'bob@example.com'},
            {'name': 'Carol', 'email': 'carol@example.com'},
            {'name': 'Dave', 'email': 'dave@example.com'},
        ]
        secret_santa.save_participants(self.participants)
        secret_santa.save_config({'admin_password': 'test-password'})
        secret_santa.app.config['TESTING'] = True
        self.client = secret_santa.app.test_client()

    def tearDown(self):
        (
            secret_santa.PARTICIPANTS_FILE,
            secret_santa.ASSIGNMENTS_FILE,
            secret_santa.CONFIG_FILE,
        ) = self.original_paths
        self.temp_dir.cleanup()

    def test_generation_respects_directional_exclusions(self):
        secret_santa.save_participants(self.participants[:3])
        secret_santa.save_config({
            'admin_password': 'test-password',
            'assignment_exclusions': [['alice@example.com', 'bob@example.com']],
        })

        with patch('app.random.shuffle', lambda values: None):
            success, assignments = secret_santa.generate_assignments()

        self.assertTrue(success, assignments)
        self.assertNotEqual(assignments['alice@example.com']['giftee_email'], 'bob@example.com')
        self.assertEqual(assignments['bob@example.com']['giftee_email'], 'alice@example.com')
        self.assertEqual(len({assignment['giftee_email'] for assignment in assignments.values()}), 3)

    def test_generation_fails_when_exclusions_make_assignment_impossible(self):
        secret_santa.save_participants(self.participants[:2])
        secret_santa.save_config({
            'admin_password': 'test-password',
            'assignment_exclusions': [['alice@example.com', 'bob@example.com']],
        })

        success, message = secret_santa.generate_assignments()

        self.assertFalse(success)
        self.assertIn('No valid assignments', message)
        self.assertFalse(os.path.exists(secret_santa.ASSIGNMENTS_FILE))

    def test_participant_preferences_update_without_changing_other_preferences(self):
        secret_santa.save_config({
            'admin_password': 'test-password',
            'assignment_exclusions': [['bob@example.com', 'dave@example.com']],
        })

        response = self.client.post('/participant/exclusions', json={
            'email': 'alice@example.com'
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['excluded_indices'], [])

        response = self.client.post('/participant/exclusions', json={
            'email': 'alice@example.com',
            'excluded_indices': [1, 2],
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['excluded_indices'], [1, 2])
        self.assertEqual(
            secret_santa.load_config()['assignment_exclusions'],
            [
                ['alice@example.com', 'bob@example.com'],
                ['alice@example.com', 'carol@example.com'],
                ['bob@example.com', 'dave@example.com'],
            ]
        )

    def test_participant_cannot_exclude_themselves_or_unregistered_users(self):
        response = self.client.post('/participant/exclusions', json={
            'email': 'alice@example.com',
            'excluded_indices': [0],
        })
        self.assertEqual(response.status_code, 400)

        response = self.client.post('/participant/exclusions', json={
            'email': 'unknown@example.com',
            'excluded_indices': [],
        })
        self.assertEqual(response.status_code, 404)

        self.assertNotIn('assignment_exclusions', secret_santa.load_config())

    def test_registration_saves_exclusions_for_new_participant(self):
        response = self.client.post('/register', data={
            'name': 'Eve',
            'email': 'eve@example.com',
            'excluded_indices': ['0', '2'],
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            secret_santa.load_config()['assignment_exclusions'],
            [
                ['eve@example.com', 'alice@example.com'],
                ['eve@example.com', 'carol@example.com'],
            ]
        )

    def test_registration_rejects_invalid_exclusion_indices(self):
        response = self.client.post('/register', data={
            'name': 'Eve',
            'email': 'eve@example.com',
            'excluded_indices': ['9'],
        })

        self.assertEqual(response.status_code, 400)
        self.assertFalse(any(person['email'] == 'eve@example.com'
                             for person in secret_santa.load_participants()))


if __name__ == '__main__':
    unittest.main()
