FROM python:3.11-slim

WORKDIR /app

ENV PYTHONPATH=/app/src

COPY pyproject.toml .
RUN mkdir -p src/kevlarbot && touch src/kevlarbot/__init__.py \
    && pip install --no-cache-dir .

COPY . .

RUN chmod +x /app/docker-entrypoint.sh

ENTRYPOINT ["/app/docker-entrypoint.sh"]
