# backup

Alpine 3.24 image that writes one `tar.xz` archive and a `.sha256` file to `/mnt/backups`.

```sh
./build.sh
./prove.sh
```

`build.sh` tags the image `ghcr.io/dragoncrafted87/alpine-backup-cron`.

`BACKUP_NAME` is the set name. The rest of the archive name is the local time: ISO year, ISO week, weekday, hour, minute, and second, from `TZ`. The tool writes `SET-YYYY-Www-D-HH-MM-SS.tar.xz.partial`, tests it with `xz -t`, writes `SET-YYYY-Www-D-HH-MM-SS.tar.xz.sha256`, and then renames the archive. A failure removes the partial and exits non-zero. The log line carries the start, the end, the size, the duration, and the checksum, and the same line is appended to `backup.log` on the share.

`BACKUP_METHOD` chooses the payload:

- `tar` copies `/mnt/source`. A symlink is stored as the file it points at. The source has to contain at least one entry.
- `sqlite` reads each path in `SQLITE_DB` (relative to `/mnt/source`, separated by spaces) with SQLite `.backup`, then `PRAGMA integrity_check`. The live database, its `-wal`, and its `-shm` are not archived.
- `litestream` runs `litestream restore -o` for `LITESTREAM_DB` from the file replica at `LITESTREAM_REPLICA` (default `/mnt/replica`), then checks integrity. The replica directory is not archived.
- `mysql` runs `mysqldump --single-transaction --skip-ssl` against `MYSQL_HOST`, `MYSQL_USER`, and `MYSQL_DATABASE`. The password is `MYSQL_PWD`. `mariadb-connector-c` supplies the `caching_sha2_password` plugin so MySQL 8.x accepts the login. TLS is skipped because these servers present a self-signed certificate.
- `postgres` runs `pg_dump --format=custom` against `PGHOST`, `PGUSER`, and `PGDATABASE`, then checks the dump with `pg_restore --list`. The password is `PGPASSWORD`.

`BACKUP_COPY` is one extra path under `/mnt/source` placed next to a database snapshot. `BACKUP_EXTRA` is a directory copied into that same archive. When `RCON_HOST` is set, a `tar` run sends `save-off`, `save-all flush`, and `save-on`. The password is `RCON_PASSWORD`, or `rcon.password` in `/mnt/source/server.properties`. `save-on` still runs when the archive fails.

Pruning runs only after the rename. It considers one set, ignores `.partial` files, and matches only `SET-YYYY-Www-D-HH-MM-SS.tar.xz`. Retention is 14 daily, 8 weekly, and 12 monthly, counted back from the archive just written. One archive can fill more than one slot. The newest archive is always kept. `BACKUP_PRUNE` defaults to `dry-run`, which logs every deletion and removes nothing. `apply` removes those archives and their `.sha256` files. `off` skips the pass. A failed or empty run does not prune.

`BACKUP_MODE=report` prints that dry-run for every set already in `/mnt/backups` and does not write an archive. `apply` is ignored in report mode.

A push to `main` publishes `edge` and the commit sha. A tag `backup-v2.2.0` publishes `2.2.0`. The image does not publish `latest`.
