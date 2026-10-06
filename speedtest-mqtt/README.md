# speedtest-mqtt

Alpine 3.24 image that measures ping, download, and upload, then publishes the result to MQTT and exits. The image starts from `ghcr.io/dragoncrafted87/alpine:3.24`.

```sh
./build.sh
```

`build.sh` builds the base image, then this one, and tags it `ghcr.io/dragoncrafted87/alpine-speedtest-mqtt-publisher`.

`/docker_service_init` runs `/scripts/setup/run_job.py`, then the base finalize script, then the process exits. `MQTT_SERVER` defaults to `localhost` and `MQTT_SERVER_PORT` defaults to `1883`. `PING_COUNT` defaults to 20. One sample has no previous sample to compare, so the count has to be at least 2.

A push to `main` publishes `edge` and the commit sha. A tag `speedtest-mqtt-v2.1.0` publishes `2.1.0`. The image does not publish `latest`.
