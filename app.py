from flask import Flask, render_template, request, jsonify, redirect, url_for, session
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
        raise ValueError('Assignment exclusions must be a list')

    participant_emails = set(participant_emails)
    normalized_pairs = set()
    for pair in pairs:
        if (not isinstance(pair, (list, tuple)) or len(pair) != 2 or
                not all(isinstance(email, str) for email in pair)):
            raise ValueError('Each assignment exclusion must contain two participant emails')
        first_email, second_email = pair
        if first_email == second_email:
            raise ValueError('A participant cannot be excluded from themselves')
        if first_email not in participant_emails or second_email not in participant_emails:
            if ignore_missing:
                continue
            raise ValueError('Assignment exclusions must refer to registered participants')
        normalized_pairs.add((first_email, second_email))

    return sorted(normalized_pairs)

def parse_participant_indices(raw_indices, participant_count, own_index=None):
    """Validate participant indices submitted for one participant's exclusions."""
    if not isinstance(raw_indices, list):
        raise ValueError('Excluded participants must be provided as a list')

    indices = set()
    for raw_index in raw_indices:
        if isinstance(raw_index, bool) or not isinstance(raw_index, (int, str)):
            raise ValueError('Invalid excluded participant')
        try:
            index = int(raw_index)
        except ValueError:
            raise ValueError('Invalid excluded participant')
        if index < 0 or index >= participant_count:
            raise ValueError('Invalid excluded participant')
        if index == own_index:
            raise ValueError('You cannot exclude yourself')
        indices.add(index)
    return sorted(indices)

@app.route('/')
def index():
    """Home page with registration form"""
    participants = load_participants()
    assignments = load_assignments()
    return render_template('index.html', participants=participants, assignments=assignments)

@app.route('/register', methods=['POST'])
def register():
    """Register a new participant"""
    name = request.form.get('name', '').strip()
    email = request.form.get('email', '').strip().lower()
    
    if not name or not email:
        return jsonify({'success': False, 'message': 'Name and email are required'}), 400
    
    # Basic email validation
    if '@' not in email:
        return jsonify({'success': False, 'message': 'Invalid email format'}), 400
    
    participants = load_participants()
    # Check for duplicate email
    if any(p['email'] == email for p in participants):
        return jsonify({'success': False, 'message': 'This email is already registered'}), 400

    try:
        excluded_indices = parse_participant_indices(
            request.form.getlist('excluded_indices'),
            len(participants)
        )
    except ValueError as error:
        return jsonify({'success': False, 'message': str(error)}), 400
    
    # Add new participant
    participants.append({
        'name': name,
        'email': email,
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
        return jsonify({'success': False, 'message': f'Could not save exclusions: {error}'}), 500

    save_participants(participants)
    save_config(config)
    
    return jsonify({'success': True, 'message': 'Successfully registered!'})

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
    """Read or update the directed exclusions belonging to a participant."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({'success': False, 'message': 'Invalid request'}), 400

    email = data.get('email')
    if not isinstance(email, str) or not email.strip():
        return jsonify({'success': False, 'message': 'A registered email is required'}), 400
    email = email.strip().lower()
    participants = load_participants()
    participant_index = next(
        (index for index, participant in enumerate(participants)
         if participant['email'] == email),
        None
    )
    if participant_index is None:
        return jsonify({'success': False, 'message': 'No participant found for this email'}), 404

    config = load_config()
    try:
        exclusion_pairs = normalize_exclusion_pairs(
            config.get('assignment_exclusions', []),
            [participant['email'] for participant in participants],
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

    return jsonify({
        'success': True,
        'message': 'Your assignment exclusions have been saved.',
        'participant_index': participant_index,
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
        return jsonify({'success': False, 'message': 'Email is required'}), 400
    
    assignments = load_assignments()
    
    if email not in assignments:
        return jsonify({'success': False, 'message': 'No assignment found for this email'}), 404
    
    assignment = assignments[email]
    participants = load_participants()
    giftee = next((p for p in participants if p['email'] == assignment['giftee_email']), None)
    
    if not giftee:
        return jsonify({'success': False, 'message': 'Assignment found but giftee not found'}), 404
    
    return jsonify({
        'success': True,
        'giftee_name': giftee['name'],
        'giftee_email': giftee['email']
    })

@app.route('/admin')
def admin():
    """Admin page for generating assignments"""
    # Check if user is authenticated
    if not session.get('admin_authenticated'):
        return render_template('admin.html', authenticated=False)
    
    participants = load_participants()
    assignments = load_assignments()
    return render_template('admin.html', authenticated=True, participants=participants, assignments=assignments)

@app.route('/admin/login', methods=['POST'])
def admin_login():
    """Authenticate admin user"""
    password = request.form.get('password', '').strip()
    config = load_config()
    
    # Verify password
    if password == config.get('admin_password', 'admin123'):
        session['admin_authenticated'] = True
        return jsonify({'success': True, 'message': 'Authentication successful'})
    else:
        return jsonify({'success': False, 'message': 'Invalid password'}), 401

@app.route('/admin/logout', methods=['POST'])
def admin_logout():
    """Logout admin user"""
    session.pop('admin_authenticated', None)
    return jsonify({'success': True, 'message': 'Logged out successfully'})

@app.route('/admin/participants/remove', methods=['POST'])
def remove_participant():
    """Remove a registered participant and reset assignments."""
    if not session.get('admin_authenticated'):
        return jsonify({'success': False, 'message': 'Not authenticated. Please log in first.'}), 401

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({'success': False, 'message': 'Invalid request'}), 400

    email = data.get('email')
    if not isinstance(email, str) or not email.strip():
        return jsonify({'success': False, 'message': 'A participant email is required'}), 400
    email = email.strip().lower()

    participants = load_participants()
    if not any(participant['email'] == email for participant in participants):
        return jsonify({'success': False, 'message': 'Participant not found'}), 404

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
        'message': 'Participant removed. Generate assignments again to notify the remaining participants.'
    })

@app.route('/generate-assignments', methods=['POST'])
def generate_assignments_web():
    """Generate assignments via web interface"""
    # Check if user is authenticated
    if not session.get('admin_authenticated'):
        return jsonify({'success': False, 'message': 'Not authenticated. Please log in first.'}), 401
    
    skip_email = request.form.get('skip_email', 'false') == 'true'
    
    # Note: We allow regeneration even if assignments exist (user can use CLI for confirmation prompt)
    
    # Generate assignments
    success, result = generate_assignments()
    
    if not success:
        return jsonify({'success': False, 'message': result}), 400
    
    assignments = result
    participants = load_participants()
    email_results = []
    
    # Send email notifications if not skipped
    if not skip_email:
        config = load_config()
        if config.get('email') and config.get('password'):
            for participant in participants:
                assignment = assignments.get(participant['email'])
                if assignment:
                    giftee = next((p for p in participants if p['email'] == assignment['giftee_email']), None)
                    if giftee:
                        success, message = send_email_notification(
                            participant['email'],
                            participant['name'],
                            giftee['name'],
                            giftee['email']
                        )
                        email_results.append({
                            'participant': participant['name'],
                            'email': participant['email'],
                            'success': success,
                            'message': message
                        })
        else:
            email_results.append({
                'participant': 'System',
                'email': '',
                'success': False,
                'message': 'Email configuration not set'
            })
    
    return jsonify({
        'success': True,
        'message': f'Successfully generated assignments for {len(assignments)} participants!',
        'email_results': email_results,
        'skip_email': skip_email
    })

def generate_assignments():
    """Generate random Secret Santa assignments"""
    participants = load_participants()
    
    if len(participants) < 2:
        return False, 'Need at least 2 participants to generate assignments'
    
    config = load_config()
    try:
        exclusion_pairs = normalize_exclusion_pairs(
            config.get('assignment_exclusions', []),
            [participant['email'] for participant in participants],
            ignore_missing=True
        )
    except ValueError as error:
        return False, f'Invalid assignment exclusions: {error}'

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
            return False, 'No valid assignments are possible with the current exclusions. Remove some exclusions and try again.'

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

def send_email_notification(participant_email, participant_name, giftee_name, giftee_email):
    """Send email notification to participant"""
    config = load_config()
    
    if not config.get('email') or not config.get('password'):
        return False, 'Email configuration not set'
    
    try:
        msg = MIMEMultipart()
        msg['From'] = config['email']
        msg['To'] = participant_email
        msg['Subject'] = 'Your Secret Santa Assignment!'
        
        body = f"""
Hello {participant_name}!

Your Secret Santa assignment has been made!

You are gifting to: {giftee_name}

Remember to keep this secret! 🎁

Happy gifting!
"""
        msg.attach(MIMEText(body, 'plain'))
        
        server = smtplib.SMTP(config['smtp_server'], config['smtp_port'])
        server.starttls()
        server.login(config['email'], config['password'])
        text = msg.as_string()
        server.sendmail(config['email'], participant_email, text)
        server.quit()
        
        return True, 'Email sent successfully'
    except Exception as e:
        return False, f'Failed to send email: {str(e)}'

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
