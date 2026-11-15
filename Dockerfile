FROM python:3.11-slim

WORKDIR /app

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY app.py .
COPY assign.py .
COPY templates/ ./templates/
COPY static/ ./static/

# Create data directory
RUN mkdir -p /app/data

# Expose port
EXPOSE 5000

# Serve with gunicorn instead of the Flask development server.
# Keep a single worker: state lives in JSON files without locking, and a
# random fallback SECRET_KEY would differ per worker process.
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "1", "--threads", "4", "app:app"]
