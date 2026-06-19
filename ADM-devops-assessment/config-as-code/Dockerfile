# ---------- build stage ----------
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY app/requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# ---------- runtime stage ----------
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH" \
    APP_NAME=devops-demo \
    APP_ENV=production \
    LOG_LEVEL=INFO \
    PORT=8000

WORKDIR /app

# Run as an unprivileged user (security best practice).
RUN useradd --create-home --uid 1000 appuser

# Bring in the pre-built virtualenv and the application code.
COPY --from=builder /opt/venv /opt/venv
COPY app/ /app/

USER appuser
EXPOSE 8000

# Container-level healthcheck (also used by docker-compose).
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health').status==200 else 1)"

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
