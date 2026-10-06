# backup

Alpine 3.24 image that copies `/mnt/source` and writes one `tar.xz` archive to `/mnt/backups`.

```sh
./build.sh
```

`build.sh` tags the image `ghcr.io/dragoncrafted87/alpine-backup-cron`.

`BACKUP_NAME` is the file prefix. The default is `minecraft-vanillaplusplus-backup`. The rest of the name is the local time: ISO year, ISO week, weekday, hour, minute, and second, from `TZ`. The archive contains the files from the source directory. A symlink is stored as the file it points at.

A push to `main` publishes `edge` and the commit sha. A tag `backup-v2.1.0` publishes `2.1.0`. The image does not publish `latest`.
