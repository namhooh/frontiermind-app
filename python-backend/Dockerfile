# Build stage - install dependencies
FROM python:3.12-slim as builder

WORKDIR /app

# Install build dependencies (including WeasyPrint build deps)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for layer caching
COPY requirements.txt .

# Install Python dependencies to user directory
RUN pip install --no-cache-dir --user -r requirements.txt

# Production stage - minimal runtime image
FROM python:3.12-slim

WORKDIR /app

# Install runtime dependencies (including WeasyPrint runtime deps for PDF generation)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libgdk-pixbuf-2.0-0 \
    libffi8 \
    shared-mime-info \
    fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# Copy installed packages from builder
COPY --from=builder /root/.local /root/.local

# Ensure scripts in .local are in PATH
ENV PATH=/root/.local/bin:$PATH

# Copy application code
COPY . .

# Remove unnecessary files to reduce image size
RUN rm -rf tests/ test_data/ scripts/ __pycache__/ .env .env.example *.pyc exports/ venv/

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV ENVIRONMENT=production

# Cloud Run uses PORT environment variable (default 8080)
ENV PORT=8080

# Expose port
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:${PORT}/health || exit 1

# Start uvicorn server
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT}"]
