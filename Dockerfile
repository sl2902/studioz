# StudioZ Backend — Cloud Run Dockerfile
# Python 3.12, uv for dependency management, ffmpeg for video assembly

FROM python:3.12-slim AS base

# Install system dependencies (ffmpeg is required for video assembly)
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Set working directory
WORKDIR /app

# Copy dependency files first (cache layer)
COPY pyproject.toml uv.lock ./

# Install dependencies (production only, no dev deps)
RUN uv sync --frozen --no-dev --no-install-project

# Copy application source
COPY src/ src/
COPY config/ config/

# Install the project itself
RUN uv sync --frozen --no-dev

# Cloud Run sets PORT env var (default 8080)
ENV PORT=8080

# Run with uvicorn
CMD ["uv", "run", "uvicorn", "studioz.api.main:app", "--host", "0.0.0.0", "--port", "8080"]
