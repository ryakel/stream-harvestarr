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
