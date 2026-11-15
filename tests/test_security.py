import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent


class SecurityRegressionTests(unittest.TestCase):
    def test_templates_do_not_assign_inner_html(self):
        # Participant names are user input; rendering them via innerHTML
        # allowed stored XSS in the admin panel.
        for template in (ROOT / 'templates').glob('*.html'):
            with self.subTest(template=template.name):
                self.assertNotRegex(template.read_text(), r'\.(inner|outer)HTML\s*=')

    def test_debug_server_not_enabled_unconditionally(self):
        source = (ROOT / 'app.py').read_text()
        self.assertIsNone(re.search(r'debug\s*=\s*True', source))

    def test_docker_image_uses_production_server(self):
        dockerfile = (ROOT / 'Dockerfile').read_text()
        self.assertIn('gunicorn', dockerfile)
        self.assertNotIn('"app.py"', dockerfile)


if __name__ == '__main__':
    unittest.main()
