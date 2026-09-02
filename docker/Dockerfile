# Stage 1: Build stage for compiling dependencies
FROM python:3.11-slim AS builder

WORKDIR /app

# Install compilation tools needed for C-extensions (arch, numpy, scipy)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .

# Build wheels for project dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip wheel --no-cache-dir --no-deps --wheel-dir /app/wheels -e .


# Stage 2: Minimal runtime environment
FROM python:3.11-slim AS runner

WORKDIR /app

# Create non-root system user for security compliance
RUN useradd -m -u 1000 appuser && \
    mkdir -p /app/models && \
    chown -R appuser:appuser /app

# Install compiled wheels from builder stage
COPY --from=builder /app/wheels /wheels
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir /wheels/* && \
    rm -rf /wheels

# Copy application source code
COPY --chown=appuser:appuser . .

USER appuser

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000

EXPOSE 8000

CMD ["uvicorn", "src.volatility_api.main:app", "--host", "0.0.0.0", "--port", "8000"]