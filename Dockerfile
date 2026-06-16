FROM python:3.12-slim

# psycopg2-binary ships wheels, but libpq runtime is handy; keep it slim.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install deps first for better layer caching.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Normalize line endings (Windows CRLF would break the shebang) and make executable.
RUN sed -i 's/\r$//' /app/entrypoint.sh && chmod +x /app/entrypoint.sh

EXPOSE 8000
ENTRYPOINT ["/app/entrypoint.sh"]
