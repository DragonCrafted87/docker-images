# docker-images

Container images for the home lab. Neither image publishes `latest`.

## base

`base/` builds `ghcr.io/dragoncrafted87/alpine:3.24`. It supplies Python and `/docker_service_init`, which runs `/scripts/setup` and then replaces itself with `/scripts/finalize`.

A tag `base-v3.24.0` publishes the image as `3.24.0`. Pushes to `main` publish `3.24` and `edge`.

## minecraft

`minecraft/` builds `ghcr.io/dragoncrafted87/alpine-minecraft` from that base. Startup retries a transient failure while it downloads the Fabric installer. If that download still fails, or the process is signaled before the server exists, the process exits so the pod can restart.

A tag `minecraft-v2.1.0` publishes the image as `2.1.0`. Pushes to `main` publish `edge`.
