# Minimal standard-library Python runtime. No private SIRA Core is copied.
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080 \
    FIRELAB_INTERNAL_PORT=8765

WORKDIR /app
COPY --chown=10001:10001 . /app
RUN mkdir -p /app/runtime && chown 10001:10001 /app /app/runtime
USER 10001:10001

EXPOSE 8080
CMD ["python", "tools/run_firelab_azure.py"]
