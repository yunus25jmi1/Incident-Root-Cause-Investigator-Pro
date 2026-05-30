FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN pip install --no-cache-dir coral-ai

COPY . .

RUN addgroup --system appuser && adduser --system --ingroup appuser appuser && \
    chown -R appuser:appuser /app

USER appuser

RUN mkdir -p investigator/data/reports && \
    python -m investigator.scripts.seed_all

ENV USE_MOCK_SOURCES=true

EXPOSE 8000

CMD ["uvicorn", "investigator.web.app:app", "--host", "0.0.0.0", "--port", "8000"]
