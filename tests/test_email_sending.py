import io
import os
import smtplib
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

import app as secret_santa
import assign


def failing_for(*emails):
    """SMTP sendmail side effect that fails for the given recipients."""
    def sendmail(sender, recipient, message):
        if recipient in emails:
            raise smtplib.SMTPRecipientsRefused({recipient: (550, b'mailbox unavailable')})
    return sendmail


class EmailSendingTestCase(unittest.TestCase):
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
            {'name': 'Alice', 'email': 'alice@example.com'},
            {'name': 'Bob', 'email': 'bob@example.com'},
            {'name': 'Carol', 'email': 'carol@example.com'},
        ])
        secret_santa.save_config({
            'admin_password': 'test-password',
            'email': 'santa@example.com',
            'password': 'smtp-password',
            'smtp_server': 'smtp.example.com',
            'smtp_port': 587,
        })
        secret_santa.save_assignments({
            'alice@example.com': {'giftee_email': 'bob@example.com'},
            'bob@example.com': {'giftee_email': 'carol@example.com'},
            'carol@example.com': {'giftee_email': 'alice@example.com'},
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

    def login(self):
        with self.client.session_transaction() as session:
            session['admin_authenticated'] = True

    def send(self, payload, fail=()):
        with patch('app.smtplib.SMTP') as smtp:
            smtp.return_value.sendmail.side_effect = failing_for(*fail)
            response = self.client.post('/admin/emails/send', json=payload)
        recipients = [call.args[1] for call in smtp.return_value.sendmail.call_args_list]
        return response, recipients

    def status(self, email):
        return secret_santa.load_assignments()[email]


class GenerateDoesNotSendTests(EmailSendingTestCase):
    def test_generating_sends_no_emails(self):
        self.login()
        with patch('app.smtplib.SMTP') as smtp:
            response = self.client.post('/generate-assignments')
        self.assertEqual(response.status_code, 200)
        smtp.assert_not_called()
        for assignment in secret_santa.load_assignments().values():
            self.assertNotIn('email_sent_at', assignment)


class SendEmailsWebTests(EmailSendingTestCase):
    def setUp(self):
        super().setUp()
        self.login()

    def test_send_to_everyone_records_status(self):
        response, recipients = self.send({})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['message'], 'Emails sent: 3, failed: 0')
        self.assertEqual(sorted(recipients), ['alice@example.com', 'bob@example.com', 'carol@example.com'])
        for email in recipients:
            self.assertIn('email_sent_at', self.status(email))

    def test_failures_are_recorded_and_retried_with_only_unsent(self):
        response, _ = self.send({}, fail=('bob@example.com',))
        self.assertEqual(response.json['message'], 'Emails sent: 2, failed: 1')
        self.assertIn('email_error', self.status('bob@example.com'))
        self.assertNotIn('email_sent_at', self.status('bob@example.com'))

        response, recipients = self.send({'only_unsent': True})
        self.assertEqual(recipients, ['bob@example.com'])
        self.assertIn('email_sent_at', self.status('bob@example.com'))
        self.assertNotIn('email_error', self.status('bob@example.com'))

    def test_only_unsent_when_everyone_is_notified_sends_nothing(self):
        self.send({})
        response, recipients = self.send({'only_unsent': True})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(recipients, [])
        self.assertEqual(response.json['message'], 'Everyone has already been notified.')

    def test_resend_to_everyone_sends_again(self):
        self.send({})
        _, recipients = self.send({})
        self.assertEqual(len(recipients), 3)

    def test_send_to_single_person(self):
        response, recipients = self.send({'email': ' Carol@Example.com '})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(recipients, ['carol@example.com'])
        self.assertNotIn('email_sent_at', self.status('alice@example.com'))

    def test_failed_resend_keeps_earlier_successful_send_time(self):
        self.send({'email': 'alice@example.com'})
        sent_at = self.status('alice@example.com')['email_sent_at']

        self.send({'email': 'alice@example.com'}, fail=('alice@example.com',))
        self.assertEqual(self.status('alice@example.com')['email_sent_at'], sent_at)
        self.assertIn('email_error', self.status('alice@example.com'))

    def test_unknown_recipient_is_rejected(self):
        response, recipients = self.send({'email': 'nobody@example.com'})
        self.assertEqual(response.status_code, 404)
        self.assertEqual(recipients, [])

    def test_requires_assignments_and_email_config(self):
        secret_santa.save_assignments({})
        response, _ = self.send({})
        self.assertEqual(response.status_code, 400)
        self.assertIn('Generate assignments first', response.json['message'])

        secret_santa.save_config({'admin_password': 'test-password'})
        response, _ = self.send({})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json['message'], 'Email configuration not set')

    def test_rejects_invalid_payloads(self):
        for payload in ([], {'email': 42}, {'email': '  '}):
            with self.subTest(payload=payload):
                response, recipients = self.send(payload)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(recipients, [])

    def test_admin_page_shows_status_and_send_buttons(self):
        self.send({'email': 'alice@example.com'})
        self.send({'email': 'bob@example.com'}, fail=('bob@example.com',))
        html = self.client.get('/admin').get_data(as_text=True)
        self.assertIn('1 of 3 participants notified', html)
        self.assertIn('Email sent ', html)
        self.assertIn('Email failed: ', html)
        self.assertIn('Email not sent yet', html)
        self.assertEqual(html.count('class="send-one'), 3)


class SendEmailsAuthTests(EmailSendingTestCase):
    def test_requires_admin_login(self):
        response, recipients = self.send({})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(recipients, [])


class CliTests(EmailSendingTestCase):
    def run_cli(self, *args, fail=()):
        output = io.StringIO()
        with patch('sys.argv', ['assign.py', '-p', 'test-password', *args]), \
                patch('app.smtplib.SMTP') as smtp, redirect_stdout(output), \
                secret_santa.app.app_context():
            smtp.return_value.sendmail.side_effect = failing_for(*fail)
            try:
                assign.main()
                code = 0
            except SystemExit as exit_:
                code = exit_.code
        recipients = [call.args[1] for call in smtp.return_value.sendmail.call_args_list]
        return code, recipients, output.getvalue()

    def test_send_only_to_one_person(self):
        code, recipients, _ = self.run_cli('--send-only', '--to', 'bob@example.com')
        self.assertEqual(code, 0)
        self.assertEqual(recipients, ['bob@example.com'])

    def test_send_only_unsent(self):
        self.run_cli('--send-only', fail=('carol@example.com',))
        code, recipients, _ = self.run_cli('--send-only', '--unsent-only')
        self.assertEqual(code, 0)
        self.assertEqual(recipients, ['carol@example.com'])

    def test_exit_code_reports_failures(self):
        code, _, output = self.run_cli('--send-only', fail=('alice@example.com',))
        self.assertEqual(code, 1)
        self.assertIn('2 sent, 1 failed', output)

    def test_invalid_flag_combinations(self):
        with redirect_stderr(io.StringIO()):
            for args in (['--to', 'bob@example.com'], ['--unsent-only'], ['--send-only', '--skip-email']):
                with self.subTest(args=args):
                    code, recipients, _ = self.run_cli(*args)
                    self.assertEqual(code, 2)
                    self.assertEqual(recipients, [])


if __name__ == '__main__':
    unittest.main()
