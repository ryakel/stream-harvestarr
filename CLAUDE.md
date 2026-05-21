# Repository Guidance for Claude

## Branch flow

All work follows: **feature branch → `development` → `main`**.

- Open a feature branch off `development` (or off `main` when `development`
  is in sync). Never commit directly to `development` or `main`.
- Open the first PR into `development`. The Docker Builder workflow
  publishes images tagged `dev` from this branch.
- Promote to production by opening a second PR from `development` into
  `main`. Pushes to `main` get the `latest` tag, a semver bump, and a
  GitHub release.
- Keep `development` in sync with `main` after every release so the next
  feature branch starts from a clean base.

## PR review workflow (guardrails)

Two-stage check before any `APPROVE` lands on a PR — applies to both
contributor PRs and Claude-authored PRs.

**Stage 1 — project-intent check (features only).** For any `feat(...)`
PR, before doing the technical review, ask the user via
`AskUserQuestion` whether this is a feature the project wants. Wait
for an explicit "yes" recorded in the session before doing the deep
review or submitting `APPROVE`. If the user says "no" / "not now",
post a `COMMENT` review explaining the position and leave the PR
open without an approve. Do not silently sit on it.

`fix(...)`, `chore(...)`, `docs(...)`, `refactor(...)` PRs skip
stage 1 — bug fixes are inherently in-scope, cleanups don't expand
surface area. Go straight to stage 2 at Claude's discretion.

**Stage 2 — technical review.** Submit `REQUEST_CHANGES` for any
blocking issue. Submit `APPROVE` only when **both** are true:

1. Technical review is clean (no blockers, CI green).
2. For `feat(...)`: the user gave an explicit documented "yes" in
   this session for this PR.

If you're picking up a session mid-flight (handoff context, resumed
work), don't assume a prior session's "yes" carries over — ask again.
Session-bounded intent is the safer default.

## Label conventions

Four namespaces, applied by Claude on every PR Claude opens or reviews.
The namespaces answer different questions, so multiple may apply to
one PR. Existing flat labels (`bug`, `enhancement`, `dependencies`,
etc.) are kept for historical consistency but not applied on new work.

- `intent:` — decision state on `feat(...)` PRs. Values:
  `needs-decision`, `approved`, `declined`, `deferred`. Open a
  `feat(...)` PR with `intent: needs-decision`; the user's stage-1
  answer replaces it. Non-`feat` PRs skip this namespace.
- `type:` — change category from the conventional-commit prefix.
  Values: `feat`, `fix`, `chore`, `docs`, `refactor`, `deps`, `ci`.
  Exactly one per PR.
- `area:` — codebase region. Values: `docker`, `extractor`,
  `scheduler`, `sonarr`, `config`, `workflows`, `docs`, `unraid`.
  Multiple allowed when a PR genuinely spans regions.
- `status:` — ephemeral PR-state. Values: `needs-tests`,
  `breaking-change`, `needs-rebase`. Add when the condition holds;
  remove when resolved. Not all PRs carry a `status:` label.

### Legacy labels — handle, don't apply

- `bug` / `enhancement` — superseded by `type: fix` / `type: feat`.
  Don't add to new PRs; leave alone where already applied.
- `dependencies` — Dependabot applies this automatically. Don't strip
  it. Claude does not also add `type: deps` on Dependabot PRs — the
  auto-label is operative.
- `Stale` — managed by `stale.yaml`. Never rename (the workflow
  references it by exact name).
- `awaiting-approval`, `wip` — exempt-from-stale markers per
  `stale.yaml`. Apply when a PR/issue is intentionally paused.
- `good first issue`, `question`, `python` — keep as-is. Community
  signaling and Dependabot's ecosystem tag.

### Provisioning

Labels are created by `.github/workflows/labels-bootstrap.yaml`
(`workflow_dispatch` only). Trigger from the Actions UI when adding
new namespace values, or if a label gets deleted. The workflow is
idempotent: `gh label create --force` updates color/description on
existing labels without dropping any historical applications.

## Merging

- **Never merge into `main`.** No exceptions. If a PR targets `main`
  directly, immediately submit `REQUEST_CHANGES` asking for it to be
  retargeted to `development`. GitHub branch protection on `main` is
  the defense-in-depth (the maintainer sets that up server-side); the
  rule here is the in-Claude tripwire.
- **Promoting `development → main` is a maintainer-only action.**
  Claude does not open the promotion PR and does not merge it. If the
  user explicitly asks Claude to *prepare* the diff for the
  promotion, that's fine — but the PR-create and merge buttons are
  human-only.
- For PRs targeting `development`: after `APPROVE` is submitted and
  CI is green, Claude may merge (regular merge, matching the
  repository's history). For `feat(...)` PRs, the stage-1 documented
  "yes" must already be on record before the merge.

## Container build expectations

- The image is `python:3.14-alpine` based.
- yt-dlp needs a JavaScript runtime for YouTube extraction. Without one,
  every download dies with `No video_url` (issue #96). The Dockerfile
  installs `nodejs` on every arch and `deno` on `amd64`/`arm64` only
  (Alpine doesn't package deno for `386`/`armv7`). The Python code sets
  `js_runtimes={'deno': ..., 'node': ...}` so yt-dlp prefers deno where
  available and falls back to node.
- `yt-dlp-ejs` must be installed alongside yt-dlp for the EJS extension.
- The `CI` workflow (`.github/workflows/ci.yaml`) builds the Dockerfile
  for every published arch on every PR and runs a YouTube extraction
  smoke test on linux/amd64 against the upstream yt-dlp test video.
  Treat it as required — if it goes red, fix the image rather than
  merging around it.

## yt-dlp playlist matching gotchas

`ytsearch()` in `app/stream_harvestarr.py` calls
`yt_dlp.YoutubeDL.extract_info(playlist_url, download=False)` with
`matchtitle` set to a regex built from the Sonarr episode name. Two
non-obvious behaviors bit us in issue #114:

1. **Matched entries don't always have a top-level `url` field.** The
   YouTube extractor sets `info_dict['webpage_url']` directly (the
   canonical `https://www.youtube.com/watch?v=ID` URL) but `url` is
   only populated when format selection picks a *single* non-merge
   format. HLS videos — the default for modern YouTube uploads —
   trigger ffmpeg audio+video merge; the merged "format" dict built
   in `YoutubeDL._merge` has `requested_formats` but no top-level
   `url`. After `info_dict.update(best_format)`, `entry.get('url')`
   returns None even though extraction succeeded (m3u8 manifest
   downloaded, deno JS challenge solved, etc.). Always read
   `entry.get('webpage_url') or entry.get('url')` — the fallback is
   there for non-YouTube extractors that only populate `url`.

2. **Reading webpage_url means the downstream `download()` call
   re-extracts.** The previous "working" path passed a direct
   Googlevideo stream URL to the second `ydl.download([dlurl])` call,
   which silently ignored the configured `format`,
   `merge_output_format`, and subtitle postprocessors (those options
   only apply when yt-dlp starts from a webpage URL, not a raw stream
   URL). Passing the watch URL costs an extra ~5s extraction per
   download but makes the user's format/subtitle config actually work
   and avoids stale auth-token 403s when downloads queue up.

If you ever feel tempted to "simplify" back to `.get('url')`, don't —
re-read #114 first.

## Adding new architectures

If a new platform is added to `main.yaml` / `cron.yaml`, also add it to
the `build-multiarch` job in `ci.yaml` so build failures land in PR
checks instead of in the publish workflow.

## Architecture parity caveat

`amd64` and `arm64` are the recommended (and most-tested) targets:

- They install `deno`, yt-dlp's upstream-recommended JavaScript runtime,
  which sandboxes JS execution under restricted permissions.
- The CI smoke test runs on `linux/amd64` only, so any runtime
  regression is caught there first.

`386` and `armv7` are best-effort:

- Alpine doesn't package `deno` for these arches, so they ship with
  `nodejs` only. yt-dlp's `js_runtimes` config falls back to node.
- YouTube extraction works today, but if upstream yt-dlp ever adds
  extractor features that depend on deno-specific APIs / sandboxing,
  these arches may lag.
- The multi-arch build job in `ci.yaml` keeps them honest at build
  time, but there is no per-arch runtime smoke test.

If a feature gap shows up for these arches, the response is to either
(a) drop the arch from the publish matrix, or (b) carry a deno binary
into the image manually. Don't paper over it with try/except in the
Python code.

## Dependency floor maintenance (Claude is the automation)

`requirements.txt` uses `>=` floors. Dependabot is configured to yell
when those floors drift below PyPI latest — that's intentional, don't
disable it. The image always runs the absolute latest at build time
(pip resolves `>=` to current); the floors are how we record what
we've actually validated.

**You (Claude) keep the floors current, not the pipeline.** Any time
you touch code in this repo, run the bump check before you commit:

```bash
# Freshness: skip if requirements.txt was touched in the last 4 hours.
last=$(git log -1 --format=%ct -- requirements.txt 2>/dev/null || echo 0)
now=$(date +%s)
if [ $(( now - last )) -lt 14400 ]; then
    echo "requirements.txt is fresh; skipping bump."
else
    # For each `<pkg>>=<ver>` line, query
    # https://pypi.org/pypi/<pkg>/json -> info.version and rewrite
    # the floor when it differs.
    for pkg in $(grep -oE '^[A-Za-z0-9_.-]+(?=>=)' requirements.txt); do
        latest=$(curl -fsS "https://pypi.org/pypi/${pkg}/json" \
                 | python3 -c "import sys,json; print(json.load(sys.stdin)['info']['version'])")
        sed -i "s|^${pkg}>=.*|${pkg}>=${latest}|" requirements.txt
    done
fi
```

Land the bump as its own `chore(deps): bump requirements floors to
PyPI latest` commit *before* the code change. If PyPI is unreachable,
warn and continue with the existing floors — don't block progress.
