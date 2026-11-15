import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
from email import message_from_string
from unittest.mock import patch

from babel.messages.pofile import read_po

import app as secret_santa

ROOT = pathlib.Path(__file__).resolve().parent.parent
TRANSLATIONS = ROOT / 'translations'
LANGUAGES = [code for code in secret_santa.SUPPORTED_LANGUAGES if code != 'en']


def setUpModule():
    for lang in LANGUAGES:
        po = TRANSLATIONS / lang / 'LC_MESSAGES' / 'messages.po'
        mo = po.with_suffix('.mo')
        if not mo.exists() or mo.stat().st_mtime < po.stat().st_mtime:
            raise RuntimeError(
                f'{mo.relative_to(ROOT)} is missing or stale. '
                'Run: pybabel compile -d translations'
            )


class I18nTestCase(unittest.TestCase):
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
            {'name': 'Anna', 'email': 'anna@example.com', 'language': 'de'},
            {'name': 'Bram', 'email': 'bram@example.com', 'language': 'nl'},
            {'name': 'Cleo', 'email': 'cleo@example.com'},  # registered before i18n
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


class LanguageSelectionTests(I18nTestCase):
    def test_defaults_to_english(self):
        html = self.client.get('/').get_data(as_text=True)
        self.assertIn('<html lang="en">', html)
        self.assertIn('Register for Secret Santa', html)

    def test_uses_browser_language(self):
        html = self.client.get('/', headers={'Accept-Language': 'de-DE,de;q=0.9'}).get_data(as_text=True)
        self.assertIn('<html lang="de">', html)
        self.assertIn('Zum Wichteln anmelden', html)

    def test_cookie_overrides_browser_language(self):
        self.client.set_cookie('lang', 'nl')
        html = self.client.get('/', headers={'Accept-Language': 'de'}).get_data(as_text=True)
        self.assertIn('Aanmelden voor Secret Santa', html)

    def test_denglisch_is_never_picked_from_browser_settings(self):
        # Real users with English UI in Germany send en-DE; they must get English.
        html = self.client.get('/', headers={'Accept-Language': 'en-DE,en;q=0.9'}).get_data(as_text=True)
        self.assertIn('<html lang="en">', html)
        self.assertIn('Register for Secret Santa', html)

    def test_denglisch_can_be_chosen_with_the_switcher(self):
        self.client.get('/language/en_DE')
        html = self.client.get('/').get_data(as_text=True)
        self.assertIn('<html lang="en-DE">', html)
        self.assertIn('Make mit by the Wichteln', html)

    def test_switcher_sets_cookie_and_returns_to_page(self):
        response = self.client.get('/language/nl?next=/admin')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers['Location'], '/admin')
        self.assertEqual(self.client.get_cookie('lang').value, 'nl')
        self.assertIn('Beheerpaneel', self.client.get('/admin').get_data(as_text=True))

    def test_switcher_rejects_external_redirects_and_unknown_languages(self):
        for target in ('//evil.example', 'https://evil.example', '/\\evil.example'):
            with self.subTest(target=target):
                response = self.client.get('/language/de', query_string={'next': target})
                self.assertEqual(response.headers['Location'], '/')

        self.client.delete_cookie('lang')
        self.client.get('/language/xx')
        self.assertIsNone(self.client.get_cookie('lang'))

    def test_api_messages_are_translated(self):
        response = self.client.post(
            '/register',
            data={'name': 'Anna', 'email': 'anna@example.com'},
            headers={'Accept-Language': 'nl'},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json['message'], 'Dit e-mailadres is al aangemeld')

    def test_javascript_strings_are_translated_and_escaped(self):
        html = self.client.get('/my-assignment', headers={'Accept-Language': 'de'}).get_data(as_text=True)
        self.assertIn('"loading": "Einstellungen werden geladen', html)

    def test_registration_stores_language(self):
        self.client.post(
            '/register',
            data={'name': 'Dirk', 'email': 'dirk@example.com'},
            headers={'Accept-Language': 'nl-BE'},
        )
        dirk = next(p for p in secret_santa.load_participants() if p['email'] == 'dirk@example.com')
        self.assertEqual(dirk['language'], 'nl')


class LanguageUpdateTests(I18nTestCase):
    def language_of(self, email):
        return next(p for p in secret_santa.load_participants() if p['email'] == email).get('language')

    def test_loading_preferences_stores_language_for_legacy_participant(self):
        response = self.client.post('/participant/exclusions', json={'email': 'cleo@example.com'},
                                    headers={'Accept-Language': 'de'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.language_of('cleo@example.com'), 'de')

    def test_saving_preferences_updates_changed_language(self):
        self.client.get('/language/en_DE')
        response = self.client.post('/participant/exclusions',
                                    json={'email': 'anna@example.com', 'excluded_indices': [1]})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.language_of('anna@example.com'), 'en_DE')

    def test_failed_requests_do_not_change_language(self):
        response = self.client.post('/participant/exclusions',
                                    json={'email': 'anna@example.com', 'excluded_indices': [0]},
                                    headers={'Accept-Language': 'nl'})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.language_of('anna@example.com'), 'de')

        response = self.client.post('/participant/exclusions', json={'email': 'nobody@example.com'},
                                    headers={'Accept-Language': 'nl'})
        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.language_of('cleo@example.com'), None)


class EmailLanguageTests(I18nTestCase):
    def sent_emails(self, smtp):
        """Map recipient -> (subject, body) from the mocked SMTP connection."""
        emails = {}
        for call in smtp.return_value.sendmail.call_args_list:
            _sender, recipient, raw = call.args
            message = message_from_string(raw)
            body = message.get_payload()[0].get_payload(decode=True).decode('utf-8')
            emails[recipient] = (str(message['Subject']), body)
        return emails

    def test_web_generation_emails_each_participant_in_their_language(self):
        with self.client.session_transaction() as session:
            session['admin_authenticated'] = True

        with patch('app.smtplib.SMTP') as smtp:
            # The admin uses German; recipients must still get their own language.
            response = self.client.post('/generate-assignments', headers={'Accept-Language': 'de'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['message'], 'Zuteilungen für 3 Personen erfolgreich erstellt!')
        emails = self.sent_emails(smtp)
        self.assertIn('Du beschenkst:', emails['anna@example.com'][1])
        self.assertIn('Jij koopt een cadeau voor:', emails['bram@example.com'][1])
        self.assertIn('You are gifting to:', emails['cleo@example.com'][1])
        self.assertEqual(emails['bram@example.com'][0], 'Jouw Secret Santa-lootje!')

    def test_cli_path_emails_in_participant_language(self):
        with secret_santa.app.app_context(), patch('app.smtplib.SMTP') as smtp:
            success, _message = secret_santa.send_email_notification(
                'anna@example.com', 'Anna', 'Bram', 'bram@example.com', 'de'
            )

        self.assertTrue(success)
        subject, body = self.sent_emails(smtp)['anna@example.com']
        self.assertEqual(subject, 'Deine Wichtel-Zuteilung!')
        self.assertIn('Hallo Anna!', body)
        self.assertIn('Du beschenkst: Bram', body)


class CatalogTests(unittest.TestCase):
    def test_catalogs_match_source_and_are_complete(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            pot = pathlib.Path(temp_dir) / 'messages.pot'
            subprocess.run(
                [sys.executable, '-m', 'babel.messages.frontend', 'extract',
                 '-F', 'babel.cfg', '--ignore-dirs=.venv tests', '-k', '_',
                 '-o', str(pot), '.'],
                cwd=ROOT, check=True, capture_output=True,
            )
            with pot.open('rb') as f:
                source_ids = {m.id if isinstance(m.id, str) else m.id[0]
                              for m in read_po(f) if m.id}

        for lang in LANGUAGES:
            with self.subTest(lang=lang):
                po = TRANSLATIONS / lang / 'LC_MESSAGES' / 'messages.po'
                with po.open('rb') as f:
                    catalog = read_po(f, locale=lang)
                catalog_ids = {m.id if isinstance(m.id, str) else m.id[0]
                               for m in catalog if m.id}

                self.assertEqual(source_ids - catalog_ids, set(),
                                 'Strings missing from catalog; see CLAUDE.md for the update command')
                for message in catalog:
                    if not message.id:
                        continue
                    strings = message.string if isinstance(message.string, tuple) else (message.string,)
                    self.assertTrue(all(strings), f'Untranslated: {message.id!r}')
                    self.assertNotIn('fuzzy', message.flags, f'Fuzzy: {message.id!r}')
                    # Catches broken %(name)s placeholders in translations.
                    self.assertEqual(list(message.check(catalog)), [], message.id)


if __name__ == '__main__':
    unittest.main()
