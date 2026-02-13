FROM python:3.11-slim

WORKDIR /app

# Install system dependencies for pdfplumber (uses pdfminer.six)
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc && \
    rm -rf /var/lib/apt/lists/*

# Copy project files
COPY pyproject.toml README.md ./
COPY src/ src/

# Install the package and web dependencies
RUN pip install --no-cache-dir . gunicorn flask

# Create non-root user
RUN useradd --create-home appuser
USER appuser

# Railway sets PORT env var
ENV PORT=8080
EXPOSE ${PORT}

CMD gunicorn --bind 0.0.0.0:${PORT} --workers 2 --timeout 120 "archery_parser.web:create_app()"
