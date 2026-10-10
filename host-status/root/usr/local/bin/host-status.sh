#!/bin/sh
# Publish one retained host status payload. The first sample is only a
# baseline. A later sample with no CPU delta publishes nothing.
set -eu

ROOT=${HOST_STATUS_ROOT:-/}
HOST=${HOST_STATUS_HOST:-}
if [ -z "$HOST" ]; then
    HOST=$(hostname 2>/dev/null || printf '%s' unknown)
fi
BROKER=${HOST_STATUS_BROKER:-}
INTERVAL=${HOST_STATUS_INTERVAL:-30}
TOPIC=${HOST_STATUS_TOPIC:-homelab/status/$HOST}
ONCE=${HOST_STATUS_ONCE:-0}

sample_index=0

sample_path() {
    rel=$1
    if [ -f "$ROOT/$rel.$sample_index" ]; then
        printf '%s\n' "$ROOT/$rel.$sample_index"
        return 0
    fi
    if [ -f "$ROOT/$rel" ]; then
        printf '%s\n' "$ROOT/$rel"
        return 0
    fi
    return 1
}

iface_skipped() {
    name=$1
    case $name in
        lo)
            return 0
            ;;
        br-lan)
            return 1
            ;;
        docker*|veth*|cni*|flannel*|cali*|kube*|virbr*|dummy*|ifb*|sit*|gre*|tunl*|wg*|zt*|tailscale*|nodelocal*|vxlan*|cilium*|lxc*|br-*)
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}

write_snapshot() {
    sample_index=$1
    dest=$2
    : >"$dest"

    stat_path=$(sample_path proc/stat || true)
    if [ -n "$stat_path" ]; then
        awk '/^cpu / {
            busy = $2 + $3 + $4 + $7 + $8 + $9
            total = busy + $5 + $6
            printf "cpu %s %s\n", busy, total
            exit
        }' "$stat_path" >>"$dest"
    fi

    mem_path=$(sample_path proc/meminfo || true)
    if [ -n "$mem_path" ]; then
        awk '
            $1 == "MemTotal:" { total = $2 + 0 }
            $1 == "MemAvailable:" { avail = $2 + 0; have = 1 }
            $1 == "MemFree:" { free = $2 + 0 }
            $1 == "Buffers:" { buffers = $2 + 0 }
            $1 == "Cached:" { cached = $2 + 0 }
            END {
                if (!have) {
                    avail = free + buffers + cached
                }
                printf "mem %s %s\n", total + 0, avail + 0
            }
        ' "$mem_path" >>"$dest"
    fi

    best=
    for zone in "$ROOT"/sys/class/thermal/thermal_zone*; do
        if [ ! -f "$zone/temp" ]; then
            continue
        fi
        raw=$(tr -d '[:space:]' <"$zone/temp")
        case $raw in
            ''|*[!0-9]*)
                continue
                ;;
        esac
        if [ "$raw" -gt 1000 ]; then
            tenths=$((raw / 100))
        else
            tenths=$((raw * 10))
        fi
        if [ "$tenths" -le 0 ] || [ "$tenths" -gt 1500 ]; then
            continue
        fi
        if [ -z "$best" ] || [ "$tenths" -gt "$best" ]; then
            best=$tenths
        fi
    done
    if [ -n "$best" ]; then
        printf 'temp %s\n' "$best" >>"$dest"
    fi

    route_path=$(sample_path proc/net/route || true)
    if [ -n "$route_path" ]; then
        primary=$(awk '
            NR > 1 && $2 == "00000000" {
                metric = $7 + 0
                if (best == "" || metric < best) {
                    best = metric
                    iface = $1
                }
            }
            END {
                if (iface != "") {
                    print iface
                }
            }
        ' "$route_path")
        if [ -n "${primary:-}" ]; then
            printf 'primary %s\n' "$primary" >>"$dest"
        fi
    fi

    dev_path=$(sample_path proc/net/dev || true)
    if [ -n "$dev_path" ]; then
        awk '$1 ~ /:$/ {
            name = $1
            sub(":", "", name)
            printf "%s %s %s\n", name, $2, $10
        }' "$dev_path" | while read -r name rx tx; do
            if iface_skipped "$name"; then
                continue
            fi
            printf 'net %s %s %s\n' "$name" "$rx" "$tx"
        done >>"$dest"
    fi
}

emit_payload() {
    awk -v interval="$INTERVAL" '
        FNR == NR {
            if ($1 == "cpu") {
                busy1 = $2 + 0
                total1 = $3 + 0
            }
            if ($1 == "net") {
                rx1[$2] = $3 + 0
                tx1[$2] = $4 + 0
            }
            next
        }
        {
            if ($1 == "cpu") {
                busy2 = $2 + 0
                total2 = $3 + 0
            }
            if ($1 == "mem") {
                mem_total = $2 + 0
                mem_avail = $3 + 0
            }
            if ($1 == "temp") {
                tenths = $2 + 0
                have_temp = 1
            }
            if ($1 == "primary") {
                primary = $2
            }
            if ($1 == "net") {
                count++
                order[count] = $2
                rx2[$2] = $3 + 0
                tx2[$2] = $4 + 0
            }
        }
        END {
            delta_total = total2 - total1
            if (delta_total <= 0) {
                exit 0
            }
            if (interval + 0 <= 0) {
                exit 0
            }
            delta_busy = busy2 - busy1
            if (delta_busy < 0) {
                delta_busy = 0
            }
            cpu = (delta_busy / delta_total) * 100
            if (mem_total <= 0) {
                memory = 0
            } else {
                memory = ((mem_total - mem_avail) / mem_total) * 100
                if (memory < 0) {
                    memory = 0
                }
            }
            if (have_temp) {
                whole = int(tenths / 10)
                frac = tenths % 10
                temp_json = sprintf("%d.%d", whole, frac)
            } else {
                temp_json = "null"
            }
            primary_rx = 0
            primary_tx = 0
            if (primary != "" && (primary in rx2)) {
                primary_rx = rx2[primary] - rx1[primary]
                primary_tx = tx2[primary] - tx1[primary]
                if (primary_rx < 0) {
                    primary_rx = 0
                }
                if (primary_tx < 0) {
                    primary_tx = 0
                }
                primary_rx = int(primary_rx / interval)
                primary_tx = int(primary_tx / interval)
            }
            printf "{\"cpu_percent\":%.1f,\"memory_percent\":%.1f,\"temperature_c\":%s,\"primary\":\"%s\",\"rx_bps\":%d,\"tx_bps\":%d,\"net\":[", cpu, memory, temp_json, primary, primary_rx, primary_tx
            for (i = 1; i <= count; i++) {
                name = order[i]
                rx = rx2[name] - rx1[name]
                tx = tx2[name] - tx1[name]
                if (rx < 0) {
                    rx = 0
                }
                if (tx < 0) {
                    tx = 0
                }
                if (i > 1) {
                    printf ","
                }
                printf "{\"name\":\"%s\",\"rx_bps\":%d,\"tx_bps\":%d}", name, int(rx / interval), int(tx / interval)
            }
            printf "],\"disks\":[]}\n"
        }
    ' "$1" "$2"
}

workdir=$(mktemp -d)
trap 'rm -rf "$workdir"' EXIT

idx=0
while true; do
    idx=$((idx + 1))
    write_snapshot "$idx" "$workdir/cur"
    if [ -f "$workdir/prev" ]; then
        payload=$(emit_payload "$workdir/prev" "$workdir/cur" || true)
        if [ -n "$payload" ]; then
            if [ -n "$BROKER" ]; then
                mosquitto_pub -h "$BROKER" -p 1883 -t "$TOPIC" -r -m "$payload"
            else
                printf '%s\n' "$payload"
            fi
        fi
        if [ "$ONCE" = 1 ]; then
            exit 0
        fi
    fi
    mv "$workdir/cur" "$workdir/prev"
    sleep "$INTERVAL"
done
