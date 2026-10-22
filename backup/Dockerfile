# syntax=docker/dockerfile:1
FROM litestream/litestream:0.5.17 AS litestream
FROM alpine:3.24

COPY --from=litestream /usr/local/bin/litestream /usr/local/bin/litestream
COPY root/. /

RUN <<eot ash
    set -e

    apk upgrade
    apk add --no-cache --update \
        coreutils \
        mariadb-client \
        mariadb-connector-c \
        postgresql16-client \
        rcon \
        sqlite \
        tzdata \
        xz

    chmod +x /usr/local/bin/backup
    rm -rf /tmp/*
    rm -rf /var/cache/apk/*
eot

ENTRYPOINT ["/usr/local/bin/backup"]
