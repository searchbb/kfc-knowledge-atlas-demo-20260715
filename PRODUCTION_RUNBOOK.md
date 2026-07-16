# KFC Knowledge Portal Production Runbook

## Source and synchronization contract

- `data/semantic_pipeline_v2` and `data/news_library/news_library.sqlite3` in the KFC repository are the only truth sources.
- The public portal is a read-only generated snapshot. It never writes back to local assets.
- A successful formal asset mutation triggers build, consistency validation, atomic replacement, Git push, and remote SHA-256 verification.
- A source digest prevents no-op publishes. A collection drop above 5%, an orphan relation, a missing critical field, or a local-path leak stops the release and preserves the previous online version.

## Stable URL protocol

GitHub Pages serves one static application, so stable deep links use hash routes:

- `#topic/<id>`
- `#issue/<id>`
- `#card/<id>`
- `#research/<id>`
- `#article/<id>`
- `#news/<id>`

The canonical base is `https://searchbb.github.io/kfc-knowledge-atlas-demo-20260715/`.
Digest mail uses the same protocol through `scripts/semantic_v2/portal_links.py`.

## Relation navigation

The generator emits one normalized relation list. The UI reads each relation in
both directions, so Topic, Issue, Card, Research, Article, and News pages can all
link back to the supporting or parent asset without duplicating relation records.

## Three operating entrances

The production home page replaces the old scattered entry points with three
first-class entrances backed by the same snapshot:

1. Knowledge assets: Topics, Issues, Cards, and Research.
2. Article digestion: materialized Articles and their terminal state.
3. News acquisition: News library rows, sources, summaries, and original URLs.

## Release and rollback

1. Run `python3 scripts/sync_portal_data.py --repo-root /path/to/KFC`.
2. Run `python3 scripts/validate_portal_data.py` and the browser smoke suite.
3. Run `python3 scripts/publish_portal_site.py --repo-root /path/to/KFC`.
4. Keep the returned `commit_sha`, `site_data_sha256`, and remote verification result.
5. If a verified regression is found, revert the release commit in this static-site repository, push the revert, and rerun public verification. The local KFC truth source is not rolled back by a portal rollback.
