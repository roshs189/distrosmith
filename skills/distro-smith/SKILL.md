---
name: distro-smith
description: >-
  End-to-end distro bring-up for a board: generate its qcom-ptool
  partition files and open (but never merge) a PR for them, bump
  meta-qcom's qcom-ptool.inc SRCREV directly to that PR's head commit,
  trigger a real kas-container build for the --distro and --image inputs
  (defaulting to qcom-distro/qcom-console-image when not given) unless
  --skip-build is passed or this run is invoked as part of an orchestrating
  pipeline, attempting a fix and retry if the build fails, and — once the
  build succeeds or is skipped — commit and open the meta-qcom PR. This
  skill (not qcom-yocto-new-machine) owns the SRCREV bump, the build-retry
  loop, the PR automation, and distro-params.yml — qcom-yocto-new-machine
  only gets a board as far as generated machine files and a generated-file
  summary. Neither the qcom-ptool PR nor the meta-qcom PR is ever
  auto-merged by this skill — both are left open for the user to review and
  merge by hand. Always writes the run's result to
  distro-params.yml outside the clone work directory, and on a successful
  run cleans up its own clone work directory once that file is written
  (failed runs keep the work directory for debugging). Stitches together
  qcom-partition-conf-new-board and qcom-yocto-new-machine into one
  invocation. Use for "run the build distro skill for <machine>", "do the
  full distro flow for <machine>", or "run distro-smith for <machine>".
  Accepts --machine <machine>, --distro <distro>, --image <image>, and the
  explicit escape hatch --skip-build. Do
  NOT use for just the partition files (use qcom-partition-conf-new-board
  alone) or just the machine conf (use qcom-yocto-new-machine alone) —
  this skill exists specifically to chain both together with a distro PR
  artifact for downstream build orchestration.
---

# Run the full distro-smith flow for a board

Sequences `qcom-partition-conf-new-board` and `qcom-yocto-new-machine` so
one invocation takes a board from its board-spec entry all the way to an
open qcom-ptool PR, a real build against that PR's head commit, and (on
success) an open meta-qcom PR — ending in one `distro-params.yml` that
reports what happened. Neither PR is merged by this skill; both stay open
for the user's own review.

Required invocation form:

```bash
$distro-smith --machine <machine> [--distro <distro>] [--image <image>] [--skip-build]
```

Treat these as inputs:

- `--machine <machine>`: **required.** Target machine name used for partition
  and machine bring-up.
- `--distro <distro>`: Yocto distro to use in the build configuration and to
  write into `distro-params.yml`. Optional — defaults to `qcom-distro` when
  not given.
- `--image <image>`: image target to build and to write into
  `distro-params.yml`. Optional — defaults to `qcom-console-image` when not
  given.
- `--skip-build`: explicit escape hatch for cases where the user wants to
  raise the meta-qcom PR and produce `distro-params.yml` without running
  the kas build or build retry loop.

Only run the internal build (step 2b) when this skill is invoked standalone
(directly by a user or agent, not as part of a larger pipeline). If the
invocation context indicates this skill is running inside the qli-orchestrator
pipeline (or any other orchestrating pipeline) — e.g. the invoking prompt or
conversation references an orchestrator, a numbered pipeline stage, or an
already-initialized run log — skip the internal build regardless of whether
`--skip-build` was passed, per step 2b. Otherwise, run the build by default
unless `--skip-build` is explicitly passed.

`qcom-yocto-new-machine` only writes the machine conf, CI yaml, and
supporting recipes. It does not build, validate, run pre-PR checks, commit,
open a PR, or write `distro-params.yml`. Everything past file generation —
bumping `qcom-ptool.inc`'s `SRCREV`, running the build, retrying a failed
build with a fix, committing, opening the meta-qcom PR, and writing
`distro-params.yml` — is this skill's own responsibility.
`qcom-yocto-new-machine`'s `SKILL.md` remains the source of truth for its
own file-generation steps and prerequisites (env vars, checkout locations —
see its Section 0).

## 0. Parse inputs and scope check

Parse `--machine`, `--distro`, and `--image` from the invocation. Use exactly
the first value supplied for each argument throughout this run. Do not infer or
replace these values later. If `--distro` is not supplied, default it to
`qcom-distro`. If `--image` is not supplied, default it to
`qcom-console-image`.

Validate:

- `--machine` is non-empty.
- `--skip-build`, if present, is recorded as an intentional validation skip
  in status output, the PR body, and `distro-params.yml`.

Then perform the meta-qcom scope check below.

Before any cloning or `cd` into a checkout, capture the original cwd and
derive the artifact path:

```sh
RUN_CWD="$(pwd -P)"
WORK_ROOT_INPUT="${BUILD_DISTRO_ROOT:-$RUN_CWD/.distrosmith-work}"
case "$WORK_ROOT_INPUT" in
  /*) ;;
  *)  WORK_ROOT_INPUT="$RUN_CWD/$WORK_ROOT_INPUT" ;;
esac

if [ -d "$WORK_ROOT_INPUT" ]; then
  WORK_ROOT="$(cd "$WORK_ROOT_INPUT" && pwd -P)"
else
  WORK_ROOT_PARENT="$(dirname "$WORK_ROOT_INPUT")"
  WORK_ROOT_BASENAME="$(basename "$WORK_ROOT_INPUT")"
  if [ -d "$WORK_ROOT_PARENT" ]; then
    WORK_ROOT="$(cd "$WORK_ROOT_PARENT" && pwd -P)/$WORK_ROOT_BASENAME"
  else
    WORK_ROOT="$WORK_ROOT_INPUT"
  fi
fi

case "$RUN_CWD/" in
  "$WORK_ROOT"/*) DISTRO_PARAMS_DIR="$(dirname "$WORK_ROOT")" ;;
  *)              DISTRO_PARAMS_DIR="$RUN_CWD" ;;
esac

DISTRO_PARAMS_PATH="$DISTRO_PARAMS_DIR/distro-params.yml"
export BUILD_DISTRO_ROOT="$WORK_ROOT"
```

Use `DISTRO_PARAMS_PATH` for every `distro-params.yml` write in this
skill, including fast paths and failure paths. Never write
`distro-params.yml` inside `WORK_ROOT` or any of its child directories. If
the computed path would still be inside `WORK_ROOT`, stop and report the
path problem instead of writing an artifact that cleanup can delete. Use
the exported `BUILD_DISTRO_ROOT="$WORK_ROOT"` for the rest of the run so
later `cd` commands do not change the default clone root.

### meta-qcom only

This flow assumes the target layer is **meta-qcom**, not
meta-qcom-3rdparty — the `qcom-ptool.inc`/`SRCREV` dependency this skill
bridges is meta-qcom-specific. If the user names a meta-qcom-3rdparty
board, say so and offer to run `qcom-partition-conf-new-board` and
`qcom-yocto-new-machine` separately instead (meta-qcom-3rdparty boards
still get partition files and a machine conf, just not through this
chained flow).

## 0a. Existing meta-qcom PR fast path

Before cloning work directories or invoking `qcom-partition-conf-new-board` /
`qcom-yocto-new-machine`, check whether a meta-qcom PR already exists for the
standard branch `add/<machine>`:

```sh
curl -s \
  -H "Authorization: Bearer $GITHUB_TOKEN" \
  -H "Accept: application/vnd.github+json" \
  "https://api.github.com/repos/$DISTRO_GITHUB_ORG/meta-qcom/pulls?head=$DISTRO_GITHUB_ORG:add/<machine>&state=open"
```

If the response is a non-empty array, do not run the normal flow. Instead,
write `DISTRO_PARAMS_PATH` immediately and stop:

```yaml
status: "pass"

repo:        "https://github.com/$DISTRO_GITHUB_ORG/meta-qcom.git"
branch:      "master"
type:        "distro"

changes:
  - type: pr
    url: <existing meta-qcom PR html_url>

workspace:    ""
machine:      "<machine>"
distro:       "<distro>"
image:        "<image>"
build_config: "ci/<machine>.yml:ci/<distro>.yml"
```

`branch` is the meta-qcom PR's *base* branch (the one `build-distro` syncs and
builds from, per its Step 4) — not the PR's own head branch `add/<machine>`.
It must match the `base` value used when the PR was opened (step 2c uses
`"master"`); read it from the PR response's `base.ref` rather than
hardcoding it, in case the target repo's default branch differs.

This fast path exists so orchestrators can consume an already-open machine PR
without repeating the partition/machine-conf generation flow. If the response
is empty, continue to step 1 and run the normal flow. If GitHub returns `401`
or another API error, stop and report the error; do not guess whether a PR
exists.

## 1. Run `qcom-partition-conf-new-board`

Follow that skill's Sections 0-6 for the parsed `<machine>` exactly as documented —
this skill leaves the qcom-ptool PR open, it never merges it. Capture two things
from its result:

- The qcom-ptool PR's `html_url`.
- The PR's head commit `sha` (from the PR-creation response's `head.sha`,
  or `GET .../pulls/{number}` if you need to re-fetch it).

If that skill stops or fails at any point (missing board-spec entry,
`schema_errors`, a `401`/`422` from the GitHub API), **stop the whole
orchestration here** — report exactly what happened and do not proceed to
step 2 with a partial or failed partition leg.

## 2. Run `qcom-yocto-new-machine`

Follow that skill's Sections 0-10 for the parsed `<machine>` (target layer:
meta-qcom): prerequisites, board-spec lookup, template selection, machine
conf, FIT_DTB_COMPATIBLE entries, any new-SoC scaffold, CI yaml, and its
autopilot outstanding-items/generated-file summary. It must return after file
generation; do not ask it to run a build or validation step.

From this point on, this skill (not `qcom-yocto-new-machine`) drives
everything else: the `SRCREV` bump (step 2a), the build-retry loop (step
2b), pre-PR checks, and the commit + PR (step 2c).

### 2a. Bump `qcom-ptool.inc`'s `SRCREV`

Point the layer's `recipes-bsp/partition/qcom-ptool.inc` at the PR head
commit SHA captured in step 1. Since that commit lives only on the
still-open `add/<machine>` branch of the fork (not on `main`), add
`nobranch=1` to `SRC_URI` so bitbake's git fetcher checks out that exact
SHA directly rather than requiring it to be reachable from a named branch:

```sh
cd <meta-qcom-checkout>
sed -i \
  -e "s#^SRC_URI = .*#SRC_URI = \"git://github.com/\$DISTRO_GITHUB_ORG/qcom-ptool.git;protocol=https;nobranch=1\"#" \
  -e "s#^SRCREV = .*#SRCREV = \"<pr-head-commit-sha-from-step-1>\"#" \
  recipes-bsp/partition/qcom-ptool.inc
```

If the qcom-ptool PR is merged later (by hand) and `SRCREV` is moved to a
commit that's actually on `main`, `nobranch=1` should be dropped again and
`branch=main` restored — that's a follow-up edit for whoever merges it,
not something this skill does automatically.

This is its own atomic commit, separate from the `conf/machine: add
<machine>` commit (per `AGENTS.md`'s "each patch must be logically
coherent, self-contained" rule):

```sh
git add recipes-bsp/partition/qcom-ptool.inc
git commit -s -m "recipes-bsp/partition: point qcom-ptool at <machine> partitions PR"
```

### 2b. Build with diagnose/fix/retry

Skip the build (do not run `kas-container`, the diagnose/fix/retry loop, or
`yocto-patchreview.sh`/`yocto-check-layer.sh`) whenever either of the
following holds:

- `--skip-build` was passed, or
- this run is invoked as part of an orchestrating pipeline (see the
  invocation-context rule above).

In either case, print a clear warning explaining which condition caused the
skip, note the skip reason for the PR body (step 2c), and continue to step 2c.

Otherwise (standalone invocation, no `--skip-build`), run the first real
build after the machine files are generated and `qcom-ptool.inc` has been
bumped:

```sh
export KAS_YAMLS="ci/<machine>.yml:ci/<distro>.yml"
"${KAS_CONTAINER:-kas-container}" build "${KAS_YAMLS}" --target <image>
```

Record the actual build result (pass/fail; on failure, the tail of the
build log) — **this result gates step 2c next.**

If the build fails, diagnose the actual error from the log (bitbake's
`ERROR:` lines usually name the missing/broken recipe or dependency
directly) and attempt a fix:

- Prefer the smallest change that addresses the real cause — e.g. drop an
  RDEPENDS/RRECOMMENDS on a package that genuinely doesn't exist upstream
  yet, correct a typo'd recipe/package name, add a missing `require`, fix
  a bad `SRC_URI`/`SRCREV`/checksum. Don't paper over the error by deleting
  functionality beyond the specific broken reference. If the failure looks
  rooted in `qcom-yocto-new-machine`'s own written files (machine conf,
  FIT_DTB_COMPATIBLE entries, new-SoC include, recipes), fix those files
  directly rather than re-invoking that skill — it has no retry logic of
  its own to hand back into.
- Re-run the exact same build command after each fix attempt.
- Cap retries at 3 distinct fix attempts. If the build still fails after
  3 attempts, or if the root cause isn't something under this run's
  control (e.g. an upstream repo genuinely missing a package, a
  network/infra failure, a disk-space error), stop — do not keep
  iterating blindly. Skip step 2c (no commit/PR) and go to step 3 to write
  `distro-params.yml` with `status: "fail"`.
- Any fix applied here becomes part of the same commit(s) in step 2c —
  don't create separate "fixup" commits; the change that goes into the PR
  should look like it was written correctly the first time.

Once the build passes (whether on the first attempt or after a fix),
continue to step 2c.

If the build succeeds, also run:

```sh
ci/kas-container-shell-helper.sh ci/yocto-patchreview.sh
ci/kas-container-shell-helper.sh ci/yocto-check-layer.sh
```

before opening or updating the pull request.

### 2c. Commit and open the meta-qcom PR

Only reachable after step 2b's build succeeded, or when step 2b skipped the
build (either because `--skip-build` was passed or this run is invoked as
part of an orchestrating pipeline). Do not commit or open/update a PR off a
failed build. When step 2b skipped the build, make the skipped validation
visible in the PR body and in `distro-params.yml`.

Commit following meta-qcom's `CONTRIBUTING.md`/`AGENTS.md`: split the
change into logically separate, independently buildable commits rather
than one bundled commit — this mirrors the "avoid mixing unrelated
changes" / "each patch must be logically coherent, self-contained, and
independently buildable" rule. A typical new-machine change decomposes
along the recipe boundaries `qcom-yocto-new-machine` wrote (its Sections
4-8), in dependency order so the tree stays buildable after every commit
even though the machine only becomes selectable once the final commit
lands:

1. **New SoC plumbing** (only if a new SoC include was scaffolded) — the
   new `conf/machine/include/qcom-<soc>.inc` plus its
   `packagegroup-machine-essential-qcom-<soc>-soc` entry in
   `recipes-bsp/packagegroups/packagegroup-machine-essential.bb`. Subject:
   `conf/machine: add <soc> SoC family`.
2. **Boot/CDT firmware recipes** — the
   `firmware-qcom-boot-<soc-or-board>.inc`/`.bb` and
   `firmware-qcom-cdt-<soc-or-board>.bb` pair. Subject:
   `recipes-bsp/firmware-boot: add <soc-or-board> boot and CDT firmware recipes`.
3. **Board packagegroup** — the `packagegroup-<board>.bb` recipe. Subject:
   `recipes-bsp/packagegroups: add packagegroup-<board>`.
4. **The machine itself** — `conf/machine/<machine>.conf`, its
   `FIT_DTB_COMPATIBLE` entries in
   `conf/machine/include/fit-dtb-compatible.inc`, and `ci/<machine>.yml`.
   This is the commit that wires everything above together and is the
   point at which the machine becomes selectable/buildable, so it must
   land last. Subject: `conf/machine: add <machine>`.
5. **The SRCREV bump** (step 2a) — already its own commit; land it after
   commit 4 since it depends on the machine's `QCOM_PARTITION_FILES_SUBDIR`
   (set in commit 4) actually pointing at the PR'd partitions.

Commits 1-3 add recipes nothing references yet, so they don't change any
existing machine's behavior — safe to land independently of each other,
but all three must precede commit 4. Skip a slot here the same way its
corresponding write step was skipped (no new SoC → no commit 1; board
reuses an existing packagegroup pattern instead of a new one → fold into
commit 4 rather than inventing a split that isn't there). For a small/
simple addition (existing SoC, no new firmware, no new packagegroup), it
is fine to collapse to just commit 4 + commit 5 — logical separation means
matching commit boundaries to genuinely distinct pieces of work, not
hitting a fixed commit count.

For each commit: `git add` only the files for that piece, plain-English
body explaining what and why for anything non-trivial, and a
`Signed-off-by` trailer built from `git config user.name`/`user.email` —
never fabricate identity. Add `Assisted-by: AGENT_NAME:MODEL_VERSION` if an
AI assistant helped write the change.

```sh
cd <meta-qcom-checkout>
git fetch origin master
git checkout -b add/<machine> origin/master
# repeat per commit in the split above:
git add <files for this commit>
git status   # confirm nothing unrelated got swept in
git commit -s -m "<subject for this commit>"
git push origin add/<machine>
```

Never `git commit --amend` or otherwise rewrite a commit already made in
this series to fix a mistake — fix it in a new commit ahead of the same
push, per `AGENTS.md`'s "fixups within the same patch series are not
allowed" rule (where that rule exists; otherwise still prefer a new commit
over rewriting one already pushed).

- Branch name is always `add/<machine>`. If it already exists on `origin`
  without an open PR, stop and ask the user whether to force-push an update
  or pick a different branch name — never force-push silently.
- Before pushing, re-check whether a PR already exists for this branch to
  guard against a race with another run:
  ```sh
  curl -s -H "Authorization: Bearer $GITHUB_TOKEN" -H "Accept: application/vnd.github+json" \
    "https://api.github.com/repos/$DISTRO_GITHUB_ORG/meta-qcom/pulls?head=$DISTRO_GITHUB_ORG:add/<machine>&state=open"
  ```
  A non-empty array means one's already open. Write the same
  `distro-params.yml` fast-path artifact described in step 0a to
  `DISTRO_PARAMS_PATH`, report its `html_url`, and stop instead of
  creating a second PR.

Then open the PR against `$DISTRO_GITHUB_ORG/meta-qcom`'s default branch
via the GitHub REST API (no `gh` CLI or browser step needed):

```sh
curl -s -X POST \
  -H "Authorization: Bearer $GITHUB_TOKEN" \
  -H "Accept: application/vnd.github+json" \
  "https://api.github.com/repos/$DISTRO_GITHUB_ORG/meta-qcom/pulls" \
  -d @- <<EOF
{
  "title": "conf/machine: add <machine>",
  "head": "add/<machine>",
  "base": "master",
  "body": "Adds <machine> (<SoC>) via the distro-smith skill.\n\nValidated locally with kas-container build, yocto-patchreview.sh, and yocto-check-layer.sh.",
  "draft": false
}
EOF
```

If step 2b skipped the build, use this PR body instead:

```json
{
  "title": "conf/machine: add <machine>",
  "head": "add/<machine>",
  "base": "master",
  "body": "Adds <machine> (<SoC>) via the distro-smith skill.\n\nValidation skipped (--skip-build or orchestrating pipeline invocation); kas-container build, yocto-patchreview.sh, and yocto-check-layer.sh were not run.",
  "draft": false
}
```

- A `201` response with an `html_url` field means the PR was created —
  report that URL back to the user.
- A `422` usually means the branch has no diff against `base` (nothing to
  PR) or a PR already exists — read the `message`/`errors` fields and
  surface them rather than retrying blindly.
- If `GITHUB_TOKEN` is missing/invalid (`401`), stop and tell the user to
  re-check the env var prerequisite — don't fall back to printing a manual
  "go create this PR yourself" message as a silent default.
- This PR lands on the user's own fork first (a staging step, same
  philosophy as `qcom-partition-conf-new-board`) — merging it upstream into
  `qualcomm-linux/meta-qcom` is a separate, manual follow-up; don't do that
  without the user asking.

## 3. Write `distro-params.yml`

Always write this file, whether step 2b's build ultimately passed or
failed. Write it to `DISTRO_PARAMS_PATH`, computed in step 0 before any
checkout work starts. That path must be outside `WORK_ROOT`
(`${BUILD_DISTRO_ROOT:-<original-cwd>/.distrosmith-work}`), so a successful
cleanup cannot delete the artifact.

On a successful build + PR (step 2c ran):

```yaml
status: "pass"

repo:        "https://github.com/$DISTRO_GITHUB_ORG/meta-qcom.git"
branch:      "master"
type:        "distro"

changes:
  - type: pr
    url: <qcom-ptool PR html_url from step 1>
  - type: pr
    url: <meta-qcom PR html_url from step 2c>
  # Add more changes below (applied in listed order):
  # - type: pr
  #   url: https://github.com/qualcomm-linux/meta-qcom/pull/2717
  # - type: commit
  #   url: https://github.com/qualcomm-linux/meta-qcom/commit/abc1234
  # - type: patch
  #   path: /home/user/fixes/fix-audio.patch

workspace:    "<local meta-qcom checkout path used>"
machine:      "<machine>"
distro:       "<distro>"
image:        "<image>"
build_config: "<KAS_YAMLS value used, e.g. ci/<machine>.yml:ci/<distro>.yml>"
```

- List every PR/commit the whole chain produced, in the order they were
  opened: the qcom-ptool PR first, then the meta-qcom PR. Both are left
  open, not merged.
- `branch` is the meta-qcom PR's base branch (`"master"`, matching step 2c's
  PR-creation `base` field) — the branch `build-distro` checks out and
  applies the PR onto — not the PR's own head branch `add/<machine>`.
- `workspace`/`machine`/`distro`/`image`/`build_config` are filled with
  the actual values already known at this point, not left blank.

On a successful PR with the build skipped (`--skip-build` or an orchestrating
pipeline invocation):

```yaml
status: "pass"

repo:        "https://github.com/$DISTRO_GITHUB_ORG/meta-qcom.git"
branch:      "master"
type:        "distro"

changes:
  - type: pr
    url: <qcom-ptool PR html_url from step 1>
  - type: pr
    url: <meta-qcom PR html_url from step 2c>

workspace:    "<local meta-qcom checkout path used>"
machine:      "<machine>"
distro:       "<distro>"
image:        "<image>"
build_config: "ci/<machine>.yml:ci/<distro>.yml"
```

This is still `status: "pass"` so qli-orchestrator can consume it and invoke
`build-distro` — build-distro runs its own real build regardless of
whether distro-smith's internal build ran, so the skip here isn't recorded
in `distro-params.yml` itself; it's already visible in the PR body (step 2c).

On a failed build (step 2b's retry cap was exhausted):

```yaml
status: "fail"

repo:        "https://github.com/$DISTRO_GITHUB_ORG/meta-qcom.git"
branch:      "master"
type:        "distro"

changes: []

workspace:    "<local meta-qcom checkout path used>"
machine:      "<machine>"
distro:       "<distro>"
image:        "<image>"
build_config: "<KAS_YAMLS value used>"
```

`machine`/`distro`/`image`/`build_config` stay filled in even on failure —
those are known regardless of whether the build succeeded; only `changes`
is empty since nothing was committed or opened.

## 4. Clean up the clone work directory

Both underlying skills clone into `WORK_ROOT`
(`${BUILD_DISTRO_ROOT:-<original-cwd>/.distrosmith-work}` by default; see
each skill's Section 0) — a directory under this invocation's original cwd,
not `/tmp`. Once `DISTRO_PARAMS_PATH` is written (step 3), and only on a
`status: "pass"` run, remove that work directory:

```sh
rm -rf "$WORK_ROOT"
```

- Before deleting anything, verify `DISTRO_PARAMS_PATH` is outside
  `WORK_ROOT`. If it is inside `WORK_ROOT`, move the file to
  `$(dirname "$WORK_ROOT")/distro-params.yml` and update
  `DISTRO_PARAMS_PATH` before removing `WORK_ROOT`.
- On `status: "fail"`, leave the work directory in place instead — a
  failed build's checkout (source tree, build logs under
  `<layer-checkout>/build/tmp/log/`, bitbake's parsed state) is exactly
  what's needed to debug the failure further, whether that's this agent
  continuing after reporting, or the user inspecting it by hand. Don't
  delete it just because the run ended.
- Only `distro-smith` does this. When either underlying skill is invoked
  standalone (not through this orchestrator), it leaves its checkout in
  place — see each skill's Section 0 — since standalone runs are expected
  to be followed by more manual work against that same checkout.
- If `BUILD_DISTRO_ROOT` was explicitly set by the user to a path outside
  the default (e.g. an existing checkout they already had before this
  run), don't delete it — only remove the directory this run itself
  created under the default `$(pwd)/.distrosmith-work` location.

## Notes

- Run the build by default on a standalone invocation — the entire point of
  this skill over running the two skills manually is that the build is real
  and gates the PR. Only skip it when `--skip-build` is passed or this run is
  invoked as part of an orchestrating pipeline (see step 2b).
- A failed build gets one diagnose-and-fix pass (capped at 3 attempts,
  handled inside this skill's own step 2b) before this orchestration is
  treated as failed.
- Never guess `DISTRO_GITHUB_ORG` — both underlying skills already stop
  and ask if it's unset; don't paper over that by guessing at this
  orchestration layer either.
- Report progress at each step boundary (partition PR opened, SRCREV
  bumped, build result, meta-qcom PR opened or build failed) rather than
  going silent until the very end — a real build can take a long time.
- Neither this skill nor `qcom-partition-conf-new-board` ever merges the
  qcom-ptool PR, whether the meta-qcom build against it passes or fails —
  merging it (into the fork, and separately upstream) is always a manual
  decision left to the user.
