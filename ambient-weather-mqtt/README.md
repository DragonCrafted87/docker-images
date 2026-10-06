# ambient-weather-mqtt

Alpine 3.24 image that accepts an Ambient Weather station update and publishes it to MQTT. The image starts from `ghcr.io/dragoncrafted87/alpine:3.24`.

```sh
./build.sh
```

`build.sh` builds the base image, then this one, and tags it `ghcr.io/dragoncrafted87/alpine-ambient-weather-mqtt-publisher`.

The container listens on port 80. `MQTT_SERVER` defaults to `localhost` and `MQTT_SERVER_PORT` defaults to `1883`. `MQTT_USERNAME` and `MQTT_PASSWORD` are sent together when both are set.

A push to `main` publishes `edge` and the commit sha. A tag `ambient-weather-mqtt-v2.1.0` publishes `2.1.0`. The image does not publish `latest`.
