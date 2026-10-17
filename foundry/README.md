# foundry

Node 20 on Alpine. Foundry 9 calls `util.isDate`, which Node 24 removed. The entrypoint is `node server/resources/app/main.js --headless --dataPath=/home/docker/data`.

```sh
./build.sh
```

`build.sh` tags the image `ghcr.io/dragoncrafted87/alpine-foundry-vtt-runner`. The process runs as `docker` (uid 1000). Mount the Foundry server tree at `/home/docker/server` and the data directory at `/home/docker/data`.

A push to `main` publishes `edge` and the commit sha. A tag `foundry-v2.1.0` publishes `2.1.0`. The image does not publish `latest`.
