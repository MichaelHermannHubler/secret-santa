# Secret Santa Organizer

A Docker-based web application for organizing Secret Santa gift exchanges.

**Available on Docker Hub:** `docker pull michaelhermannhubler/secret-santa`

*This project was created using AI assistance.*

## Features

- **Web Registration**: Participants can register their name and email through a simple web interface
- **Random Assignment**: Generate random Secret Santa assignments via web interface or CLI command
- **Email Notifications**: Automatically send assignment emails to all participants
- **Assignment Viewing**: Participants can view their assignments on the website
- **Data Persistence**: All data is stored in JSON files and persists across container restarts
- **Security**: Password protection for assignment generation, duplicate email prevention, and self-assignment prevention

## Quick Start

### Option 1: Pull from Docker Hub (Recommended)

```bash
docker pull michaelhermannhubler/secret-santa:latest
docker run -d -p 5000:5000 -v $(pwd)/data:/app/data michaelhermannhubler/secret-santa:latest
```

### Option 2: Build from Source

```bash
docker build -t secret-santa .
docker run -d -p 5000:5000 -v $(pwd)/data:/app/data secret-santa
```

### 2. Access the Web Interface

Open your browser and go to: `http://localhost:5000`

### 3. Register Participants

Participants can register by entering their name and email on the homepage.

### 4. Configure Email (Optional)

To enable email notifications, edit `data/config.json`:

```json
{
  "smtp_server": "smtp.gmail.com",
  "smtp_port": 587,
  "email": "your-email@gmail.com",
  "password": "your-app-password",
  "admin_password": "your-secure-password"
}
```

**Note**: For Gmail, you'll need to use an [App Password](https://support.google.com/accounts/answer/185833) instead of your regular password.

### 5. Generate Assignments

Once all participants have registered, you can generate assignments in two ways:

#### Option A: Via Web Interface (Recommended)

1. Click on "Admin Panel - Generate Assignments" link on the homepage
2. Enter the admin password (default: `admin123`)
3. Optionally check "Skip sending email notifications" if you don't want emails sent
4. Click "Generate Assignments"

#### Option B: Via CLI Command

```bash
docker exec <container-id> python assign.py --password admin123
```

Or if you want to skip email notifications:

```bash
docker exec <container-id> python assign.py --password admin123 --skip-email
```

**Important**: Change the default password (`admin123`) by editing `data/config.json` before generating assignments.

## File Structure

```
secret-santa/
├── app.py              # Flask application
├── assign.py           # CLI script for generating assignments
├── requirements.txt    # Python dependencies
├── Dockerfile          # Docker configuration
├── templates/          # HTML templates
│   ├── index.html
│   ├── my_assignment.html
│   └── admin.html
├── static/
│   └── css/
│       └── style.css
└── data/               # Data directory (created at runtime)
    ├── participants.json
    ├── assignments.json
    └── config.json
```

## API Endpoints

- `GET /` - Homepage with registration form
- `POST /register` - Register a new participant
- `GET /my-assignment` - Page to check your assignment
- `POST /check-assignment` - Check assignment by email
- `GET /admin` - Admin panel for generating assignments
- `POST /generate-assignments` - Generate assignments via web interface (requires admin password)

## Data Storage

All data is stored in JSON files in the `data/` directory:

- `participants.json` - List of registered participants
- `assignments.json` - Generated assignments (email → giftee mapping)
- `config.json` - Configuration (SMTP settings, admin password)

## Security Features

- **Duplicate Email Prevention**: Prevents registering the same email twice
- **Self-Assignment Prevention**: Ensures no one is assigned to gift themselves
- **Password Protection**: Assignment generation requires admin password
- **Email Validation**: Basic email format validation

## Troubleshooting

### Email Not Sending

1. Check that `data/config.json` has correct SMTP settings
2. For Gmail, ensure you're using an App Password, not your regular password
3. Check container logs: `docker logs <container-id>`
4. Use `--skip-email` flag to generate assignments without sending emails

### Assignments Already Exist

- **CLI**: The script will prompt you before regenerating assignments
- **Web Interface**: A warning will be shown, but you can proceed to regenerate (this will overwrite existing assignments)
- You can also manually delete `data/assignments.json` if needed

### Port Already in Use

Change the port mapping: `docker run -d -p 8080:5000 ...` and access at `http://localhost:8080`

## License

MIT License

