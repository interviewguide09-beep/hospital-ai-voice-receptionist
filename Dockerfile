# Use an official Python 3.12 runtime slim base image
FROM python:3.12-slim

# Set system environment settings
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV WORKDIR=/workspace

# Set the active working directory
WORKDIR $WORKDIR

# Install system dependencies needed for compiling extensions
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    default-libmysqlclient-dev \
    pkg-config \
    curl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies first to cache this layer
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Copy the application source code files into container
COPY app/ app/
COPY migrations/ migrations/
COPY alembic.ini .

# Expose FastAPI server port
EXPOSE 8000

# Execute server boot: run migrations, seed database, then start uvicorn
CMD ["sh", "-c", "alembic upgrade head && python -m app.database.seed_cp_tiwari && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
