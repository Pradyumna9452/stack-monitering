FROM python:3.11-slim

LABEL maintainer="Zabbix-GLPI Integration"
LABEL description="Automated ticket lifecycle management between Zabbix and GLPI"

# Install dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY *.py ./
COPY *.js ./
COPY *.json ./
COPY entrypoint.sh ./
RUN chmod +x entrypoint.sh

# Create data directory for SQLite database
RUN mkdir -p /data

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV DATABASE_PATH=/data/zabbix_glpi.db

# Expose webhook port
EXPOSE 5002

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:5002/health || exit 1

# Use entrypoint script
ENTRYPOINT ["./entrypoint.sh"]
