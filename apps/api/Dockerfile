FROM python:3.13.11-slim-trixie

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       curl libmagic1 postgresql-client tesseract-ocr tesseract-ocr-por \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 kairos \
    && useradd --uid 10001 --gid kairos --home-dir /app --create-home kairos

WORKDIR /app
COPY requirements.txt .
RUN pip install --requirement requirements.txt
COPY . .
RUN chmod 0555 /app/docker-entrypoint.sh \
    && mkdir -p /app/staticfiles \
    && chown -R kairos:kairos /app

USER 10001:10001
EXPOSE 8000
ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["api"]
