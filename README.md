# docker-images

Container images for the home lab. None of these images publish `latest`.

## base

`base/` builds `ghcr.io/dragoncrafted87/alpine:3.24`. It supplies Python and `/docker_service_init`, which runs `/scripts/setup` and then replaces itself with `/scripts/finalize`.

A tag `base-v3.24.0` publishes the image as `3.24.0`. Pushes to `main` publish `3.24` and `edge`.

## minecraft

`minecraft/` builds `ghcr.io/dragoncrafted87/alpine-minecraft` from that base. Startup retries a transient failure while it downloads the Fabric installer. If that download still fails, or the process is signaled before the server exists, the process exits so the pod can restart.

A tag `minecraft-v2.1.0` publishes the image as `2.1.0`. Pushes to `main` publish `edge`.

## foundry

`foundry/` builds `ghcr.io/dragoncrafted87/alpine-foundry-vtt-runner` from Alpine 3.24. The entrypoint is the Node command that starts Foundry with `/home/docker/data`.

A tag `foundry-v2.1.0` publishes the image as `2.1.0`. Pushes to `main` publish `edge`.

## backup

`backup/` builds `ghcr.io/dragoncrafted87/alpine-backup-cron` from Alpine 3.24. The entrypoint copies `/mnt/source` and writes one `tar.xz` under `/mnt/backups`, named from `BACKUP_NAME` and a timestamp.

A tag `backup-v2.1.0` publishes the image as `2.1.0`. Pushes to `main` publish `edge`.

## ambient-weather-mqtt

`ambient-weather-mqtt/` builds `ghcr.io/dragoncrafted87/alpine-ambient-weather-mqtt-publisher` from the base image. It listens on port 80 and publishes a station update to MQTT.

A tag `ambient-weather-mqtt-v2.1.0` publishes the image as `2.1.0`. Pushes to `main` publish `edge`.

## speedtest-mqtt

`speedtest-mqtt/` builds `ghcr.io/dragoncrafted87/alpine-speedtest-mqtt-publisher` from the base image. The setup script measures the link, publishes the result to MQTT, and the container exits.

A tag `speedtest-mqtt-v2.1.0` publishes the image as `2.1.0`. Pushes to `main` publish `edge`.

## host-status

`host-status/` builds `ghcr.io/dragoncrafted87/alpine-host-status` from Alpine 3.24. It publishes CPU, memory, temperature, and default-route rates to MQTT.

A tag `host-status-v2.1.0` publishes the image as `2.1.0`. Pushes to `main` publish `edge`.
