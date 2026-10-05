FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY pyproject.toml /app/pyproject.toml
COPY bagsort /app/bagsort

RUN python -m compileall -q /app/bagsort

EXPOSE 8080

CMD ["python", "-m", "bagsort", "--state", "/data/state", "--addr", "0.0.0.0:8080", "serve"]
