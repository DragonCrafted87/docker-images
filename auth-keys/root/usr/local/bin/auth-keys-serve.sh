#!/bin/sh
# Serve the published authorized_keys file. The URL path is the
# file name under /www.
set -eu
exec httpd -f -p 8080 -h /www
