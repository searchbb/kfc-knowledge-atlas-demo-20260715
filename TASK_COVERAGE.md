# Portal Task Acceptance Coverage

This matrix freezes implementation evidence for all 24 production tasks before the release-side-effect cases run. The final two release gates are closed only after the approved test runner publishes and verifies production.

| Task | Acceptance evidence | State before release |
|---|---|---|
| portal schema | `portal_schema.py`, `validate_portal_data.py` | completed |
| data adapter | generated `site-data.json`; source counts validated; news uses bounded recent projection | completed |
| base routes | Playwright opens home plus topic, issue, card, research, article, news routes | implemented, locally passed |
| topic page | metadata and bidirectional related-assets panel | implemented, locally passed |
| issue page | canonical question, evidence count, full content, relation panel | implemented, locally passed |
| card page | metadata, mechanism/evidence content, updated time, article relations | implemented, locally passed |
| research page | full report, metadata, and related assets | implemented, locally passed |
| home dashboard | generated counts, build metadata, latest updates, three entrances | implemented, locally passed |
| site search | all first-class collections searchable | completed |
| search ranking | shared weighted ranking module and real-data cases | completed |
| timeline | normalized mixed timeline and type filters | implemented, locally passed |
| graph navigation design | normalized relations consumed bidirectionally; documented in runbook | implemented, locally passed |
| graph navigation UI | relation nodes open the correct detail route | implemented, locally passed |
| sync script | atomic knowledge build plus bounded/indexed recent-news projection and publish lock | completed |
| build metadata | build id, source digest/revision, generated time, counts shown | implemented, locally passed |
| mail URL protocol | `portal_links.py` hash-route contract and runbook | implemented, locally passed |
| digest mail links | rendered home/article/card links without sending mail | implemented, locally passed |
| three-page migration | Knowledge assets, Article digestion, News acquisition home entrances | implemented, locally passed |
| publish flow | build, validate, commit, retry push, remote SHA verify | completed |
| Pages verify | public Pages URL and data endpoint established | completed; current release reverified by runner |
| smoke test | 4 Playwright tests: 8 entrances; 6 detail types; search/relation/timeline; mobile | implemented, 4/4 locally passed |
| consistency check | counts match; duplicates, orphans, missing fields and local paths rejected | implemented, locally passed |
| release freeze | independent static directory, enable marker, runbook and rollback tool | implementation complete; runner closes gate |
| final acceptance | accessibility, sync, update, remote SHA and rollback evidence | runner and final GPT review close gate |

Browser test source: `scripts/portal-smoke.spec.js`. Visual evidence: `portal-mobile-smoke.png`. Operational evidence: `PRODUCTION_RUNBOOK.md`.
