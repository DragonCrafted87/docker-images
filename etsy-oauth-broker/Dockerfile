# syntax=docker/dockerfile:1
FROM alpine:3.24

COPY broker.py /usr/local/lib/etsy-oauth-broker/broker.py

RUN <<eot ash
    set -e
    apk upgrade
    apk add --no-cache python3
    addgroup -g 1000 -S etsy
    adduser -S -D -H -u 1000 -G etsy -h /tmp -s /sbin/nologin etsy
    rm -rf /tmp/* /var/cache/apk/*
eot

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
USER etsy
ENTRYPOINT ["python3", "/usr/local/lib/etsy-oauth-broker/broker.py"]
