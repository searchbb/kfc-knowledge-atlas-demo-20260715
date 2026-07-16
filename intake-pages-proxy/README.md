# Cloudflare Pages intake proxy

This stateless proxy gives browsers and the Mac receiver a reachable `pages.dev`
endpoint while the authoritative queue remains in the private Worker D1 database.
It forwards only the intake API surface and injects a private hop secret.

Required production secrets:

- `UPSTREAM_WORKER_ORIGIN`
- `PROXY_SHARED_SECRET`
