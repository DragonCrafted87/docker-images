# minecraft

Alpine 3.24 image that installs a Fabric server and runs it. Java is OpenJDK 17.

```sh
docker build --tag ghcr.io/dragoncrafted87/alpine-minecraft .
```

`MINECRAFT_VERSION` selects the Minecraft release. The default is `1.17`. The world and config live on `/mnt/minecraft`. The running server uses `/mnt/ramdisk`.

Startup downloads the Fabric installer from `maven.fabricmc.net`. A transient DNS or connection failure is retried for about fifteen seconds. The process then exits with status 1. A signal before the server process exists exits without copying the ramdisk back over the world.
