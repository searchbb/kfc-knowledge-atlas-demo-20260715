# News Synchronization Boundary

## What the public site does now

The local SQLite database remains the authoritative news store. The static site
does **not** upload the database and does **not** export the full table on every
publish. Its main snapshot contains only the latest bounded window (default 500
rows) plus `newsMeta.totalCount`, cursor timestamps, and the public fields needed
for recent browsing. Structured analysis and curated research remain separate,
comparatively small snapshots.

Every live 30-minute digest cycle refreshes this bounded projection before it
sends the reader briefing. The publish step is idempotent: unchanged input
creates no commit, but the currently deployed hashes are still verified. If
build, push, or external verification fails, the briefing is blocked rather
than linking to a knowingly stale snapshot.

## Production path for large history

When public full-history access is required, the supported architecture is:

1. The crawler commits a local SQLite transaction.
2. A change-data-capture worker reads rows after a durable `(updated_at, id)` cursor.
3. It upserts only changed rows into a remote query database through a private API.
4. It advances the cursor only after remote acknowledgement and count/hash checks.
5. The GitHub Pages frontend queries that API for pagination, filters, and search.
6. The local SQLite database remains the source of truth; the remote database is a read-only public projection and can be rebuilt from a cursor checkpoint.

This is O(changed rows), not O(total rows). A failed network call does not roll
back local ingestion and does not advance the cursor, so the next run retries the
same idempotent upserts.

## Why full static export is rejected

A single JSON file or Git history containing hundreds of thousands or millions
of news rows causes unbounded repository growth, slow deploys, large browser
downloads, and unusable full-text search. Static date shards can extend a small
archive, but they are not the production answer for million-row querying. That
requires a remote database/API chosen and provisioned with deployment credentials.
