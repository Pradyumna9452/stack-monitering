FROM python:3.11-slim

RUN apt-get update && apt-get install -y procps && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN pip install --no-cache-dir requests

COPY exporter.py .

CMD ["python", "exporter.py"]
