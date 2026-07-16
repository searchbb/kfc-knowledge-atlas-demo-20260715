# KFC Knowledge Asset Portal

This repo is the production static GitHub Pages mirror for the KFC knowledge portal.
The KFC workspace remains the source of truth. This repo only stores generated
site assets plus the scripts that rebuild and publish them.

## Requirements

- Python 3.10+
- Git access to `searchbb/kfc-knowledge-atlas-demo-20260715`
- A local KFC checkout with:
  - `data/semantic_pipeline_v2/`
  - `data/news_library/news_library.sqlite3`

## Fixed Publish Flow

Run the full build -> publish -> verify sequence from this repo:

```bash
/Users/mac/.pyenv/versions/3.10.14/bin/python3 \
  scripts/publish_portal_site.py \
  --repo-root /Users/mac/Downloads/code/KFC
```

The script performs five guarded steps:

1. Rebuild `data/site-data.json` from the local KFC truth sources.
2. Validate counts, required fields, relation endpoints, timeline endpoints, and public-path safety.
3. Stage and commit all repo changes only when the source digest changed.
4. Push the current branch to `origin` with bounded retry.
5. Verify the public GitHub Pages site by checking:
   - `https://searchbb.github.io/kfc-knowledge-atlas-demo-20260715/`
   - `https://searchbb.github.io/kfc-knowledge-atlas-demo-20260715/data/site-data.json`

The verification step requires the remote `site-data.json` SHA-256 to match the
local generated file.

`sync_portal_data.py` performs an atomic replacement. A collection drop greater
than 5% is rejected by default, so an incomplete local read cannot overwrite the
last known-good public snapshot.

## Automatic publish after asset changes

The 30-minute formal digest pipeline calls `scripts/semantic_v2/portal_publish_hook.py`
after an article reaches the terminal `digested` state. The hook is active only
when `.portal-auto-publish-enabled` exists. It performs the same guarded build,
push, and remote hash verification used for manual production releases. Failed
publishes are recorded without removing the last verified online version.

See `PRODUCTION_RUNBOOK.md` for deep-link rules, relation navigation, rollback,
and operational checks.

## New Environment Repeatability

On a fresh machine or clone:

```bash
git clone https://github.com/searchbb/kfc-knowledge-atlas-demo-20260715.git
cd kfc-knowledge-atlas-demo-20260715
/Users/mac/.pyenv/versions/3.10.14/bin/python3 \
  scripts/publish_portal_site.py \
  --repo-root /path/to/KFC \
  --skip-push \
  --skip-verify
```

That proves the build path is reproducible before granting push credentials.

## Useful Flags

- `--skip-push`: rebuild and commit locally without pushing.
- `--skip-verify`: skip the public Pages verification step.
- `--pages-url <url>`: override the derived public URL.
- `--verify-attempts <n>` and `--verify-sleep-seconds <n>`: adjust retry logic
  when Pages deployment is slow.
- `--push-attempts <n>` and `--push-sleep-seconds <n>`: adjust bounded push retry.
