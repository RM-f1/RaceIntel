FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    RACEINTEL_OFFLINE=1 \
    RACEINTEL_DB_PATH=/app/tests/fixtures/ci.db

WORKDIR /app

COPY requirements.txt pyproject.toml ./
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/
COPY app.py ./app.py
COPY frontend/ ./frontend/
COPY artifacts/ ./artifacts/
COPY tests/fixtures/ci.db ./tests/fixtures/ci.db

RUN pip install --no-cache-dir --no-deps -e .

EXPOSE 8001

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8001/health/', timeout=3)"

CMD ["uvicorn", "raceintel.api.main:app", "--host", "0.0.0.0", "--port", "8001"]
