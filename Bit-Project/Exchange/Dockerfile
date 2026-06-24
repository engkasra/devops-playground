# Base image
FROM python:3.11-slim

# Set environment variables
#ENV PYTHONDONTWRITEBYTECODE=1 \
#    PYTHONUNBUFFERED=1

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first (for caching)
COPY requirements.txt .

# Install Python dependencies
RUN pip install -r requirements.txt --no-cache-dir

# Copy project files
COPY . .

# Expose port for Django
EXPOSE 8000

# Run migrations + start dev server
ENTRYPOINT ["/app/entrypoint.sh"]
