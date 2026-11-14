# Dashboard w kontenerze (wormer). Build: deploy/docker/build.sh
FROM python:3.12-slim-bookworm
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1 \
    TZ=Europe/Warsaw HOME=/tmp/home
RUN apt-get update -qq && apt-get install -y -qq --no-install-recommends tzdata curl \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
ARG REVISION=unknown
LABEL org.opencontainers.image.revision=$REVISION
# Dane (/app/data) i tokeny Garmina (/tokens) to wolumeny, nie czesc obrazu.
USER 1000:1000
CMD ["python", "serve.py", "--server.address", "127.0.0.1", "--server.port", "8501", "--server.headless", "true"]
