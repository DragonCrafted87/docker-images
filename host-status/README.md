# host-status

`build.sh` tags the image `ghcr.io/dragoncrafted87/alpine-host-status`. The process reads host `/proc` and `/sys` from `HOST_STATUS_ROOT` and publishes one retained JSON payload to `homelab/status/<host>`.

A tag `host-status-v2.1.0` publishes the image as `2.1.0`. Pushes to `main` publish `edge`. The image does not publish `latest`.

`prove.sh` builds the image, runs it against a fixture tree, and reads the retained payload from a local broker.
