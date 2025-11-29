# FORCE REBUILD 2025-11-12-fix
FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV VIRTUAL_ENV=/opt/venv
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

WORKDIR /app

# Install system dependencies (build + runtime libs for WeasyPrint and reportlab)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential gcc libffi-dev libssl-dev libxml2-dev \
    libxslt1-dev zlib1g-dev curl \
    libfreetype6-dev libfreetype6 \
    libjpeg62-turbo-dev libjpeg62-turbo \
    libpng-dev libpng16-16 \
    libcairo2 libcairo-gobject2 \
    libpango-1.0-0 libpangocairo-1.0-0 libpangoft2-1.0-0 \
    libgdk-pixbuf-2.0-0 \
    fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

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

CMD ["gunicorn", "core.main:app", "--bind", "0.0.0.0:8080", "--timeout", "120"]