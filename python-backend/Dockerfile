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
COPY python-backend/requirements.txt .

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

# Copy backend application code
COPY python-backend/ .

# Copy project onboarding SQL script
COPY database/scripts/project-onboarding/onboard_project.sql database/scripts/project-onboarding/onboard_project.sql

# Copy data ingestion modules (processing pipeline + fetchers)
COPY data-ingestion/processing/schema_validator.py data_ingestion/processing/schema_validator.py
COPY data-ingestion/processing/transformer.py data_ingestion/processing/transformer.py
COPY data-ingestion/processing/meter_reading_loader.py data_ingestion/processing/meter_reading_loader.py
COPY data-ingestion/processing/ingest_service.py data_ingestion/processing/ingest_service.py
COPY data-ingestion/processing/__init__.py data_ingestion/processing/__init__.py
COPY data-ingestion/processing/meter_aggregate_loader.py data_ingestion/processing/meter_aggregate_loader.py
COPY data-ingestion/processing/billing_resolver.py data_ingestion/processing/billing_resolver.py
COPY data-ingestion/processing/adapters/__init__.py data_ingestion/processing/adapters/__init__.py
COPY data-ingestion/processing/adapters/cbe_billing_adapter.py data_ingestion/processing/adapters/cbe_billing_adapter.py
COPY data-ingestion/__init__.py data_ingestion/__init__.py
COPY data-ingestion/sources/inverter-api/__init__.py data_ingestion/fetchers/__init__.py
COPY data-ingestion/sources/inverter-api/base_fetcher.py data_ingestion/fetchers/base_fetcher.py
COPY data-ingestion/sources/inverter-api/config.py data_ingestion/fetchers/config.py
COPY data-ingestion/sources/inverter-api/solaredge/__init__.py data_ingestion/fetchers/solaredge/__init__.py
COPY data-ingestion/sources/inverter-api/solaredge/fetcher.py data_ingestion/fetchers/solaredge/fetcher.py
COPY data-ingestion/sources/inverter-api/enphase/__init__.py data_ingestion/fetchers/enphase/__init__.py
COPY data-ingestion/sources/inverter-api/enphase/fetcher.py data_ingestion/fetchers/enphase/fetcher.py
COPY data-ingestion/sources/inverter-api/goodwe/__init__.py data_ingestion/fetchers/goodwe/__init__.py
COPY data-ingestion/sources/inverter-api/goodwe/fetcher.py data_ingestion/fetchers/goodwe/fetcher.py
COPY data-ingestion/sources/inverter-api/sma/__init__.py data_ingestion/fetchers/sma/__init__.py
COPY data-ingestion/sources/inverter-api/sma/fetcher.py data_ingestion/fetchers/sma/fetcher.py

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
