# minecraft

Alpine 3.24 image that installs a Fabric server and runs it. Java is OpenJDK 17. The image starts from `ghcr.io/dragoncrafted87/alpine:3.24`.

```sh
./build.sh
```

`build.sh` builds the base image, then this one, and tags it `ghcr.io/dragoncrafted87/alpine-minecraft`.

`MINECRAFT_VERSION` selects the Minecraft release. The default is `1.17`. OpenJDK 17 runs Minecraft through 1.20.4. A release of 1.20.5 or newer needs Java 21, which this image does not install. The world and config live on `/mnt/minecraft`. The running server uses `/mnt/ramdisk`.

`EULA=true` writes `eula.txt` on the ramdisk before launch. That file is one of the names copied back to `/mnt/minecraft`, so an acceptance on the volume is there on the next start. Without it, the server writes `eula=false` and exits.

The container starts at `/docker_service_init`. Minecraft has no setup scripts, so the init replaces itself with `/scripts/finalize`. Startup downloads the Fabric installer from `maven.fabricmc.net`. A transient DNS or connection failure is retried for about fifteen seconds. The process then exits with status 1. A signal before the server process exists exits without copying the ramdisk back over the world.

SIGTERM waits up to 20 seconds for the server to stop, then copies the ramdisk for up to 150 seconds. `docker stop -t` and a pod `terminationGracePeriodSeconds` have to be at least 180. A shorter stop kills the process while that copy is still running.
