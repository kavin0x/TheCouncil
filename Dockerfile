FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# System deps for asyncpg (PostgreSQL), aiosqlite (SQLite), and cryptography
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Install the package itself in editable mode so `council` entry-point works
RUN pip install --no-cache-dir -e .

EXPOSE 8000

CMD ["uvicorn", "council.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
