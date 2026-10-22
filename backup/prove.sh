#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

image=ghcr.io/dragoncrafted87/alpine-backup-cron
./build.sh

work=$(mktemp -d)
net=backup-prove-$$
mysql5=
mysql8=
pg=
repl=
rcon_pid=
cleanup() {
    if [ -n "$rcon_pid" ]; then
        kill "$rcon_pid" >/dev/null 2>&1 || true
    fi
    if [ -n "$mysql5" ]; then
        docker rm -f "$mysql5" >/dev/null 2>&1 || true
    fi
    if [ -n "$mysql8" ]; then
        docker rm -f "$mysql8" >/dev/null 2>&1 || true
    fi
    if [ -n "$pg" ]; then
        docker rm -f "$pg" >/dev/null 2>&1 || true
    fi
    if [ -n "$repl" ]; then
        docker rm -f "$repl" >/dev/null 2>&1 || true
    fi
    docker network rm "$net" >/dev/null 2>&1 || true
    rm -rf "$work"
}
trap cleanup EXIT

docker network create "$net" >/dev/null

run_backup() {
    docker run --rm "$@" "$image"
}

expect_log() {
    log=$1
    text=$2
    if ! grep -q "$text" "$log"; then
        printf 'log missing %s\n' "$text" >&2
        cat "$log" >&2
        exit 1
    fi
}

# Tar, checksum, and name.
mkdir -p "$work/tar/source/nested" "$work/tar/source/empty" "$work/tar/backups"
printf 'known-line\n' >"$work/tar/source/known.txt"
printf 'nested-line\n' >"$work/tar/source/nested/inside.txt"
printf 'space name\n' >"$work/tar/source/nested/space name.txt"
ln -s inside.txt "$work/tar/source/nested/link.txt"
run_backup \
    --env BACKUP_NAME=fixture \
    --env BACKUP_PRUNE=off \
    --env BACKUP_NOW=2026-10-21T04:00:00 \
    --env TZ=UTC \
    --volume "$work/tar/source:/mnt/source:ro" \
    --volume "$work/tar/backups:/mnt/backups" \
    >"$work/tar/log"
archive=$work/tar/backups/fixture-2026-W43-3-04-00-00.tar.xz
if [ ! -f "$archive" ]; then
    printf 'missing tar archive\n' >&2
    cat "$work/tar/log" >&2
    exit 1
fi
if find "$work/tar/backups" -name '*.partial' | grep -q .; then
    printf 'partial left after success\n' >&2
    exit 1
fi
xz -t "$archive"
(
    cd "$work/tar/backups"
    sha256sum -c fixture-2026-W43-3-04-00-00.tar.xz.sha256
)
expect_log "$work/tar/log" "backup start set=fixture method=tar"
expect_log "$work/tar/log" "backup end set=fixture archive=fixture-2026-W43-3-04-00-00.tar.xz"
expect_log "$work/tar/log" "sha256="
extract=$work/tar/extract
expected=$work/tar/expected
mkdir -p "$extract" "$expected"
cp -R -L "$work/tar/source/." "$expected/"
tar -C "$extract" -xJf "$archive"
diff -rq "$expected" "$extract"

# A failed run removes the partial and does not prune.
printf 'keep-me\n' >"$work/tar/backups/fixture-2024-W20-1-04-00-00.tar.xz"
if run_backup \
    --env BACKUP_NAME=fixture \
    --env BACKUP_PRUNE=apply \
    --env BACKUP_NOW=2026-10-21T05:00:00 \
    --env TZ=UTC \
    --volume "$work/tar/missing:/mnt/source:ro" \
    --volume "$work/tar/backups:/mnt/backups" \
    >"$work/tar/fail.log" 2>"$work/tar/fail.err"; then
    printf 'missing source exited 0\n' >&2
    exit 1
fi
if [ ! -f "$work/tar/backups/fixture-2024-W20-1-04-00-00.tar.xz" ]; then
    printf 'failed run pruned a good archive\n' >&2
    exit 1
fi
if find "$work/tar/backups" -name '*.partial' | grep -q .; then
    printf 'partial left after failure\n' >&2
    exit 1
fi
if grep -q "would delete\|prune deleted" "$work/tar/fail.log"; then
    printf 'failed run logged a deletion\n' >&2
    exit 1
fi

# SQLite snapshot, including a row committed before the run.
mkdir -p "$work/sqlite/source" "$work/sqlite/backups"
sqlite3 "$work/sqlite/source/database.db" "PRAGMA journal_mode=WAL; CREATE TABLE t(id INTEGER PRIMARY KEY, name TEXT); INSERT INTO t(name) VALUES ('alpha');"
mkdir -p "$work/sqlite/source/upload"
printf 'pic\n' >"$work/sqlite/source/upload/pic.txt"
# A later uncheckpointed write must still be in the snapshot.
sqlite3 "$work/sqlite/source/database.db" "INSERT INTO t(name) VALUES ('beta');"
run_backup \
    --env BACKUP_NAME=sqlite \
    --env BACKUP_METHOD=sqlite \
    --env SQLITE_DB=database.db \
    --env BACKUP_COPY=upload \
    --env BACKUP_PRUNE=off \
    --env BACKUP_NOW=2026-10-21T04:00:00 \
    --env TZ=UTC \
    --volume "$work/sqlite/source:/mnt/source" \
    --volume "$work/sqlite/backups:/mnt/backups" \
    >"$work/sqlite/log"
sqlite_archive=$work/sqlite/backups/sqlite-2026-W43-3-04-00-00.tar.xz
xz -t "$sqlite_archive"
mkdir -p "$work/sqlite/extract"
tar -C "$work/sqlite/extract" -xJf "$sqlite_archive"
check=$(sqlite3 "$work/sqlite/extract/database.db" "PRAGMA integrity_check;")
names=$(sqlite3 "$work/sqlite/extract/database.db" "SELECT group_concat(name, ',') FROM t;")
if [ "$check" != "ok" ] || [ "$names" != "alpha,beta" ]; then
    printf 'sqlite snapshot returned check=%s names=%s\n' "$check" "$names" >&2
    exit 1
fi
if [ ! -f "$work/sqlite/extract/upload/pic.txt" ]; then
    printf 'sqlite archive dropped BACKUP_COPY\n' >&2
    exit 1
fi
if tar -tf "$sqlite_archive" | grep -q 'wal\|shm'; then
    printf 'sqlite archive contains a wal or shm file\n' >&2
    exit 1
fi
printf 'not a database\n' >"$work/sqlite/source/broken.db"
if run_backup \
    --env BACKUP_NAME=sqlite \
    --env BACKUP_METHOD=sqlite \
    --env SQLITE_DB='database.db broken.db' \
    --env BACKUP_PRUNE=apply \
    --env BACKUP_NOW=2026-10-21T06:00:00 \
    --env TZ=UTC \
    --volume "$work/sqlite/source:/mnt/source" \
    --volume "$work/sqlite/backups:/mnt/backups"; then
    printf 'broken sqlite exited 0\n' >&2
    exit 1
fi
if [ ! -f "$sqlite_archive" ]; then
    printf 'broken sqlite removed the good archive\n' >&2
    exit 1
fi

# Dry-run lists deletions and apply performs the same set.
seed_prune() {
    dest=$1
    mkdir -p "$dest/source" "$dest/backups"
    printf 'x\n' >"$dest/source/file.txt"
    touch \
        "$dest/backups/fixture-2026-W43-3-01-00-00.tar.xz" \
        "$dest/backups/fixture-2026-W43-2-04-00-00.tar.xz" \
        "$dest/backups/fixture-2026-W41-1-04-00-00.tar.xz" \
        "$dest/backups/fixture-2026-W36-1-04-00-00.tar.xz" \
        "$dest/backups/fixture-2025-W45-1-04-00-00.tar.xz" \
        "$dest/backups/fixture-2025-W44-1-04-00-00.tar.xz" \
        "$dest/backups/fixture-2024-W20-1-04-00-00.tar.xz" \
        "$dest/backups/other-2024-W20-1-04-00-00.tar.xz" \
        "$dest/backups/fixture-2026-W43-3-02-00-00.tar.xz.partial" \
        "$dest/backups/stray.txt"
    printf 'sum\n' >"$dest/backups/fixture-2024-W20-1-04-00-00.tar.xz.sha256"
    printf 'sum\n' >"$dest/backups/fixture-2026-W43-2-04-00-00.tar.xz.sha256"
}

seed_prune "$work/dry"
run_backup \
    --env BACKUP_NAME=fixture \
    --env BACKUP_PRUNE=dry-run \
    --env BACKUP_NOW=2026-10-21T04:00:00 \
    --env TZ=UTC \
    --volume "$work/dry/source:/mnt/source:ro" \
    --volume "$work/dry/backups:/mnt/backups" \
    >"$work/dry/log"
expect_log "$work/dry/log" "prune would delete fixture-2024-W20-1-04-00-00.tar.xz"
expect_log "$work/dry/log" "prune would delete fixture-2024-W20-1-04-00-00.tar.xz.sha256"
if ! find "$work/dry/backups" -name 'fixture-2024-W20-1-04-00-00.tar.xz' | grep -q .; then
    printf 'dry-run deleted an archive\n' >&2
    exit 1
fi
if ! grep -q "prune dry-run set=fixture" "$work/dry/log"; then
    printf 'dry-run summary missing\n' >&2
    cat "$work/dry/log" >&2
    exit 1
fi

seed_prune "$work/apply"
run_backup \
    --env BACKUP_NAME=fixture \
    --env BACKUP_PRUNE=apply \
    --env BACKUP_NOW=2026-10-21T04:00:00 \
    --env TZ=UTC \
    --volume "$work/apply/source:/mnt/source:ro" \
    --volume "$work/apply/backups:/mnt/backups" \
    >"$work/apply/log"
python3 - "$work/apply/backups" << 'PY'
import sys
from datetime import date, timedelta
from pathlib import Path
import re

root = Path(sys.argv[1])
anchor = date(2026, 10, 21)
daily, weekly, monthly = 14, 8, 12
pat = re.compile(r"^(?P<prefix>.+)-(?P<y>\d{4})-W(?P<w>\d{2})-(?P<d>[1-7])-\d{2}-\d{2}-\d{2}\.tar\.xz$")
names = sorted(
    (p.name for p in root.iterdir() if pat.match(p.name) and pat.match(p.name).group("prefix") == "fixture"),
    reverse=True,
)
parsed = []
for name in names:
    match = pat.match(name)
    day = date.fromisocalendar(int(match.group("y")), int(match.group("w")), int(match.group("d")))
    monday = date.fromisocalendar(int(match.group("y")), int(match.group("w")), 1)
    parsed.append((name, day, monday, day.year * 12 + day.month))
anchor_monday = anchor - timedelta(days=anchor.weekday())
anchor_month = anchor.year * 12 + anchor.month
seen_d, seen_w, seen_m = set(), set(), set()
expect = []
for index, (name, day, monday, month) in enumerate(parsed):
    keep = False
    if day not in seen_d:
        seen_d.add(day)
        delta = (anchor - day).days
        if 0 <= delta < daily:
            keep = True
    if monday not in seen_w:
        seen_w.add(monday)
        delta = (anchor_monday - monday).days // 7
        if 0 <= delta < weekly:
            keep = True
    if month not in seen_m:
        seen_m.add(month)
        delta = anchor_month - month
        if 0 <= delta < monthly:
            keep = True
    if index == 0:
        keep = True
    if keep:
        expect.append(name)
got = sorted(expect)
have = sorted(p.name for p in root.iterdir() if pat.match(p.name) and pat.match(p.name).group("prefix") == "fixture")
if have != got:
    sys.exit(f"apply kept {have}, oracle kept {got}")
left = {p.name for p in root.iterdir()}
for required in (
    "other-2024-W20-1-04-00-00.tar.xz",
    "fixture-2026-W43-3-02-00-00.tar.xz.partial",
    "stray.txt",
    "fixture-2026-W43-2-04-00-00.tar.xz.sha256",
):
    if required not in left:
        sys.exit(f"apply removed {required}")
if "fixture-2024-W20-1-04-00-00.tar.xz.sha256" in left:
    sys.exit("apply left the checksum of a deleted archive")
print("apply kept", len(got))
PY
expect_log "$work/apply/log" "prune deleted fixture-2024-W20-1-04-00-00.tar.xz"
expect_log "$work/apply/log" "prune deleted fixture-2024-W20-1-04-00-00.tar.xz.sha256"

# One ancient archive is the newest, so report mode keeps it.
mkdir -p "$work/report"
printf 'old\n' >"$work/report/only-2024-W20-1-04-00-00.tar.xz"
run_backup \
    --env BACKUP_MODE=report \
    --env BACKUP_NOW=2026-10-21T04:00:00 \
    --env TZ=UTC \
    --volume "$work/report:/mnt/backups:ro" \
    >"$work/report.log"
expect_log "$work/report.log" "prune dry-run set=only keep=1 drop=0"
if grep -q "would delete" "$work/report.log"; then
    printf 'report wanted to delete the only archive\n' >&2
    exit 1
fi

# MySQL 5.7 and 8, then Postgres.
wait_mysql() {
    name=$1
    for _ in $(seq 1 60); do
        if docker exec "$name" mysqladmin ping -uroot -pprove-secret --silent >/dev/null 2>&1; then
            return 0
        fi
        sleep 2
    done
    printf '%s did not become ready\n' "$name" >&2
    docker logs "$name" >&2 || true
    exit 1
}

dump_has_row() {
    archive=$1
    dir=$2
    mkdir -p "$dir"
    tar -C "$dir" -xJf "$archive"
    if ! grep -q "prove-row" "$dir"/*.sql; then
        printf 'dump missing prove-row in %s\n' "$archive" >&2
        exit 1
    fi
    xz -t "$archive"
}

mysql5=backup-prove-mysql5-$$
docker run -d --name "$mysql5" --network "$net" \
    --env MYSQL_ROOT_PASSWORD=prove-secret \
    --env MYSQL_DATABASE=app \
    mysql:5.7.44 >/dev/null
wait_mysql "$mysql5"
docker exec "$mysql5" mysql -uroot -pprove-secret app -e "CREATE TABLE t(name VARCHAR(32)); INSERT INTO t VALUES ('prove-row');"
mkdir -p "$work/mysql5"
run_backup \
    --network "$net" \
    --env BACKUP_NAME=mysql5 \
    --env BACKUP_METHOD=mysql \
    --env MYSQL_HOST=backup-prove-mysql5-$$ \
    --env MYSQL_USER=root \
    --env MYSQL_PWD=prove-secret \
    --env MYSQL_DATABASE=app \
    --env BACKUP_PRUNE=off \
    --env BACKUP_NOW=2026-10-21T04:00:00 \
    --env TZ=UTC \
    --volume "$work/mysql5:/mnt/backups" \
    >"$work/mysql5.log"
dump_has_row "$work/mysql5/mysql5-2026-W43-3-04-00-00.tar.xz" "$work/mysql5/extract"
docker rm -f "$mysql5" >/dev/null
mysql5=

mysql8=backup-prove-mysql8-$$
docker run -d --name "$mysql8" --network "$net" \
    --env MYSQL_ROOT_PASSWORD=prove-secret \
    --env MYSQL_DATABASE=app \
    mysql:8.4 >/dev/null
wait_mysql "$mysql8"
docker exec "$mysql8" mysql -uroot -pprove-secret app -e "CREATE TABLE t(name VARCHAR(32)); INSERT INTO t VALUES ('prove-row');"
mkdir -p "$work/mysql8"
run_backup \
    --network "$net" \
    --env BACKUP_NAME=mysql8 \
    --env BACKUP_METHOD=mysql \
    --env MYSQL_HOST=backup-prove-mysql8-$$ \
    --env MYSQL_USER=root \
    --env MYSQL_PWD=prove-secret \
    --env MYSQL_DATABASE=app \
    --env BACKUP_PRUNE=off \
    --env BACKUP_NOW=2026-10-21T04:00:00 \
    --env TZ=UTC \
    --volume "$work/mysql8:/mnt/backups" \
    >"$work/mysql8.log"
dump_has_row "$work/mysql8/mysql8-2026-W43-3-04-00-00.tar.xz" "$work/mysql8/extract"
docker rm -f "$mysql8" >/dev/null
mysql8=

pg=backup-prove-pg-$$
docker run -d --name "$pg" --network "$net" \
    --env POSTGRES_PASSWORD=prove-secret \
    --env POSTGRES_USER=pulp \
    --env POSTGRES_DB=pulp \
    postgres:16.15 >/dev/null
for _ in $(seq 1 60); do
    if docker exec "$pg" pg_isready -U pulp -d pulp >/dev/null 2>&1; then
        break
    fi
    sleep 2
done
docker exec "$pg" psql -U pulp -d pulp -c "CREATE TABLE t(name TEXT); INSERT INTO t VALUES ('prove-row');"
mkdir -p "$work/pg"
run_backup \
    --network "$net" \
    --env BACKUP_NAME=postgres \
    --env BACKUP_METHOD=postgres \
    --env PGHOST=backup-prove-pg-$$ \
    --env PGUSER=pulp \
    --env PGPASSWORD=prove-secret \
    --env PGDATABASE=pulp \
    --env BACKUP_PRUNE=off \
    --env BACKUP_NOW=2026-10-21T04:00:00 \
    --env TZ=UTC \
    --volume "$work/pg:/mnt/backups" \
    >"$work/pg.log"
mkdir -p "$work/pg/extract"
tar -C "$work/pg/extract" -xJf "$work/pg/postgres-2026-W43-3-04-00-00.tar.xz"
xz -t "$work/pg/postgres-2026-W43-3-04-00-00.tar.xz"
if ! docker run --rm --entrypoint pg_restore \
    --volume "$work/pg/extract:/dump:ro" \
    "$image" --list /dump/pulp.dump | grep -q "TABLE DATA"; then
    printf 'pg_dump is not a readable custom archive\n' >&2
    exit 1
fi
docker rm -f "$pg" >/dev/null
pg=

# Litestream restore from a file replica, not a tar of that replica.
mkdir -p "$work/ls/db" "$work/ls/replica" "$work/ls/extra/files" "$work/ls/backups" "$work/ls/config"
printf 'attached\n' >"$work/ls/extra/files/note.txt"
cat >"$work/ls/config/litestream.yml" << 'EOF'
dbs:
  - path: /db/app.db
    replica:
      type: file
      path: /replica
EOF
docker run --rm --user 0 --network none -e HOME=/tmp \
    --volume "$work/ls/db:/db" \
    --entrypoint /bin/sh "$image" \
    -c 'sqlite3 /db/app.db "CREATE TABLE t(name TEXT); INSERT INTO t VALUES ('"'"'alpha'"'"');"'
repl=backup-prove-ls-$$
docker run -d --name "$repl" --user 0 --network none -e HOME=/tmp \
    --volume "$work/ls/config/litestream.yml:/litestream.yml:ro" \
    --volume "$work/ls/db:/db" \
    --volume "$work/ls/replica:/replica" \
    --entrypoint litestream "$image" \
    replicate -config /litestream.yml >/dev/null
sleep 2
docker run --rm --user 0 --network none -e HOME=/tmp \
    --volume "$work/ls/db:/db" \
    --entrypoint /bin/sh "$image" \
    -c 'sqlite3 /db/app.db "INSERT INTO t VALUES ('"'"'beta'"'"');"'
sleep 2
docker rm -f "$repl" >/dev/null
repl=
run_backup \
    --env BACKUP_NAME=litestream \
    --env BACKUP_METHOD=litestream \
    --env LITESTREAM_DB=/db/app.db \
    --env LITESTREAM_REPLICA=/mnt/replica \
    --env BACKUP_EXTRA=/mnt/extra \
    --env BACKUP_PRUNE=off \
    --env BACKUP_NOW=2026-10-21T04:00:00 \
    --env TZ=UTC \
    --volume "$work/ls/replica:/mnt/replica:ro" \
    --volume "$work/ls/extra:/mnt/extra:ro" \
    --volume "$work/ls/backups:/mnt/backups" \
    >"$work/ls/log"
ls_archive=$work/ls/backups/litestream-2026-W43-3-04-00-00.tar.xz
xz -t "$ls_archive"
mkdir -p "$work/ls/extract"
tar -C "$work/ls/extract" -xJf "$ls_archive"
ls_names=$(sqlite3 "$work/ls/extract/app.db" "SELECT group_concat(name, ',') FROM t;")
if [ "$ls_names" != "alpha,beta" ]; then
    printf 'litestream restore returned %s\n' "$ls_names" >&2
    exit 1
fi
if [ ! -f "$work/ls/extract/files/note.txt" ]; then
    printf 'litestream archive dropped BACKUP_EXTRA\n' >&2
    exit 1
fi
if tar -tf "$ls_archive" | grep -q '^replica'; then
    printf 'litestream archive contains the replica\n' >&2
    exit 1
fi

# RCON failure leaves no archive. A fake server records the flush sequence.
mkdir -p "$work/rcon/source" "$work/rcon/backups"
printf 'world\n' >"$work/rcon/source/level.dat"
printf 'rcon.password=prove\n' >"$work/rcon/source/server.properties"
if run_backup \
    --env BACKUP_NAME=rcon \
    --env RCON_HOST=127.0.0.1 \
    --env RCON_PORT=1 \
    --env BACKUP_PRUNE=apply \
    --env BACKUP_NOW=2026-10-21T04:00:00 \
    --env TZ=UTC \
    --volume "$work/rcon/source:/mnt/source:ro" \
    --volume "$work/rcon/backups:/mnt/backups" \
    >"$work/rcon/fail.log" 2>"$work/rcon/fail.err"; then
    printf 'refused rcon exited 0\n' >&2
    exit 1
fi
if find "$work/rcon/backups" -name 'rcon-*.tar.xz' | grep -q .; then
    printf 'refused rcon published an archive\n' >&2
    exit 1
fi

RCON_LOG=$work/rcon/server.log python3 - << 'PY' &
import socket, struct, os
path = os.environ["RCON_LOG"]
server = socket.socket()
server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
server.bind(("0.0.0.0", 35575))
server.listen(1)
seen = []

def read_packet(conn):
    header = b""
    while len(header) < 4:
        chunk = conn.recv(4 - len(header))
        if not chunk:
            return None
        header += chunk
    size = struct.unpack("<i", header)[0]
    body = b""
    while len(body) < size:
        chunk = conn.recv(size - len(body))
        if not chunk:
            return None
        body += chunk
    req_id, kind = struct.unpack("<ii", body[:8])
    payload = body[8:-2].decode()
    return req_id, kind, payload

def write_packet(conn, req_id, kind, payload):
    data = struct.pack("<ii", req_id, kind) + payload.encode() + b"\x00\x00"
    conn.sendall(struct.pack("<i", len(data)) + data)

while "save-on" not in seen:
    conn, _ = server.accept()
    auth = read_packet(conn)
    if auth and auth[1] == 3 and auth[2] == "prove":
        write_packet(conn, auth[0], 2, "")
        write_packet(conn, auth[0], 0, "")
    else:
        write_packet(conn, -1, 2, "")
        conn.close()
        continue
    while True:
        packet = read_packet(conn)
        if packet is None:
            break
        seen.append(packet[2])
        write_packet(conn, packet[0], 0, "ok")
    conn.close()
server.close()
open(path, "w", encoding="utf-8").write("\n".join(seen) + "\n")
PY
rcon_pid=$!
sleep 1
run_backup \
    --add-host=rconhost:host-gateway \
    --env BACKUP_NAME=rcon \
    --env RCON_HOST=rconhost \
    --env RCON_PORT=35575 \
    --env BACKUP_PRUNE=off \
    --env BACKUP_NOW=2026-10-21T04:10:00 \
    --env TZ=UTC \
    --volume "$work/rcon/source:/mnt/source:ro" \
    --volume "$work/rcon/backups:/mnt/backups" \
    >"$work/rcon/ok.log"
wait "$rcon_pid"
rcon_pid=
expect_log "$work/rcon/server.log" "save-off"
expect_log "$work/rcon/server.log" "save-all flush"
expect_log "$work/rcon/server.log" "save-on"
if [ ! -f "$work/rcon/backups/rcon-2026-W43-3-04-10-00.tar.xz" ]; then
    printf 'rcon success did not publish\n' >&2
    exit 1
fi
expect_log "$work/rcon/ok.log" "rcon save-off"
expect_log "$work/rcon/ok.log" "rcon save-on"

printf 'backup prove ok\n'
