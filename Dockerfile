# Use a lightweight base Python image
FROM python:3.10-slim

# Set up environment
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV VIRTUAL_ENV=/opt/venv
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y build-essential gcc libffi-dev libssl-dev libxml2-dev libxslt1-dev zlib1g-dev && \
    rm -rf /var/lib/apt/lists/*

# Copy and install Python dependencies
COPY requirements.txt .
RUN python -m venv $VIRTUAL_ENV && \
    $VIRTUAL_ENV/bin/pip install --upgrade pip && \
    $VIRTUAL_ENV/bin/pip install -r requirements.txt && \
    $VIRTUAL_ENV/bin/pip install xai-sdk --extra-index-url=https://pypi.xai.io/simple

# Copy app code
COPY . .

# Expose app port
EXPOSE 8080

# Run the app using Gunicorn
CMD ["gunicorn", "main:app", "--bind", "0.0.0.0:8080"]
