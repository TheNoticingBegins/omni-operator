FROM python:3.12-slim

# FFmpeg is required for audio decoding (transcription plugin)
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY config.py bot.py ./
COPY modules/ ./modules/

# Data directory for personas.yaml and optional message history
RUN mkdir -p /data
VOLUME ["/data"]

# Prometheus metrics (optional, enabled via METRICS_PORT)
EXPOSE 8080

CMD ["python", "bot.py"]