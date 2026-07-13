---
name: distro-smith
description: >-
  End-to-end distro bring-up for a board: generate and merge its
  qcom-ptool partition files, bump meta-qcom's qcom-ptool.inc SRCREV to
  that merged commit, trigger a real kas-container build targeting
  qcom-multimedia-image, and — only if the build succeeds — commit and
  open the meta-qcom PR. Always writes the run's result to
  distro-params.yaml. Stitches together qcom-partition-conf-new-board and
  qcom-yocto-new-machine into one invocation. Use for "run the build
  distro skill for <machine>", "do the full distro flow for <machine>",
  or "run distro-smith for <machine>". Do NOT use for just the partition
  files (use qcom-partition-conf-new-board alone) or just the machine conf
  (use qcom-yocto-new-machine alone) — this skill exists specifically to
  chain both together with a real gated build in between.
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

Automatically fixing a build failure is explicitly out of scope — on
failure, stop and report; do not retry, patch, or iterate.

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
- Its Section 10 (real build, `--target qcom-multimedia-image`).

If the build fails, that skill's own gate stops it before committing or
opening a PR — do not override that gate. Skip ahead to step 3 below with
an overall `status: "fail"`.

If the build succeeds, let that skill continue into its Section 11
(commit + open the meta-qcom PR). Capture the meta-qcom PR's `html_url`.

## 3. Write `distro-params.yaml`

This is `qcom-yocto-new-machine`'s own Section 12 — by the time it runs,
that skill already has both PR URLs (qcom-ptool from step 1, meta-qcom
from step 2) and the real `machine`/`distro`/`image`/`build_config`
values, so no extra work is needed here beyond letting it write the file.
Confirm it's written at the directory this `distro-smith` invocation was
started from (the invocation cwd), listing both changes in order: the
qcom-ptool merge first, the meta-qcom PR second.

## Notes

- Never skip the build step — the entire point of this skill over running
  the two skills manually is that the build is real and gates the PR.
- Never attempt to automatically fix a build failure — report it and stop,
  per the explicit scope limit on this whole flow.
- Never guess `DISTRO_GITHUB_ORG` — both underlying skills already stop
  and ask if it's unset; don't paper over that by guessing at this
  orchestration layer either.
- Report progress at each step boundary (partition PR merged, SRCREV
  bumped, build result, meta-qcom PR opened or build failed) rather than
  going silent until the very end — a real build can take a long time.
