FROM golang:1.24.8-bookworm AS builder

ARG MINIO_REVISION=9e49d5e7a648f00e26f2246f4dc28e6b07f8c84a
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates git \
    && rm -rf /var/lib/apt/lists/*
RUN git clone --filter=blob:none --no-checkout https://github.com/minio/minio.git /src/minio \
    && cd /src/minio \
    && git checkout --detach "$MINIO_REVISION" \
    && test "$(git rev-parse HEAD)" = "$MINIO_REVISION"
WORKDIR /src/minio
RUN CGO_ENABLED=0 go build -trimpath -o /out/minio .

FROM debian:bookworm-slim
LABEL org.opencontainers.image.source="https://github.com/minio/minio" \
      org.opencontainers.image.revision="9e49d5e7a648f00e26f2246f4dc28e6b07f8c84a" \
      org.opencontainers.image.version="RELEASE.2025-10-15T17-29-55Z"
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 1000 minio \
    && useradd --uid 1000 --gid minio --home-dir /data --no-create-home minio
COPY --from=builder /out/minio /usr/local/bin/minio
USER 1000:1000
EXPOSE 9000 9001
ENTRYPOINT ["minio"]
