# syntax=docker/dockerfile:1
FROM alpine:3.24

COPY root/ /

RUN <<eot ash
    set -e

    apk upgrade
    # Alpine's default busybox omits httpd. busybox-extras provides it.
    apk add --no-cache --update \
        busybox-extras \
        curl \
        jq \
        openssh-client

    chmod +x /usr/local/bin/auth-keys.sh /usr/local/bin/auth-keys-serve.sh
    rm -rf /tmp/*
    rm -rf /var/cache/apk/*
eot

ENTRYPOINT ["/usr/local/bin/auth-keys.sh"]
