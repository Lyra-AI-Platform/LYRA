FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    LYRA_HOST=0.0.0.0 LYRA_PORT=7860 LYRA_SERVE_WEBSITE=1

WORKDIR /app
COPY requirements-server.txt .
RUN pip install --no-cache-dir -r requirements-server.txt

COPY lyra ./lyra
COPY frontend ./frontend
COPY website ./website

RUN useradd -r -u 1000 -m lyra && mkdir -p /app/data && chown -R lyra:lyra /app
USER lyra

VOLUME ["/app/data"]
EXPOSE 7860
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:7860/api/health', timeout=4)"
CMD ["python", "-m", "lyra.main"]
