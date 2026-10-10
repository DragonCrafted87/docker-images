# syntax=docker/dockerfile:1
FROM alpine:3.24

COPY root/. /

RUN <<eot ash
    set -e

    apk upgrade
    apk add --no-cache --update \
        mosquitto-clients \
        tzdata

    chmod +x /usr/local/bin/host-status.sh
    rm -rf /tmp/*
    rm -rf /var/cache/apk/*
eot

ENTRYPOINT ["/usr/local/bin/host-status.sh"]
