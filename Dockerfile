# SOW Family Contact App — stdlib-only Python server, no third-party deps.
# north7.sqlite is NOT baked in; mount it at runtime (see DEPLOY.md).
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY server.py dataset.py ./
COPY scripts/ scripts/
COPY static/ static/

# Run as a non-root user.
RUN useradd --create-home --uid 10001 appuser && chown -R appuser /app
USER appuser

EXPOSE 8000

# Liveness probe hits /healthz (confirms the DB is reachable). No auth needed.
HEALTHCHECK --interval=30s --timeout=4s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz').status==200 else 1)"

CMD ["python3", "server.py"]
