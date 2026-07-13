---
name: distro-smith
description: >-
  End-to-end distro bring-up for a board: generate and merge its
  qcom-ptool partition files, bump meta-qcom's qcom-ptool.inc SRCREV to
  that merged commit, trigger a real kas-container build (whatever image
  qcom-yocto-new-machine's Section 10 targets, attempting a fix and retry
  if it fails), and — only once the build succeeds — commit and open the
  meta-qcom PR. This skill (not qcom-yocto-new-machine) owns the SRCREV
  bump, the build-retry loop, the PR automation, and distro-params.yaml —
  qcom-yocto-new-machine only gets a board as far as a single, non-retrying
  build attempt. Always writes the run's result to distro-params.yaml, and
  on a successful run cleans up its own clone work directory once that
  file is written
  (failed runs keep the work directory for debugging). Stitches together
  qcom-partition-conf-new-board and qcom-yocto-new-machine into one
  invocation. Use for "run the build distro skill for <machine>", "do the
  full distro flow for <machine>", or "run distro-smith for <machine>". Do
  NOT use for just the partition files (use qcom-partition-conf-new-board
  alone) or just the machine conf (use qcom-yocto-new-machine alone) —
  this skill exists specifically to chain both together with a real gated
  build in between.
---

# Run the full distro-smith flow for a board

Sequences `qcom-partition-conf-new-board` and `qcom-yocto-new-machine` so
one invocation ("run distro-smith for `<machine>`") takes a board from its
board-spec entry all the way to a merged qcom-ptool PR, a real build, and
(on success) an open meta-qcom PR — ending in one `distro-params.yaml`
that reports what happened.

`qcom-yocto-new-machine` only writes the machine conf, CI yaml, and
supporting recipes, then runs a single non-retrying build (its own Section
10) to sanity-check the result. Everything past that — bumping
`qcom-ptool.inc`'s `SRCREV`, retrying a failed build with a fix, committing,
opening the meta-qcom PR, and writing `distro-params.yaml` — is this
skill's own responsibility, not `qcom-yocto-new-machine`'s. That skill's
own `SKILL.md` remains the source of truth for its own steps and
prerequisites (env vars, checkout locations — see its Section 0).

## 0. Scope check: meta-qcom only

This flow assumes the target layer is **meta-qcom**, not
meta-qcom-3rdparty — the `qcom-ptool.inc`/`SRCREV` dependency this skill
bridges is meta-qcom-specific. If the user names a meta-qcom-3rdparty
board, say so and offer to run `qcom-partition-conf-new-board` and
`qcom-yocto-new-machine` separately instead (meta-qcom-3rdparty boards
still get partition files and a machine conf, just not through this
chained flow).

## 1. Run `qcom-partition-conf-new-board`

Follow that skill's Sections 0-6 for `<machine>` exactly as documented —
this includes the auto-merge step (Section 6). Capture two things
from its result:

- The qcom-ptool PR's `html_url`.
- The merge commit `sha` (from the `PUT .../pulls/{number}/merge`
  response).

If that skill stops or fails at any point (missing board-spec entry,
`schema_errors`, a real merge conflict, a `401`/`422` from the GitHub
API), **stop the whole orchestration here** — report exactly what
happened and do not proceed to step 2 with a partial or failed partition
leg.

## 2. Run `qcom-yocto-new-machine`

Follow that skill's Sections 0-9 for `<machine>` (target layer:
meta-qcom): prerequisites, board-spec lookup, template selection, machine
conf, FIT_DTB_COMPATIBLE entries, any new-SoC scaffold, CI yaml, and its
autopilot outstanding-items summary. Then follow its Section 10 to trigger
one real `kas-container build` — that skill stops there, reporting
pass/fail back to this orchestrator without retrying, committing, or
opening a PR itself.

From this point on, this skill (not `qcom-yocto-new-machine`) drives
everything else: the `SRCREV` bump (step 2a), the build-retry loop (step
2b), and the commit + PR (step 2c).

### 2a. Bump `qcom-ptool.inc`'s `SRCREV`

Point the layer's `recipes-bsp/partition/qcom-ptool.inc` at the merge
commit SHA captured in step 1:

```sh
cd <meta-qcom-checkout>
sed -i \
  -e "s#^SRC_URI = .*#SRC_URI = \"git://github.com/\$DISTRO_GITHUB_ORG/qcom-ptool.git;branch=main;protocol=https\"#" \
  -e "s#^SRCREV = .*#SRCREV = \"<merged-commit-sha-from-step-1>\"#" \
  recipes-bsp/partition/qcom-ptool.inc
```

This is its own atomic commit, separate from the `conf/machine: add
<machine>` commit (per `AGENTS.md`'s "each patch must be logically
coherent, self-contained" rule):

```sh
git add recipes-bsp/partition/qcom-ptool.inc
git commit -s -m "recipes-bsp/partition: point qcom-ptool at merged <machine> partitions"
```

### 2b. Build with diagnose/fix/retry

If step 2's build (via `qcom-yocto-new-machine`'s Section 10) already
passed before the SRCREV bump above, re-run it now that
`qcom-ptool.inc` has changed:

```sh
export KAS_YAMLS="ci/<machine>.yml:ci/qcom-distro.yml"
"${KAS_CONTAINER:-kas-container}" build "${KAS_YAMLS}" --target qcom-console-image
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
  `distro-params.yaml` with `status: "fail"`.
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

**Only reachable after step 2b's build succeeded** — do not commit or
open/update a PR off a failed or skipped build.

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
   (set in commit 4) actually pointing at the merged partitions.

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
  (e.g. a prior run for this board), stop and ask the user whether to
  force-push an update or pick a different branch name — never force-push
  silently.
- Before pushing, check whether a PR already exists for this branch to
  avoid opening a duplicate:
  ```sh
  curl -s -H "Authorization: Bearer $GITHUB_TOKEN" -H "Accept: application/vnd.github+json" \
    "https://api.github.com/repos/$DISTRO_GITHUB_ORG/meta-qcom/pulls?head=$DISTRO_GITHUB_ORG:add/<machine>&state=open"
  ```
  A non-empty array means one's already open — report its `html_url` back
  to the user instead of creating a second one.

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

## 3. Write `distro-params.yaml`

Always write this file, whether step 2b's build ultimately passed or
failed — write it in the directory this `distro-smith` invocation was
started from (the invocation cwd, not the `BUILD_DISTRO_ROOT` checkout).

On a successful build + PR (step 2c ran):

```yaml
status: "pass"

repo:        "https://github.com/$DISTRO_GITHUB_ORG/meta-qcom.git"
branch:      "add/<machine>"
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
distro:       "qcom-distro"
image:        "<image built in step 2b, e.g. qcom-console-image>"
build_config: "<KAS_YAMLS value used, e.g. ci/<machine>.yml:ci/qcom-distro.yml>"
```

- List every PR/commit the whole chain produced, in the order they were
  applied: the qcom-ptool merge first, then the meta-qcom PR.
- `workspace`/`machine`/`distro`/`image`/`build_config` are filled with
  the actual values already known at this point, not left blank.

On a failed build (step 2b's retry cap was exhausted):

```yaml
status: "fail"

repo:        "https://github.com/$DISTRO_GITHUB_ORG/meta-qcom.git"
branch:      "add/<machine>"
type:        "distro"

changes: []

workspace:    "<local meta-qcom checkout path used>"
machine:      "<machine>"
distro:       "qcom-distro"
image:        "<image built in step 2b, e.g. qcom-console-image>"
build_config: "<KAS_YAMLS value used>"
```

`machine`/`distro`/`image`/`build_config` stay filled in even on failure —
those are known regardless of whether the build succeeded; only `changes`
is empty since nothing was committed or opened.

## 4. Clean up the clone work directory

Both underlying skills clone into `${BUILD_DISTRO_ROOT:-$(pwd)/.distrosmith-work}`
by default (see each skill's Section 0) — a directory under this
invocation's cwd, not `/tmp`. Once `distro-params.yaml` is written
(step 3), and only on a `status: "pass"` run, remove that work directory:

```sh
rm -rf "${BUILD_DISTRO_ROOT:-$(pwd)/.distrosmith-work}"
```

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

- Never skip the build step — the entire point of this skill over running
  the two skills manually is that the build is real and gates the PR.
- A failed build gets one diagnose-and-fix pass (capped at 3 attempts,
  handled inside this skill's own step 2b) before this orchestration is
  treated as failed.
- Never guess `DISTRO_GITHUB_ORG` — both underlying skills already stop
  and ask if it's unset; don't paper over that by guessing at this
  orchestration layer either.
- Report progress at each step boundary (partition PR merged, build
  result, SRCREV bumped, meta-qcom PR opened or build failed) rather than
  going silent until the very end — a real build can take a long time.
