# docker-images

Container images for the home lab.

## minecraft

`minecraft/` builds `ghcr.io/dragoncrafted87/alpine-minecraft` from Alpine 3.24. Startup retries a transient failure while it downloads the Fabric installer. If that download still fails, or the process is signaled before the server exists, the process exits so the pod can restart.

A tag `minecraft-v2.1.0` publishes the image as `2.1.0`. Pushes to `main` publish `edge`.
