FROM python:3.11-slim

WORKDIR /app

ENV PYTHONPATH=/app/src

COPY . .

RUN pip install --no-cache-dir .

CMD ["python", "bot.py"]
