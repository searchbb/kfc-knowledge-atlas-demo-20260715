# KFC Knowledge Atlas Demo

This repo is the static GitHub Pages mirror for the KFC knowledge portal demo.
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

The script performs exactly four steps:

1. Rebuild `data/site-data.json` from the local KFC truth sources.
2. Stage and commit all repo changes when the generated output changed.
3. Push the current branch to `origin`.
4. Verify the public GitHub Pages site by checking:
   - `https://searchbb.github.io/kfc-knowledge-atlas-demo-20260715/`
   - `https://searchbb.github.io/kfc-knowledge-atlas-demo-20260715/data/site-data.json`

The verification step requires the remote `site-data.json` SHA-256 to match the
local generated file.

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
