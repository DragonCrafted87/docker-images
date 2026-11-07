# auth-keys

Alpine 3.24 image that publishes `DragonCrafted87.keys` and pushes that file to hosts that cannot fetch it.

`build.sh` tags the image `ghcr.io/dragoncrafted87/alpine-auth-keys:edge`. The cron command is `auth-keys.sh run`. The server command is `auth-keys-serve.sh`, which serves `/www/authorized_keys` on port 8080 with busybox httpd. Alpine's default busybox omits that applet, so the image installs `busybox-extras`.

`AUTH_KEYS_SINK=file` writes `AUTH_KEYS_FILE`. `AUTH_KEYS_SINK=configmap` patches ConfigMap `auth-keys` in the pod namespace. A bad fetch, an empty fetch, or a fetch that shares no key with the current body leaves that body alone and does not push. One failed target does not roll the published body back and does not skip later targets.
