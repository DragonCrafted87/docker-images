# hermes

`build.sh` tags the image `ghcr.io/dragoncrafted87/hermes-agent:v0.22.2-screen`. It starts from `nousresearch/hermes-agent:v0.22.2` and adds TigerVNC, the Xfce screen packages, and Proton Pass CLI 2.5.1.

The base is Debian. Rebuilding this on Alpine is a later decision.

A tag `hermes-v0.22.2-screen` publishes the image as `0.22.2-screen`. Pushes to `main` publish `edge`. The image does not publish `latest`. The bake target is amd64, which is what the cluster runs. The Dockerfile also accepts an arm64 Pass CLI build.

`prove.sh` builds the image and checks `pass-cli` and the screen binaries as uid 10000.
