# CLAUDE.md

Flask Secret Santa app, shipped as a Docker image (`michaelhermannhubler/secret-santa`). No database: all state lives in JSON files under `data/`.

## Commands

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt   # Flask is not installed system-wide
.venv/bin/pybabel compile -d translations                            # required before tests/running: .mo files are gitignored
.venv/bin/python -m unittest discover -s tests                       # run tests (stdlib unittest, no pytest)
FLASK_DEBUG=1 .venv/bin/python app.py                                # dev server on 127.0.0.1:5000 (writes to ./data)
docker build -t secret-santa . && docker run -p 5000:5000 secret-santa  # production: gunicorn, 1 worker
.venv/bin/python assign.py --password <admin> [--skip-email]         # CLI draw (+ email everyone unless --skip-email)
.venv/bin/python assign.py --password <admin> --send-only [--unsent-only | --to EMAIL]  # CLI send without a new draw
```

## Layout

- `app.py`: everything else: routes, JSON persistence helpers, the assignment algorithm (`generate_assignments`) and SMTP (`send_email_notification`).
- `assign.py`: CLI wrapper that imports from `app.py`. Importing `app` creates `data/` relative to the CWD.
- `templates/*.html`: Jinja templates with inline JS that call the JSON endpoints.
- `.github/workflows/docker-build.yml`: runs the test suite, then builds and pushes to Docker Hub on every push to `main`. A failing test blocks the push.

## Data model (`data/`, gitignored, root-owned when created by the container)

- `participants.json`: list of `{name, email, language, likes, dislikes, registered_at}`. `language`, `likes` and `dislikes` are missing for people who registered before those features, so always read them with `.get()`. `likes`/`dislikes` are free-text gift wishes (max `MAX_PREFERENCE_LENGTH` = 500 chars, validated by `parse_gift_preferences`). Emails are lowercased and act as the primary key.
- `assignments.json`: `{giver_email: {giftee_email, assigned_at, email_sent_at?, email_error?}}`. `email_sent_at` is the last *successful* send and survives a later failed resend; `email_error` is set on failure and cleared on success. A new draw resets both.
- `config.json`: SMTP settings, `admin_password` (default `admin123`), and `assignment_exclusions`.

`assignment_exclusions` is a list of **directed** `[giver_email, excluded_giftee_email]` pairs, stored in `config.json` and not in participants. Always pass it through `normalize_exclusion_pairs` (it validates, dedupes and sorts it; `ignore_missing=True` drops pairs for removed participants).

The UI and the API refer to participants by their **list index** (`excluded_indices`) and not by email, so removing a participant shifts every later index. Do not cache indices across a removal.

## Assignment algorithm

`generate_assignments` builds the candidates for each giver (excluding self and that giver's exclusions), shuffles them, then runs augmenting-path bipartite matching (Kuhn's algorithm). The result is a random valid derangement, or it fails with "No valid assignments…". It can produce several short cycles (A↔B), which is intended. Tests make it deterministic with `patch('app.random.shuffle', lambda v: None)`.

## Sending emails

Generating assignments never sends email. All sending goes through `send_assignment_emails(recipients=None, only_unsent=False)` in `app.py`, used by both `/admin/emails/send` and `assign.py`. It raises `EmailSendError` (with an HTTP `status`) when nothing can be sent at all, and otherwise returns one result per attempted email. It saves `assignments.json` after **each** email so an interrupted run keeps accurate status. `only_unsent` skips anyone with an `email_sent_at`.

## Gift wishes

Participants enter `likes`/`dislikes` at registration and edit them on `/my-assignment`. Despite its name, `/participant/exclusions` handles all preferences: exclusions, wishes and language. It validates every field before saving anything, and omitted fields are left unchanged. The giver sees the giftee's **current** wishes via `/check-assignment`; the email contains a snapshot from draw time. Wishes are user input: render them with `textContent` only.

## Translations (Flask-Babel; en, de, nl, en_DE)

- Every user-facing string goes through `_()` / `ngettext()`: in templates, in JSON `message`s in `app.py`, and in the email. Page scripts get their strings from a translated `T` dict rendered into each template with `|tojson`, so add JS strings there and not as literals.
- In templates `%` must be written `%%` (Jinja newstyle gettext always applies `%`-formatting).
- Language order of precedence: `lang` cookie (set by `/language/<code>`), then `Accept-Language`, then `DEFAULT_LANGUAGE` (env, default `en`). Add new languages to `SUPPORTED_LANGUAGES`, and to `BROWSER_LANGUAGES` if browsers may select them.
- `en_DE` is **Denglisch**, a deliberate joke language (half German, half English, with intentional spelling and grammar errors). Don't "fix" its mistakes. It is reachable only via the switcher, never via `Accept-Language`, so real `en-DE` users get English. Locale codes contain `_`; templates convert them to BCP 47 (`en-DE`) for `lang` attributes.
- Each participant stores the UI `language` they registered with. It is updated whenever they successfully load or save preferences on `/my-assignment` (via `/participant/exclusions`). Emails are rendered in that language via `force_locale`. `force_locale` does nothing without an app context, which is why `assign.py` runs `main()` inside `app.app_context()`.
- After changing strings, update the catalogs, translate the new entries (remove `#, fuzzy` flags), then compile:
  ```bash
  .venv/bin/pybabel extract -F babel.cfg --ignore-dirs=".venv tests" -k _ --no-location --sort-output -o translations/messages.pot .
  .venv/bin/pybabel update -i translations/messages.pot -d translations -w 0
  .venv/bin/pybabel compile -d translations
  ```
  `tests/test_i18n.py` fails if a catalog is missing strings, has untranslated or fuzzy entries, or has broken `%(name)s` placeholders.

## Conventions

- JSON endpoints return `{'success': bool, 'message': str, ...}` with a matching HTTP status.
- Admin routes check `session['admin_authenticated']`. `SECRET_KEY` falls back to a random value, so sessions are lost when the app restarts.
- Removing a participant always clears `assignments.json`, which forces a fresh draw.
- Tests redirect the three `*_FILE` module globals to a temp dir in `setUp`. Follow the same pattern and never touch the real `data/`.
- Update the README "API Endpoints" list when you add a route.
