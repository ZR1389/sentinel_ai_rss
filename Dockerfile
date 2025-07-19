FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV VIRTUAL_ENV=/opt/venv
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential gcc libffi-dev libssl-dev libxml2-dev \
    libxslt1-dev zlib1g-dev curl && \
    rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN python -m venv $VIRTUAL_ENV && \
    $VIRTUAL_ENV/bin/pip install --upgrade pip setuptools wheel && \
    $VIRTUAL_ENV/bin/pip install -r requirements.txt

# Install xai-sdk from xAI's index
RUN $VIRTUAL_ENV/bin/pip install xai-sdk --extra-index-url=https://pypi.xai.io/simple

# Copy application code
COPY . .

EXPOSE 8080

# Default: Gunicorn for web, can override in Railway for scheduler
CMD ["gunicorn", "main:app", "--bind", "0.0.0.0:8080"]