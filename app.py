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
    
    # Add new participant
    participants.append({
        'name': name,
        'email': email,
        'registered_at': datetime.now().isoformat()
    })
    save_participants(participants)
    
    return jsonify({'success': True, 'message': 'Successfully registered!'})

@app.route('/my-assignment')
def my_assignment():
    """Page to view your assignment"""
    return render_template('my_assignment.html')

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
    
    # Create a list of indices
    indices = list(range(len(participants)))
    
    # Shuffle until no one is assigned to themselves
    max_attempts = 100
    for attempt in range(max_attempts):
        random.shuffle(indices)
        # Check if anyone is assigned to themselves
        if all(i != indices[i] for i in range(len(indices))):
            break
    else:
        return False, 'Could not generate valid assignments after multiple attempts'
    
    # Create assignments
    assignments = {}
    for i, participant in enumerate(participants):
        giftee_index = indices[i]
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

