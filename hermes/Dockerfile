# syntax=docker/dockerfile:1
# Hermes plus the screen tools and Proton Pass CLI.
# The base is Debian Trixie. An Alpine rebuild is a later decision.
# pass-cli 2.5.1 hashes are from
# https://proton.me/download/pass-cli/versions.json on 2026-10-23.
FROM nousresearch/hermes-agent:v0.22.2@sha256:36099926da316742423544e055d4734777105ffe6341873af5459b957d0c2919

USER root

# Package names are the screen set. Versions float with the pinned base.
# hadolint ignore=DL3008
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        tigervnc-standalone-server \
        xfce4-panel \
        xfwm4 \
        xfdesktop4 \
        xfce4-settings \
        xfce4-terminal \
        dbus-x11 \
        x11-xserver-utils \
        x11-utils \
        x11-xkb-utils \
        xauth \
        fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

ARG TARGETARCH
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
RUN set -eu; \
    case "$TARGETARCH" in \
        amd64) arch=x86_64; sum=40e27645e0485f5f0db928b81469d1c5a7c8968a162956e940069476244c02b1 ;; \
        arm64) arch=aarch64; sum=03042c8ad70b21fa1da834f2e4e74484710ab3f05754af10c5035acdf68f3c87 ;; \
        *) echo "no pass-cli build for ${TARGETARCH}" >&2; exit 1 ;; \
    esac; \
    curl -fsSL -o /usr/local/bin/pass-cli \
        "https://proton.me/download/pass-cli/2.5.1/pass-cli-linux-${arch}"; \
    echo "${sum}  /usr/local/bin/pass-cli" | sha256sum -c -; \
    chmod 755 /usr/local/bin/pass-cli

USER 10000
