# base

Alpine 3.24 image with Python 3, pip, and tzdata. `minecraft/`, `ambient-weather-mqtt/`, and `speedtest-mqtt/` build `FROM ghcr.io/dragoncrafted87/alpine:3.24`. `foundry/` and `backup/` start from `alpine:3.24` directly because each has its own entrypoint.

```sh
docker build --tag ghcr.io/dragoncrafted87/alpine:3.24 .
```

`/docker_service_init` is the entrypoint. It runs the files in `/scripts/setup` in name order. A setup script that exits non-zero stops the container with that status. When setup has nothing to run, the init replaces itself with `/scripts/finalize`.

`PYTHONPATH` is `/scripts:/scripts/includes`. A setup script can import `python_logger`. A finalize script can import `includes`.

A push to `main` publishes `3.24`, `edge`, and the commit sha. A tag `base-v3.24.0` publishes `3.24.0`. The image does not publish `latest`.
