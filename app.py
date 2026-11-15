from flask import (Flask, render_template, request, jsonify, redirect, url_for,
                   session, has_request_context)
from flask_babel import Babel, force_locale, format_datetime, gettext as _, ngettext
import json
import os
import random
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
import secrets

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', secrets.token_hex(16))

SUPPORTED_LANGUAGES = {
    'en': 'English',
    'de': 'Deutsch',
    'nl': 'Nederlands',
    'en_DE': 'Denglisch',  # joke language: half German, half English, deliberately misspelled
}
# Languages a browser's Accept-Language may select. Denglisch is opt-in via the
# switcher only, so a real "en-DE" browser setting still gets proper English.
BROWSER_LANGUAGES = ['en', 'de', 'nl']
DEFAULT_LANGUAGE = os.environ.get('DEFAULT_LANGUAGE', 'en')
if DEFAULT_LANGUAGE not in BROWSER_LANGUAGES:
    DEFAULT_LANGUAGE = 'en'
LANGUAGE_COOKIE = 'lang'

def get_locale():
    """Pick the UI language: explicit cookie choice, then browser preference."""
    if not has_request_context():
        return DEFAULT_LANGUAGE
    chosen = request.cookies.get(LANGUAGE_COOKIE)
    if chosen in SUPPORTED_LANGUAGES:
        return chosen
    return request.accept_languages.best_match(BROWSER_LANGUAGES) or DEFAULT_LANGUAGE

babel = Babel(app, locale_selector=get_locale)

@app.context_processor
def inject_languages():
    return {
        'current_language': get_locale(),
        'supported_languages': SUPPORTED_LANGUAGES,
        'max_preference_length': MAX_PREFERENCE_LENGTH,
    }

DATA_DIR = 'data'
PARTICIPANTS_FILE = os.path.join(DATA_DIR, 'participants.json')
ASSIGNMENTS_FILE = os.path.join(DATA_DIR, 'assignments.json')
CONFIG_FILE = os.path.join(DATA_DIR, 'config.json')

# Ensure data directory exists
os.makedirs(DATA_DIR, exist_ok=True)

def load_participants():
    """Load participants from JSON file"""
    if os.path.exists(PARTICIPANTS_FILE):
        with open(PARTICIPANTS_FILE, 'r') as f:
            return json.load(f)
    return []

def save_participants(participants):
    """Save participants to JSON file"""
    with open(PARTICIPANTS_FILE, 'w') as f:
        json.dump(participants, f, indent=2)

def load_assignments():
    """Load assignments from JSON file"""
    if os.path.exists(ASSIGNMENTS_FILE):
        with open(ASSIGNMENTS_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_assignments(assignments):
    """Save assignments to JSON file"""
    with open(ASSIGNMENTS_FILE, 'w') as f:
        json.dump(assignments, f, indent=2)

def load_config():
    """Load configuration from JSON file"""
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    return {
        'smtp_server': 'smtp.gmail.com',
        'smtp_port': 587,
        'email': '',
        'password': '',
        'admin_password': 'admin123'  # Default password, should be changed
    }

def save_config(config):
    """Save configuration to JSON file"""
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=2)

def normalize_exclusion_pairs(pairs, participant_emails, ignore_missing=False):
    """Validate and normalize directed assignment exclusions."""
    if not isinstance(pairs, list):
        raise ValueError(_('Assignment exclusions must be a list'))

    participant_emails = set(participant_emails)
    normalized_pairs = set()
    for pair in pairs:
        if (not isinstance(pair, (list, tuple)) or len(pair) != 2 or
                not all(isinstance(email, str) for email in pair)):
            raise ValueError(_('Each assignment exclusion must contain two participant emails'))
        first_email, second_email = pair
        if first_email == second_email:
            raise ValueError(_('A participant cannot be excluded from themselves'))
        if first_email not in participant_emails or second_email not in participant_emails:
            if ignore_missing:
                continue
            raise ValueError(_('Assignment exclusions must refer to registered participants'))
        normalized_pairs.add((first_email, second_email))

    return sorted(normalized_pairs)

MAX_PREFERENCE_LENGTH = 500
PREFERENCE_FIELDS = ('likes', 'dislikes')

def parse_gift_preferences(source):
    """Validate the optional free-text gift wishes ("likes" / "dislikes").

    Only fields present in ``source`` are returned, so callers can do partial
    updates. Values are stripped; an empty string clears the field.
    """
    preferences = {}
    for field in PREFERENCE_FIELDS:
        if field not in source:
            continue
        value = source.get(field)
        if value is None:
            value = ''
        if not isinstance(value, str):
            raise ValueError(_('Gift preferences must be text'))
        value = value.strip()
        if len(value) > MAX_PREFERENCE_LENGTH:
            raise ValueError(_('Gift preferences can be at most %(max)d characters long',
                               max=MAX_PREFERENCE_LENGTH))
        preferences[field] = value
    return preferences

def parse_participant_indices(raw_indices, participant_count, own_index=None):
    """Validate participant indices submitted for one participant's exclusions."""
    if not isinstance(raw_indices, list):
        raise ValueError(_('Excluded participants must be provided as a list'))

    indices = set()
    for raw_index in raw_indices:
        if isinstance(raw_index, bool) or not isinstance(raw_index, (int, str)):
            raise ValueError(_('Invalid excluded participant'))
        try:
            index = int(raw_index)
        except ValueError:
            raise ValueError(_('Invalid excluded participant'))
        if index < 0 or index >= participant_count:
            raise ValueError(_('Invalid excluded participant'))
        if index == own_index:
            raise ValueError(_('You cannot exclude yourself'))
        indices.add(index)
    return sorted(indices)

@app.route('/')
def index():
    """Home page with registration form"""
    participants = load_participants()
    assignments = load_assignments()
    return render_template('index.html', participants=participants, assignments=assignments)

@app.route('/language/<code>')
def set_language(code):
    """Remember the chosen UI language in a cookie and return to the page."""
    target = request.args.get('next', '/')
    # Only allow local paths to avoid an open redirect.
    if not target.startswith('/') or target.startswith('//') or '\\' in target:
        target = '/'
    response = redirect(target)
    if code in SUPPORTED_LANGUAGES:
        response.set_cookie(LANGUAGE_COOKIE, code, max_age=365 * 24 * 3600,
                            samesite='Lax', httponly=True)
    return response

@app.route('/register', methods=['POST'])
def register():
    """Register a new participant"""
    name = request.form.get('name', '').strip()
    email = request.form.get('email', '').strip().lower()
    
    if not name or not email:
        return jsonify({'success': False, 'message': _('Name and email are required')}), 400
    
    # Basic email validation
    if '@' not in email:
        return jsonify({'success': False, 'message': _('Invalid email format')}), 400
    
    participants = load_participants()
    # Check for duplicate email
    if any(p['email'] == email for p in participants):
        return jsonify({'success': False, 'message': _('This email is already registered')}), 400

    try:
        excluded_indices = parse_participant_indices(
            request.form.getlist('excluded_indices'),
            len(participants)
        )
        preferences = parse_gift_preferences(request.form)
    except ValueError as error:
        return jsonify({'success': False, 'message': str(error)}), 400
    
    # Add new participant
    participants.append({
        'name': name,
        'email': email,
        'language': get_locale(),
        'likes': preferences.get('likes', ''),
        'dislikes': preferences.get('dislikes', ''),
        'registered_at': datetime.now().isoformat()
    })

    config = load_config()
    try:
        exclusion_pairs = normalize_exclusion_pairs(
            config.get('assignment_exclusions', []),
            [participant['email'] for participant in participants],
            ignore_missing=True
        )
        exclusion_pairs.extend(
            (email, participants[index]['email'])
            for index in excluded_indices
        )
        config['assignment_exclusions'] = normalize_exclusion_pairs(
            exclusion_pairs,
            [participant['email'] for participant in participants]
        )
    except ValueError as error:
        return jsonify({'success': False, 'message': _('Could not save exclusions: %(error)s', error=error)}), 500

    save_participants(participants)
    save_config(config)
    
    return jsonify({'success': True, 'message': _('Successfully registered!')})

@app.route('/my-assignment')
def my_assignment():
    """Page to view your assignment"""
    participants = load_participants()
    return render_template(
        'my_assignment.html',
        participant_names=[participant['name'] for participant in participants]
    )

@app.route('/participant/exclusions', methods=['POST'])
def manage_participant_exclusions():
    """Read or update a participant's preferences: directed exclusions and gift wishes."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({'success': False, 'message': _('Invalid request')}), 400

    email = data.get('email')
    if not isinstance(email, str) or not email.strip():
        return jsonify({'success': False, 'message': _('A registered email is required')}), 400
    email = email.strip().lower()
    participants = load_participants()
    participant_index = next(
        (index for index, participant in enumerate(participants)
         if participant['email'] == email),
        None
    )
    if participant_index is None:
        return jsonify({'success': False, 'message': _('No participant found for this email')}), 404

    participant = participants[participant_index]
    config = load_config()
    try:
        # Validate everything before saving anything, so a bad field never
        # leaves the exclusions and the wishes half-updated.
        preferences = parse_gift_preferences(data)
        exclusion_pairs = normalize_exclusion_pairs(
            config.get('assignment_exclusions', []),
            [p['email'] for p in participants],
            ignore_missing=True
        )
        if 'excluded_indices' in data:
            excluded_indices = parse_participant_indices(
                data['excluded_indices'],
                len(participants),
                own_index=participant_index
            )
            exclusion_pairs = [
                pair for pair in exclusion_pairs if pair[0] != email
            ]
            exclusion_pairs.extend(
                (email, participants[index]['email'])
                for index in excluded_indices
            )
            config['assignment_exclusions'] = normalize_exclusion_pairs(
                exclusion_pairs,
                [participant['email'] for participant in participants]
            )
            save_config(config)
    except ValueError as error:
        return jsonify({'success': False, 'message': str(error)}), 400

    # Remember the language the participant currently uses for their emails.
    # This lets people who registered before i18n (no stored language) or who
    # changed language later pick it up just by visiting their preferences.
    updated = dict(participant, language=get_locale(), **preferences)
    if updated != participant:
        participants[participant_index] = participant = updated
        save_participants(participants)

    return jsonify({
        'success': True,
        'message': _('Your preferences have been saved.'),
        'participant_index': participant_index,
        'likes': participant.get('likes', ''),
        'dislikes': participant.get('dislikes', ''),
        'excluded_indices': [
            index for index, participant in enumerate(participants)
            if (email, participant['email']) in exclusion_pairs
        ]
    })

@app.route('/check-assignment', methods=['POST'])
def check_assignment():
    """Check assignment by email"""
    email = request.form.get('email', '').strip().lower()
    
    if not email:
        return jsonify({'success': False, 'message': _('Email is required')}), 400
    
    assignments = load_assignments()
    
    if email not in assignments:
        return jsonify({'success': False, 'message': _('No assignment found for this email')}), 404
    
    assignment = assignments[email]
    participants = load_participants()
    giftee = next((p for p in participants if p['email'] == assignment['giftee_email']), None)
    
    if not giftee:
        return jsonify({'success': False, 'message': _('Assignment found but giftee not found')}), 404
    
    return jsonify({
        'success': True,
        'giftee_name': giftee['name'],
        'giftee_email': giftee['email'],
        'giftee_likes': giftee.get('likes', ''),
        'giftee_dislikes': giftee.get('dislikes', '')
    })

@app.route('/admin')
def admin():
    """Admin page for generating assignments"""
    # Check if user is authenticated
    if not session.get('admin_authenticated'):
        return render_template('admin.html', authenticated=False)
    
    participants = load_participants()
    assignments = load_assignments()
    email_status = {}
    for giver_email, assignment in assignments.items():
        sent_at = assignment.get('email_sent_at')
        email_status[giver_email] = {
            'sent_at': format_datetime(datetime.fromisoformat(sent_at), 'short') if sent_at else None,
            'error': assignment.get('email_error'),
        }
    return render_template('admin.html', authenticated=True, participants=participants,
                           assignments=assignments, email_status=email_status)

@app.route('/admin/login', methods=['POST'])
def admin_login():
    """Authenticate admin user"""
    password = request.form.get('password', '').strip()
    config = load_config()
    
    # Verify password
    if password == config.get('admin_password', 'admin123'):
        session['admin_authenticated'] = True
        return jsonify({'success': True, 'message': _('Authentication successful')})
    else:
        return jsonify({'success': False, 'message': _('Invalid password')}), 401

@app.route('/admin/logout', methods=['POST'])
def admin_logout():
    """Logout admin user"""
    session.pop('admin_authenticated', None)
    return jsonify({'success': True, 'message': _('Logged out successfully')})

@app.route('/admin/participants/remove', methods=['POST'])
def remove_participant():
    """Remove a registered participant and reset assignments."""
    if not session.get('admin_authenticated'):
        return jsonify({'success': False, 'message': _('Not authenticated. Please log in first.')}), 401

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({'success': False, 'message': _('Invalid request')}), 400

    email = data.get('email')
    if not isinstance(email, str) or not email.strip():
        return jsonify({'success': False, 'message': _('A participant email is required')}), 400
    email = email.strip().lower()

    participants = load_participants()
    if not any(participant['email'] == email for participant in participants):
        return jsonify({'success': False, 'message': _('Participant not found')}), 404

    remaining_participants = [
        participant for participant in participants if participant['email'] != email
    ]
    config = load_config()
    exclusion_pairs = normalize_exclusion_pairs(
        config.get('assignment_exclusions', []),
        [participant['email'] for participant in participants],
        ignore_missing=True
    )
    config['assignment_exclusions'] = [
        [giver_email, giftee_email]
        for giver_email, giftee_email in exclusion_pairs
        if email not in (giver_email, giftee_email)
    ]

    save_participants(remaining_participants)
    save_config(config)

    # Existing assignments may include the removed participant or no longer fit
    # the current participant list, so require a fresh draw.
    save_assignments({})

    return jsonify({
        'success': True,
        'message': _('Participant removed. Generate assignments again to notify the remaining participants.')
    })

@app.route('/generate-assignments', methods=['POST'])
def generate_assignments_web():
    """Generate assignments via web interface. Emails are sent separately."""
    if not session.get('admin_authenticated'):
        return jsonify({'success': False, 'message': _('Not authenticated. Please log in first.')}), 401

    success, result = generate_assignments()
    if not success:
        return jsonify({'success': False, 'message': result}), 400

    return jsonify({
        'success': True,
        'message': ngettext(
            'Successfully generated assignments for %(num)d participant!',
            'Successfully generated assignments for %(num)d participants!',
            len(result)
        ),
    })

@app.route('/admin/emails/send', methods=['POST'])
def send_emails_web():
    """Send (or resend) assignment emails to everyone, to those not yet notified, or to one person."""
    if not session.get('admin_authenticated'):
        return jsonify({'success': False, 'message': _('Not authenticated. Please log in first.')}), 401

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({'success': False, 'message': _('Invalid request')}), 400

    recipient = data.get('email')
    if recipient is not None:
        if not isinstance(recipient, str) or not recipient.strip():
            return jsonify({'success': False, 'message': _('Invalid request')}), 400
        recipient = recipient.strip().lower()
    only_unsent = data.get('only_unsent') is True

    try:
        results = send_assignment_emails(
            recipients=[recipient] if recipient else None,
            only_unsent=only_unsent
        )
    except EmailSendError as error:
        return jsonify({'success': False, 'message': str(error)}), error.status

    if not results:
        return jsonify({'success': True, 'message': _('Everyone has already been notified.'),
                        'email_results': []})

    sent = sum(1 for result in results if result['success'])
    return jsonify({
        'success': True,
        'message': _('Emails sent: %(sent)d, failed: %(failed)d', sent=sent, failed=len(results) - sent),
        'email_results': results,
    })

class EmailSendError(Exception):
    """Sending could not start at all (as opposed to a single email failing)."""

    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status

def send_assignment_emails(recipients=None, only_unsent=False):
    """Email givers their assignment and record the outcome in assignments.json.

    ``recipients``: giver emails to notify; None means everyone with an assignment.
    ``only_unsent``: skip givers whose email was already sent successfully.
    Returns one result dict per attempted email. Raises EmailSendError when
    nothing can be sent (no email config, no assignments, unknown recipient).
    Must run inside an app or request context (see send_email_notification).
    """
    config = load_config()
    if not config.get('email') or not config.get('password'):
        raise EmailSendError(_('Email configuration not set'))

    assignments = load_assignments()
    if not assignments:
        raise EmailSendError(_('No assignments yet. Generate assignments first.'))

    if recipients is not None:
        unknown = [email for email in recipients if email not in assignments]
        if unknown:
            raise EmailSendError(_('No assignment found for this email'), status=404)

    participants = load_participants()
    by_email = {participant['email']: participant for participant in participants}
    results = []
    for participant in participants:
        giver_email = participant['email']
        assignment = assignments.get(giver_email)
        if assignment is None:
            continue
        if recipients is not None and giver_email not in recipients:
            continue
        if only_unsent and assignment.get('email_sent_at'):
            continue

        giftee = by_email.get(assignment['giftee_email'])
        if giftee is None:
            success, message = False, _('Assignment found but giftee not found')
        else:
            success, message = send_email_notification(
                giver_email,
                participant['name'],
                giftee['name'],
                giftee['email'],
                participant.get('language'),
                giftee_likes=giftee.get('likes', ''),
                giftee_dislikes=giftee.get('dislikes', '')
            )

        if success:
            assignment['email_sent_at'] = datetime.now().isoformat()
            assignment.pop('email_error', None)
        else:
            # Keep an earlier successful send time: that email did arrive.
            assignment['email_error'] = message
        # Save after every email so an interrupted run keeps accurate status.
        save_assignments(assignments)

        results.append({
            'participant': participant['name'],
            'email': giver_email,
            'success': success,
            'message': message,
        })
    return results

def generate_assignments():
    """Generate random Secret Santa assignments"""
    participants = load_participants()
    
    if len(participants) < 2:
        return False, _('Need at least 2 participants to generate assignments')
    
    config = load_config()
    try:
        exclusion_pairs = normalize_exclusion_pairs(
            config.get('assignment_exclusions', []),
            [participant['email'] for participant in participants],
            ignore_missing=True
        )
    except ValueError as error:
        return False, _('Invalid assignment exclusions: %(error)s', error=error)

    excluded_emails = {email: set() for email in (p['email'] for p in participants)}
    for participant_email, excluded_email in exclusion_pairs:
        excluded_emails[participant_email].add(excluded_email)

    candidates = {}
    for giver_index, participant in enumerate(participants):
        candidates[giver_index] = [
            recipient_index
            for recipient_index, recipient in enumerate(participants)
            if (recipient_index != giver_index and
                    recipient['email'] not in excluded_emails[participant['email']])
        ]
        random.shuffle(candidates[giver_index])

    giver_order = list(range(len(participants)))
    random.shuffle(giver_order)
    assigned_givers = {}

    def find_recipient(giver_index, seen_recipients):
        for recipient_index in candidates[giver_index]:
            if recipient_index in seen_recipients:
                continue
            seen_recipients.add(recipient_index)
            previous_giver = assigned_givers.get(recipient_index)
            if previous_giver is None or find_recipient(previous_giver, seen_recipients):
                assigned_givers[recipient_index] = giver_index
                return True
        return False

    for giver_index in giver_order:
        if not find_recipient(giver_index, set()):
            return False, _('No valid assignments are possible with the current exclusions. Remove some exclusions and try again.')

    # Create assignments
    assignments = {}
    for giftee_index, giver_index in assigned_givers.items():
        participant = participants[giver_index]
        giftee = participants[giftee_index]
        assignments[participant['email']] = {
            'giftee_email': giftee['email'],
            'assigned_at': datetime.now().isoformat()
        }
    
    save_assignments(assignments)
    return True, assignments

def send_email_notification(participant_email, participant_name, giftee_name, giftee_email,
                            language=None, giftee_likes='', giftee_dislikes=''):
    """Send email notification to participant, in the language they registered with.

    Includes the giftee's gift wishes as they are at draw time.
    Must run inside an app or request context, otherwise the text stays English.
    """
    config = load_config()

    if not config.get('email') or not config.get('password'):
        return False, _('Email configuration not set')

    if language not in SUPPORTED_LANGUAGES:
        language = DEFAULT_LANGUAGE

    try:
        with force_locale(language):
            subject = _('Your Secret Santa Assignment!')
            sections = [_(
                'Hello %(name)s!\n\n'
                'Your Secret Santa assignment has been made!\n\n'
                'You are gifting to: %(giftee)s',
                name=participant_name,
                giftee=giftee_name
            )]
            wishes = []
            if giftee_likes:
                wishes.append(_('They like: %(likes)s', likes=giftee_likes))
            if giftee_dislikes:
                wishes.append(_('Please avoid: %(dislikes)s', dislikes=giftee_dislikes))
            if wishes:
                wishes.append(_('Wishes can still change, so check the website for the latest version.'))
                sections.append('\n'.join(wishes))
            sections.append(_('Remember to keep this secret! 🎁\n\nHappy gifting!'))
            body = '\n\n'.join(sections)

        msg = MIMEMultipart()
        msg['From'] = config['email']
        msg['To'] = participant_email
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain', 'utf-8'))

        server = smtplib.SMTP(config['smtp_server'], config['smtp_port'])
        server.starttls()
        server.login(config['email'], config['password'])
        text = msg.as_string()
        server.sendmail(config['email'], participant_email, text)
        server.quit()

        return True, _('Email sent successfully')
    except Exception as e:
        return False, _('Failed to send email: %(error)s', error=str(e))

if __name__ == '__main__':
    # Local development only; the Docker image serves the app with gunicorn.
    # Never enable debug where the app is reachable by others: the Werkzeug
    # debugger allows arbitrary code execution.
    debug = os.environ.get('FLASK_DEBUG', '').lower() in ('1', 'true', 'yes')
    app.run(host='127.0.0.1' if debug else '0.0.0.0', port=5000, debug=debug)
