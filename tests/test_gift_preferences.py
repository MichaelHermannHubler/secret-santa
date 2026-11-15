import os
import tempfile
import unittest
from email import message_from_string
from unittest.mock import patch

import app as secret_santa


class GiftPreferenceTests(unittest.TestCase):
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
        secret_santa.save_participants([
            {'name': 'Alice', 'email': 'alice@example.com', 'language': 'en',
             'likes': 'Board games', 'dislikes': 'Socks'},
            {'name': 'Bob', 'email': 'bob@example.com', 'language': 'de'},  # registered before this feature
        ])
        secret_santa.save_config({
            'admin_password': 'test-password',
            'email': 'santa@example.com',
            'password': 'smtp-password',
            'smtp_server': 'smtp.example.com',
            'smtp_port': 587,
        })
        secret_santa.app.config['TESTING'] = True
        self.client = secret_santa.app.test_client()

    def tearDown(self):
        (
            secret_santa.PARTICIPANTS_FILE,
            secret_santa.ASSIGNMENTS_FILE,
            secret_santa.CONFIG_FILE,
        ) = self.original_paths
        self.temp_dir.cleanup()

    def participant(self, email):
        return next(p for p in secret_santa.load_participants() if p['email'] == email)

    # Registration

    def test_registration_stores_stripped_wishes(self):
        response = self.client.post('/register', data={
            'name': 'Carol', 'email': 'carol@example.com',
            'likes': '  Tea\nBooks  ', 'dislikes': '',
        })
        self.assertEqual(response.status_code, 200)
        carol = self.participant('carol@example.com')
        self.assertEqual(carol['likes'], 'Tea\nBooks')
        self.assertEqual(carol['dislikes'], '')

    def test_registration_without_wishes_still_works(self):
        response = self.client.post('/register', data={'name': 'Carol', 'email': 'carol@example.com'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.participant('carol@example.com')['likes'], '')

    def test_registration_rejects_too_long_wishes(self):
        response = self.client.post('/register', data={
            'name': 'Carol', 'email': 'carol@example.com',
            'likes': 'x' * (secret_santa.MAX_PREFERENCE_LENGTH + 1),
        })
        self.assertEqual(response.status_code, 400)
        self.assertIn('500', response.json['message'])
        self.assertEqual(len(secret_santa.load_participants()), 2)

    # Updating on the My Assignment page

    def test_loading_preferences_returns_wishes(self):
        response = self.client.post('/participant/exclusions', json={'email': 'alice@example.com'})
        self.assertEqual(response.json['likes'], 'Board games')
        self.assertEqual(response.json['dislikes'], 'Socks')

        response = self.client.post('/participant/exclusions', json={'email': 'bob@example.com'})
        self.assertEqual((response.json['likes'], response.json['dislikes']), ('', ''))

    def test_saving_updates_only_the_given_fields(self):
        response = self.client.post('/participant/exclusions', json={
            'email': 'alice@example.com', 'likes': 'Puzzles',
        })
        self.assertEqual(response.status_code, 200)
        alice = self.participant('alice@example.com')
        self.assertEqual(alice['likes'], 'Puzzles')
        self.assertEqual(alice['dislikes'], 'Socks')

    def test_saving_empty_text_clears_a_wish(self):
        self.client.post('/participant/exclusions', json={'email': 'alice@example.com', 'dislikes': '  '})
        self.assertEqual(self.participant('alice@example.com')['dislikes'], '')

    def test_invalid_wishes_save_nothing(self):
        for bad in (['a list'], 42, 'x' * (secret_santa.MAX_PREFERENCE_LENGTH + 1)):
            with self.subTest(value=bad):
                response = self.client.post('/participant/exclusions', json={
                    'email': 'alice@example.com', 'excluded_indices': [1], 'likes': bad,
                })
                self.assertEqual(response.status_code, 400)
                # Neither the wishes nor the exclusions in the same request were saved.
                self.assertEqual(self.participant('alice@example.com')['likes'], 'Board games')
                self.assertNotIn('assignment_exclusions', secret_santa.load_config())

    # Showing wishes to the giver

    def test_assignment_lookup_shows_current_giftee_wishes(self):
        secret_santa.save_assignments({
            'bob@example.com': {'giftee_email': 'alice@example.com'},
            'alice@example.com': {'giftee_email': 'bob@example.com'},
        })
        response = self.client.post('/check-assignment', data={'email': 'bob@example.com'})
        self.assertEqual(response.json['giftee_likes'], 'Board games')
        self.assertEqual(response.json['giftee_dislikes'], 'Socks')

        response = self.client.post('/check-assignment', data={'email': 'alice@example.com'})
        self.assertEqual((response.json['giftee_likes'], response.json['giftee_dislikes']), ('', ''))

    def test_wishes_are_rendered_as_text_not_html(self):
        html = self.client.get('/my-assignment').get_data(as_text=True)
        self.assertIn("document.getElementById(id).textContent = text || '';", html)

    # Email

    def send(self, **wishes):
        with secret_santa.app.app_context(), patch('app.smtplib.SMTP') as smtp:
            success, message = secret_santa.send_email_notification(
                'bob@example.com', 'Bob', 'Alice', 'alice@example.com', 'en', **wishes
            )
        self.assertTrue(success, message)
        raw = smtp.return_value.sendmail.call_args.args[2]
        return message_from_string(raw).get_payload()[0].get_payload(decode=True).decode('utf-8')

    def test_email_includes_wishes(self):
        body = self.send(giftee_likes='Board games', giftee_dislikes='Socks')
        self.assertIn('You are gifting to: Alice', body)
        self.assertIn('They like: Board games', body)
        self.assertIn('Please avoid: Socks', body)
        self.assertIn('check the website for the latest version', body)
        self.assertTrue(body.rstrip().endswith('Happy gifting!'))

    def test_email_without_wishes_has_no_wish_section(self):
        body = self.send()
        self.assertNotIn('They like', body)
        self.assertNotIn('Please avoid', body)
        self.assertNotIn('latest version', body)

    def test_generated_emails_carry_giftee_wishes(self):
        with self.client.session_transaction() as session:
            session['admin_authenticated'] = True
        self.assertEqual(self.client.post('/generate-assignments').status_code, 200)
        with patch('app.smtplib.SMTP') as smtp:
            response = self.client.post('/admin/emails/send', json={})
        self.assertEqual(response.status_code, 200)

        bodies = {
            call.args[1]: message_from_string(call.args[2]).get_payload()[0]
                .get_payload(decode=True).decode('utf-8')
            for call in smtp.return_value.sendmail.call_args_list
        }
        # With two people, Bob must draw Alice; his email is German and shows her wishes.
        self.assertIn('Mag gerne: Board games', bodies['bob@example.com'])
        self.assertIn('Bitte lieber nicht: Socks', bodies['bob@example.com'])
        self.assertNotIn('Mag gerne', bodies['alice@example.com'])


if __name__ == '__main__':
    unittest.main()
