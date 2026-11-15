# CLAUDE.md

Flask Secret Santa app, shipped as a Docker image (`michaelhermannhubler/secret-santa`). No database: all state lives in JSON files under `data/`.

## Commands

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt   # Flask is not installed system-wide
.venv/bin/python -m unittest discover -s tests                       # run tests (stdlib unittest, no pytest)
FLASK_DEBUG=1 .venv/bin/python app.py                                # dev server on 127.0.0.1:5000 (writes to ./data)
docker build -t secret-santa . && docker run -p 5000:5000 secret-santa  # production: gunicorn, 1 worker
.venv/bin/python assign.py --password <admin> [--skip-email]         # CLI draw
```

## Layout

- `app.py`: everything else: routes, JSON persistence helpers, the assignment algorithm (`generate_assignments`) and SMTP (`send_email_notification`).
- `assign.py`: CLI wrapper that imports from `app.py`. Importing `app` creates `data/` relative to the CWD.
- `templates/*.html`: Jinja templates with inline JS that call the JSON endpoints.
- `.github/workflows/docker-build.yml`: runs the test suite, then builds and pushes to Docker Hub on every push to `main`. A failing test blocks the push.

## Data model (`data/`, gitignored, root-owned when created by the container)

- `participants.json`: list of `{name, email, registered_at}`. Emails are lowercased and act as the primary key.
- `assignments.json`: `{giver_email: {giftee_email, assigned_at}}`.
- `config.json`: SMTP settings, `admin_password` (default `admin123`), and `assignment_exclusions`.

`assignment_exclusions` is a list of **directed** `[giver_email, excluded_giftee_email]` pairs, stored in `config.json` and not in participants. Always pass it through `normalize_exclusion_pairs` (it validates, dedupes and sorts it; `ignore_missing=True` drops pairs for removed participants).

The UI and the API refer to participants by their **list index** (`excluded_indices`) and not by email, so removing a participant shifts every later index. Do not cache indices across a removal.

## Assignment algorithm

`generate_assignments` builds the candidates for each giver (excluding self and that giver's exclusions), shuffles them, then runs augmenting-path bipartite matching (Kuhn's algorithm). The result is a random valid derangement, or it fails with "No valid assignments…". It can produce several short cycles (A↔B), which is intended. Tests make it deterministic with `patch('app.random.shuffle', lambda v: None)`.

## Conventions

- JSON endpoints return `{'success': bool, 'message': str, ...}` with a matching HTTP status.
- Admin routes check `session['admin_authenticated']`. `SECRET_KEY` falls back to a random value, so sessions are lost when the app restarts.
- Removing a participant always clears `assignments.json`, which forces a fresh draw.
- Tests redirect the three `*_FILE` module globals to a temp dir in `setUp`. Follow the same pattern and never touch the real `data/`.
- Update the README "API Endpoints" list when you add a route.
