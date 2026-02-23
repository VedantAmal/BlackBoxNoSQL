# Python Flask Challenge
FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY app.py .
COPY flag.txt /flag.txt
RUN chmod 400 /flag.txt

# Run as non-root user
RUN useradd -m ctfuser
USER ctfuser

EXPOSE 80

CMD ["python", "app.py"]
