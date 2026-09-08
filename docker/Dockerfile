# Stage 1: Build stage for resolving and downloading binary wheels
FROM python:3.11-slim AS builder

WORKDIR /app

# Install compilation tools needed for C-extensions (arch, numpy, scipy)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Upgrade pip and copy only dependency definitions for caching
COPY pyproject.toml README.md ./
COPY src/ ./src/

# Build wheels for the project and all of its dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip wheel --no-cache-dir --wheel-dir /app/wheels .


# Stage 2: Minimal runtime environment
FROM python:3.11-slim AS runner

WORKDIR /app

# Create a non-privileged user for security compliance (UID 1000)
RUN useradd -m -u 1000 appuser && \
    mkdir -p /app/models && \
    chown -R appuser:appuser /app

# Install pre-built wheels from builder stage
COPY --from=builder /app/wheels /wheels
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir /wheels/* && \
    rm -rf /wheels

# Copy application source code with correct non-root permissions
COPY --chown=appuser:appuser . .

USER appuser

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000

EXPOSE 8000

CMD ["uvicorn", "src.volatility_api.main:app", "--host", "0.0.0.0", "--port", "8000"]