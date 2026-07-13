---
name: distro-smith
description: >-
  End-to-end distro bring-up for a board: generate and merge its
  qcom-ptool partition files, bump meta-qcom's qcom-ptool.inc SRCREV to
  that merged commit, trigger a real kas-container build (whatever image
  qcom-yocto-new-machine's Section 10 targets, attempting a fix and retry
  if it fails), and — only once the build succeeds — commit and open the
  meta-qcom PR. Always writes the run's result to distro-params.yaml, and
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

This skill is a thin sequencer: it does not repeat either skill's
instructions, only threads state between them. The two `SKILL.md` files
remain the source of truth for their own steps and prerequisites (env
vars, checkout locations — see each one's Section 0).

A failed build is not immediately fatal — `qcom-yocto-new-machine`'s own
Section 10 now diagnoses and attempts a fix (capped at 3 attempts) before
giving up. This orchestrator doesn't duplicate that logic; it just relies
on that skill's gate to decide whether Section 11 (commit + PR) is
reachable this run.

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
this now includes the auto-merge step (Section 6). Capture two things
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

Follow that skill's Sections 0-8 for `<machine>` (target layer:
meta-qcom), then:

- Its Section 9 (bump `qcom-ptool.inc`'s `SRCREV`), passing the merge
  commit SHA captured in step 1.
- Its Section 10 (real build, including its diagnose/fix/retry loop on
  failure — the `--target` is that skill's own default, not this
  orchestrator's decision to restate).

If the build still fails after that skill's retry cap is exhausted, its
own gate stops it before committing or opening a PR — do not override
that gate by forcing a commit/PR through some other path. Skip ahead to
step 3 below with an overall `status: "fail"`.

If the build succeeds (whether on the first attempt or after a fix), let
that skill continue into its Section 11 (commit + open the meta-qcom PR).
Capture the meta-qcom PR's `html_url`.

## 3. Write `distro-params.yaml`

This is `qcom-yocto-new-machine`'s own Section 12 — by the time it runs,
that skill already has both PR URLs (qcom-ptool from step 1, meta-qcom
from step 2) and the real `machine`/`distro`/`image`/`build_config`
values, so no extra work is needed here beyond letting it write the file.
Confirm it's written at the directory this `distro-smith` invocation was
started from (the invocation cwd), listing both changes in order: the
qcom-ptool merge first, the meta-qcom PR second.

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
  handled inside `qcom-yocto-new-machine`'s Section 10) before this
  orchestrator treats the run as failed — see step 2.
- Never guess `DISTRO_GITHUB_ORG` — both underlying skills already stop
  and ask if it's unset; don't paper over that by guessing at this
  orchestration layer either.
- Report progress at each step boundary (partition PR merged, SRCREV
  bumped, build result, meta-qcom PR opened or build failed) rather than
  going silent until the very end — a real build can take a long time.
