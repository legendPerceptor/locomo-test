FROM python:3.11-slim

ARG http_proxy=${http_proxy:-http://172.17.0.1:1087}
ARG https_proxy=${https_proxy:-http://172.17.0.1:1087}
ENV http_proxy=${http_proxy}
ENV https_proxy=${https_proxy}
ENV no_proxy=localhost,127.0.0.1

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    EMBEDDING_HOST=0.0.0.0 \
    EMBEDDING_PORT=8000 \
    EMBEDDING_CACHE_DIR=/app/models \
    EMBEDDING_LOG_FILE=/app/logs/embedding-service.log

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY locomo_test ./locomo_test
COPY deploy_model.py ./

RUN pip install --upgrade pip \
    && pip install .

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=120s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/health || exit 1

CMD ["python", "deploy_model.py"]
