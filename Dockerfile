FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8000
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN useradd --create-home --uid 10001 commerce && mkdir -p /data/uploads && chown -R commerce:commerce /data /app
COPY --chown=commerce:commerce . .
USER commerce
ENV DATABASE_PATH=/data/seucomercio.sqlite3 UPLOAD_DIR=/data/uploads
EXPOSE 8000
CMD ["sh", "-c", "exec gunicorn 'app:create_app()' --bind 0.0.0.0:${PORT:-8000} --workers 1 --threads 4 --timeout 60 --access-logfile -"]
