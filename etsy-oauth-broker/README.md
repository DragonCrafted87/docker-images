# etsy-oauth-broker

`etsy-oauth-broker/` builds `ghcr.io/dragoncrafted87/etsy-oauth-broker` from Alpine 3.24 and Python's standard library. The process runs the Etsy authorization-code flow for `https://etsy.stealthdragonland.net/oauth/callback` and the scopes `listings_r`, `listings_w`, `shops_r`, and `shops_w`.

`listings_w` can create and edit listings, including publication. `shops_w` can update the shop description, messages, and sections. The broker does not call those endpoints. It writes one raw refresh token into the Secret named by `ETSY_REFRESH_SECRET` (default `etsy-refresh-token`) and discards the access token.

The public listener is `0.0.0.0:8080` and answers `GET /oauth/callback`, `GET /healthz`, and `GET /readyz`. Every other public path is `404`. The private listener is `127.0.0.1:8091` and answers `POST /flows` and `GET /status`. `POST /flows` takes an empty body and returns the Etsy authorization URL. `GET /status` returns pending-flow and Secret metadata. Neither listener has a route that returns a token.

The keystring is the file `ETSY_KEYSTRING_FILE` (default `/run/secrets/etsy/keystring`). A single trailing newline is removed. The shared secret is not read. The refresh token is the `refresh-token` key of one Opaque Secret in `ETSY_NAMESPACE` (default `etsy`). The API address is `KUBERNETES_API` (default `https://kubernetes.default.svc`). The bearer token and API CA are `KUBERNETES_TOKEN_FILE` and `KUBERNETES_CA_FILE`. A create is a single POST. An existing Secret, a Secret with any other data key, or a Secret whose `etsy.stealthdragonland.net/exported-at` annotation is 24 hours old or missing blocks a new flow. The process does not update or delete that Secret. Status reports the name, byte count, and age. It does not report the token.

Pending flows live in memory for 10 minutes. Three pending flows, or 30 callbacks in 60 seconds, is the cap. A restart drops pending flows and leaves the refresh Secret where it is. Token exchange uses `POST https://api.etsy.com/v3/public/oauth/token` with a 10 second timeout and a 64 KiB response cap. The form sends `grant_type`, `client_id`, `code`, `code_verifier`, and the exact redirect URI.

A tag `etsy-oauth-broker-v1.0.0` publishes the image as `1.0.0`. Pushes to `main` publish `edge`. The image does not publish `latest`.

The cluster runbook is `manifests/etsy/README.md` in `k8s-manifests`.
