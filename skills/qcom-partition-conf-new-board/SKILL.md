---
name: qcom-partition-conf-new-board
description: >-
  Generate qcom-ptool's partitions.conf and contents.xml.in for a new
  board, driven by the board-spec MCP server (one git branch per machine
  in a board-spec repo, schema-validated, split into
  machine.yaml + partition.yaml per board) as the single source of truth,
  then locally run qcom-ptool to validate they produce correct flashable
  artifacts (partitions.xml, gpt_main*.bin, gpt_backup*.bin,
  rawprogram*.xml, patch*.xml, contents.xml) — those generated artifacts
  are validation-only and never committed; only partitions.conf/
  contents.xml.in go in the PR. Once validated, automatically commits
  those two files to a new `add/<machine>` branch, opens a PR against the
  configured qcom-ptool fork (`$DISTRO_GITHUB_ORG/qcom-ptool` — see
  Section 0) via the GitHub REST API, and merges it — no manual git push,
  browser step, or manual merge required. meta-qcom regenerates the real flashable artifacts at build
  time (see Section 7) and copies them into <image>.qcomflash/ via
  classes-recipe/image_types_qcom.bbclass's deploy_partition_files. Use
  when asked to "generate the partition files for <board>", "create
  partitions.conf from the board spec", "produce the qcomflash XMLs for
  <board>", or "open a PR for <board>'s partition layout". Do NOT use for
  authoring the board-spec entry itself (that's a prerequisite, done by
  hand and merged via PR into the board-spec repo — see that repo's
  README), for meta-qcom machine.conf/CI bring-up (see
  qcom-yocto-new-machine), or for flashing/validating on real hardware
  (see qcom-flash-qdl, qcom-boot-validate).
---

# Generate partition files for a new board from its board-spec entry

Turns a schema-validated board-spec entry (served by the `board-spec` MCP
server, backed by a `board-spec` git repo — one branch per machine, each
holding `boards/<machine>/machine.yaml` + `boards/<machine>/partition.yaml`)
into the files `qcom-ptool` needs to produce a board's flashable partition
artifacts, runs `qcom-ptool` to actually produce them, then opens and
merges a PR with just the source files against the configured qcom-ptool
fork. The board-spec entry is the only source of partition facts this skill trusts
— never invent a size, GUID, or chip ID that isn't in the spec or copied
verbatim from a reference board. When the spec has no `reference_board`
(a `null` value is valid and common), pick any existing board's files as
the structural template for the header/boilerplate — never ask the user
to name one.

This skill is part of the `distrosmith` bundle — see that repo's
`README.md` for the one-time `setup.py` install step that provisions the
env vars below and clones the repos this skill needs.

## 0. Prerequisites

- **`DISTRO_GITHUB_ORG`** must be exported in the shell environment — the
  GitHub org or user account that hosts *all* of this user's
  `distrosmith`-managed forks (`meta-qcom`, `qcom-ptool`, `board-spec`,
  `board-spec-mcp`), always under those exact repo names (e.g.
  `roshs189/qcom-ptool`). This is what makes the skill portable across
  forks/environments instead of hardcoding one org. If it's unset, stop
  and ask the user for it rather than guessing or falling back to a
  previously seen org — this value is what determines whose repo gets a
  branch pushed and a PR opened against it. Resolve the target repo as:
  ```sh
  QCOM_PTOOL_TARGET="$DISTRO_GITHUB_ORG/qcom-ptool"
  ```
- **`GITHUB_TOKEN`** must be exported in the shell environment (a GitHub
  PAT — classic with `repo` scope, or fine-grained with `Contents:
  Read and write` + `Pull requests: Read and write` on
  `$QCOM_PTOOL_TARGET`). This skill never touches SSH keys — `GITHUB_TOKEN`
  covers both git push/fetch (over HTTPS) and the GitHub REST API that
  opening a PR requires. If it's unset, stop and ask the user to set it
  (see the `distrosmith` README, or ask them to generate one at
  https://github.com/settings/tokens) rather than falling back to
  printing manual instructions — automatic PR creation is this skill's
  job, not a fallback path.
  ```sh
  curl -s -H "Authorization: Bearer $GITHUB_TOKEN" https://api.github.com/user
  ```
  A `login` field in the response confirms the token works before you rely
  on it later.
- **`BUILD_DISTRO_ROOT`** (optional, defaults to
  `$(pwd)/.distrosmith-work` — a work directory under the invocation cwd,
  not `/tmp`) — the local root directory under which the qcom-ptool
  checkout lives: `${BUILD_DISTRO_ROOT:-$(pwd)/.distrosmith-work}/qcom-ptool`.
  This keeps `distrosmith`-managed clones separate from any other
  qcom-ptool checkout the user already has elsewhere. If a checkout
  already exists at that path, use it as-is; only ask the user for a
  different path if they say their checkout lives somewhere else. When
  this skill runs standalone (not via `distro-smith`), leave this checkout
  in place when done — it's reused by follow-up work (see Notes); only
  `distro-smith`'s own orchestration removes it, and only after that
  flow's `distro-params.yaml` is written.
- The local `qcom-ptool` checkout's `origin` remote must be
  `$QCOM_PTOOL_TARGET` (the fork the PR gets opened against), not the
  upstream `qualcomm-linux/qcom-ptool`. If cloning fresh, clone the fork
  over HTTPS using the token (no SSH key needed):
  ```sh
  git clone "https://$GITHUB_TOKEN@github.com/$QCOM_PTOOL_TARGET.git" "${BUILD_DISTRO_ROOT:-$(pwd)/.distrosmith-work}/qcom-ptool"
  ```
  If an existing checkout's `origin` points somewhere else (upstream, or a
  different org than `$DISTRO_GITHUB_ORG`), either re-point it
  (`git remote set-url origin https://github.com/$QCOM_PTOOL_TARGET.git`)
  or add it as a second remote — confirm with the user which they want,
  since rewriting `origin` on a checkout they already use is a visible
  side effect. Verify the actual remote matches before pushing:
  ```sh
  git -C <qcom-ptool> remote get-url origin
  ```

## 1. Fetch the board spec and locate the qcom-ptool checkout

Call the `board-spec` MCP tools for the target machine:

- `list_boards()` — confirm the machine has a spec branch. If it doesn't,
  stop and tell the user: a new board's spec must be authored and merged
  into the board-spec repo first (by hand, reviewed via PR, as
  `machine.yaml` + `partition.yaml` — this skill never writes to that
  repo), before partition files can be generated from it.
- `get_board_spec(machine)` — full spec, merged from both halves (or
  `get_partition_conf_fields`/`get_machine_creation_fields` individually
  if you only need one half — these read `partition.yaml`/`machine.yaml`
  respectively, but the tool names and return shapes are unchanged from
  before the split, so nothing else in this workflow needs to know the
  data lives in two files).
- `validate_board_spec(machine)` — run this before trusting the spec;
  surfaces `schema_errors` (must fix before continuing, each prefixed
  `machine.yaml:` or `partition.yaml:` to say which half failed) and
  `warnings` (raise to the user, don't silently override — this now
  includes a separate check that each half's own `machine:` field matches
  the branch name, since they're two files that could drift independently).

The returned `partition_conf` object supplies everything the old Confluence
"Board Identity / Disk Configuration / Partition Table / contents.xml.in
Metadata" sections used to:

1. `machine`, `soc`, `reference_board`, `machine_creation.partition_files_subdir`
   — equivalent to the old **Board Identity** table.
2. `partition_conf.disk` — a single `--disk` line, equivalent to
   **Disk Configuration**.
3. `partition_conf.partitions` — a list of objects (`lun`, `name`, `size`,
   `type_guid`, `filename`, `attributes`, `readonly`, `sparse`, `delta`
   (`copy`|`new`), `notes`), equivalent to the old **Partition Table** rows,
   already in LUN-ascending order.
4. `partition_conf.contents_xml_in` — `null`/absent (reuse reference
   board's `contents.xml.in` unchanged) or an object with `product_name`,
   `chip_id_default`, `additional_chip_ids`, `build_flavors`, equivalent to
   the old **contents.xml.in Metadata** table.

The local `qcom-ptool` clone location defaults per Section 0
(`${BUILD_DISTRO_ROOT:-$(pwd)/.distrosmith-work}/qcom-ptool`) — only ask the
user if they've indicated their checkout lives elsewhere. Also ask (don't
guess) the machine name to use for the new branch/PR if it differs from
the board-spec `machine` name (default: same name).

If `refresh_specs()` might be stale (e.g. the user just merged a spec PR),
call it before `get_board_spec`/`validate_board_spec` to force a fetch of
the latest branch state.

## 2. Validate the spec before writing anything

`validate_board_spec(machine)` already runs most of this server-side —
treat any `schema_errors` as blocking and any `warnings` as things to
raise with the user, not silently override. Specifically it checks:

- Every `delta: new` partition has a `notes` justification, and doesn't
  collide with a SoC-mandated name (`xbl`, `tz`, `hyp`, `aop`, `devcfg`,
  `cpucp`, `persist`, etc. — fixed by the boot ROM/XBL contract, not board
  choices).
- `machine_creation.partition_files_subdir` equals
  `partitions/<machine>/<storage_type>` (a real mismatch here broke a
  build in a prior board bring-up — see Section 7).
- Chip-ID collisions across all other board branches in the repo.

Still do these two checks locally, since they depend on the qcom-ptool
checkout the MCP server doesn't have visibility into:

- If the spec's `contents_xml_in.chip_id_default`/`additional_chip_ids`
  represent a genuinely new chip ID, confirm it doesn't already exist in
  the qcom-ptool checkout itself (belt-and-suspenders beyond the
  cross-branch check above, in case qcom-ptool has chip IDs never captured
  in a board-spec branch):
  ```sh
  grep -rn "<CHIPID>" <qcom-ptool>/platforms/*/*/contents.xml.in
  ```
  A hit means either the spec is wrong (reusing an existing chip ID) or
  there's a real naming collision to raise with the user.
- If `reference_board` is populated, confirm its path actually exists in the
  qcom-ptool checkout (`ls <qcom-ptool>/platforms/<ref-board>/<storage>/`) —
  `validate_board_spec` only warns if the board is missing across other
  spec branches, it can't see the qcom-ptool filesystem.
- If `reference_board` is `null` (no single reference board applies), pick
  any existing board in the qcom-ptool checkout as the structural
  template — prefer one with the same `storage_type` if available, but the
  `partitions.conf` header and `contents.xml.in` boilerplate are identical
  across every board in the repo, so which one you pick doesn't materially
  matter. Never ask the user which board to copy this boilerplate from —
  that's your call to make, not theirs.

## 3. Write `partitions.conf`

Path: `<qcom-ptool>/platforms/<machine>/<storage>/partitions.conf`.

- Copy the standard header (copyright + SPDX + the `--disk`/`--partition`
  flag-reference comment block) verbatim from the reference board's
  `partitions.conf` — or, if `reference_board` is `null`, from any existing
  board's `partitions.conf` (see Section 2); every existing file in the
  repo uses the identical block, don't reword it.
- Emit `partition_conf.disk` verbatim as the `--disk` line.
- Emit one `--partition` line per entry in `partition_conf.partitions`,
  **in list order** (already grouped by LUN ascending):
  ```
  --partition --lun=<lun> --name=<name> --size=<size> --type-guid=<type_guid>[ --filename=<filename>][ --attributes=<attributes>][ --readonly=<readonly>][ --sparse=<sparse>]
  ```
  - Omit `--lun` entirely when `storage_type` is `emmc`/`nand`/`nvme`/
    `spinor` (LUN only applies to `ufs` — see `qcom_ptool/gen_partition.py`
    `partition_options`, which defaults `phys_part` to `0` when absent).
  - Omit any optional flag (`--filename`, `--attributes`, `--readonly`,
    `--sparse`) whose field is `null`; `gen_partition.py`'s
    `partition_entry_defaults` already fills `filename=""`,
    `attributes` unset, `readonly=true`, `sparse=false`.
  - `size` values keep their unit suffix as given (`524288KB`, `4KB`,
    etc.) — `gen_partition.py`'s `partition_size_in_kb()` parses
    `KB`/`MB`/`GB` (case-insensitive) or a bare byte count.

## 4. Write `contents.xml.in`

Path: `<qcom-ptool>/platforms/<machine>/<storage>/contents.xml.in`.

- If `partition_conf.contents_xml_in` is `null`/absent: copy the reference
  board's `contents.xml.in` byte-for-byte into the new path — or, if
  `reference_board` is itself `null`, copy any existing board's
  `contents.xml.in` (see Section 2) — do not re-serialize it (whitespace
  and element order matter to `gen_contents.py`'s XML parsing, and there's
  no reason to touch a file that isn't changing).
- If `partition_conf.contents_xml_in` is populated: start from the
  reference board's `contents.xml.in` — or, if `reference_board` is
  `null`, any existing board's `contents.xml.in` (see Section 2) — and
  substitute only:
  - `<product_info><product_name>` → `contents_xml_in.product_name`.
  - The `<chipid flavor="default" storage_type="<storage_type>">`
    element's text → `contents_xml_in.chip_id_default`.
  - `<additional_chipid>` text → `contents_xml_in.additional_chip_ids`.
  Leave `<product_flavors>`, `<builds_flat>`, `<device_programmer>`,
  `<download_file>`/`<partition_file>`/`<partition_patch_file>` templates
  untouched — those describe the qcom-ptool pipeline's own output shape,
  not anything board-specific. Also double check `<chipset>` wasn't left
  as a stale copy from the reference board when it should track
  `chip_id_default` too — a prior board's PR shipped with `<chipid>`
  correctly updated but `<chipset>` still reading the reference board's
  value, which caused a chip mismatch during flashing (device stuck after
  UEFI, no kernel handoff).

## 5. Generate and validate the flashable artifacts (local only, never committed)

From the `qcom-ptool` repo root (requires `pip install -e .` once per
checkout if `qcom-ptool` isn't already on `PATH`):

```sh
qcom-ptool gen_partition -i platforms/<machine>/<storage>/partitions.conf -o platforms/<machine>/<storage>/partitions.xml
qcom-ptool ptool -x platforms/<machine>/<storage>/partitions.xml
qcom-ptool gen_contents -p platforms/<machine>/<storage>/partitions.xml -t platforms/<machine>/<storage>/contents.xml.in -o platforms/<machine>/<storage>/contents.xml
```

Or simply `make all` from the repo root — the Makefile's pattern rules
(`%/partitions.xml`, `%/gpt`, `%/contents.xml`) pick up the new
`partitions.conf`/`contents.xml.in` automatically via its `$(wildcard
platforms/*/*/partitions.conf)` glob. Prefer `make all` unless the user
only wants this one board rebuilt (faster iteration with the explicit
`qcom-ptool` invocations above).

This produces, under `platforms/<machine>/<storage>/`:
`partitions.xml`, `gpt_main0.bin`, `gpt_backup0.bin` (one `gpt_main`/
`gpt_backup` pair per physical partition/LUN group present), `rawprogram0.xml`,
`patch0.xml`, `contents.xml`.

Then validate:

```sh
tests/integration/check-missing-files platforms/<machine>/<storage>/*.xml
```

This cross-checks every `filename` referenced in the generated
`rawprogram*.xml`/`contents.xml` against a known-boot-binary allowlist in
the script. An `Unknown <file>` line means either a typo in the spec's
`filename` field for that partition, or a genuinely new binary name that
needs adding to the allowlist (`tests/integration/check-missing-files`) —
don't silently patch the allowlist without confirming with the user which
case it is.

**These generated files are local validation output only — never part of
the PR.** `qcom-ptool`'s `.gitignore` excludes `platforms/**/*.xml` and
`platforms/**/*.bin`; check any existing board (e.g. `git ls-files
platforms/<ref-board>/<storage>/`) and you'll see only `partitions.conf`
and `contents.xml.in` are tracked. Once `check-missing-files` passes,
delete everything the generation step produced before moving to Section 6
— `git status --short platforms/<machine>/` must show only
`partitions.conf`/`contents.xml.in` as untracked/staged. The real
`.xml`/`.bin` artifacts get regenerated at meta-qcom build time (see
Section 7) and must never end up in a qcom-ptool commit.

Run `make lint` (ruff + mypy) only if you touched `qcom_ptool/` itself,
which this workflow shouldn't.

## 6. Commit, open the PR, and merge it

Only after Section 5's `check-missing-files` passes and the generated
`.xml`/`.bin` files have been deleted:

```sh
cd <qcom-ptool>
git fetch origin main
git checkout -b add/<machine> origin/main
git add platforms/<machine>/<storage>/partitions.conf platforms/<machine>/<storage>/contents.xml.in
git status --short platforms/<machine>/   # confirm only these two files are staged
git commit -s -m "platforms/<machine>: add <storage> partition layout"
git push origin add/<machine>
```

- Branch name is always `add/<machine>` (matches existing convention in
  the fork). If that branch already exists on `origin` (e.g. a prior run
  for this board), stop and ask the user whether to force-push an update
  or pick a different branch name — never force-push over existing work
  silently.
- The commit must be signed off (`-s`), matching upstream `qcom-ptool`'s
  `CONTRIBUTING.md` DCO requirement, even though this PR targets the fork
  rather than upstream directly.
- Before pushing, check whether a PR already exists for this branch to
  avoid opening a duplicate:
  ```sh
  curl -s -H "Authorization: Bearer $GITHUB_TOKEN" -H "Accept: application/vnd.github+json" \
    "https://api.github.com/repos/$QCOM_PTOOL_TARGET/pulls?head=$DISTRO_GITHUB_ORG:add/<machine>&state=open"
  ```
  A non-empty array means one's already open — report its `html_url` back
  to the user instead of creating a second one.

Then open the PR against `$QCOM_PTOOL_TARGET`'s `main` branch via the
GitHub REST API (no `gh` CLI or browser step needed):

```sh
curl -s -X POST \
  -H "Authorization: Bearer $GITHUB_TOKEN" \
  -H "Accept: application/vnd.github+json" \
  "https://api.github.com/repos/$QCOM_PTOOL_TARGET/pulls" \
  -d @- <<EOF
{
  "title": "platforms/<machine>: add <storage> partition layout",
  "head": "add/<machine>",
  "base": "main",
  "body": "Generated from the board-spec entry for <machine> via the qcom-partition-conf-new-board skill.\n\nValidated locally with \`make all integration\` (check-missing-files passed); generated .xml/.bin artifacts are not included, only partitions.conf/contents.xml.in.",
  "draft": false
}
EOF
```

- A `201` response with an `html_url` field means the PR was created —
  note both `html_url` and `number` (needed for the merge step below).
- A `422` usually means the branch has no diff against `base` (nothing to
  PR) or a PR already exists — read the `message`/`errors` fields and
  surface them rather than retrying blindly.
- If `GITHUB_TOKEN` is missing/invalid (`401`), stop and tell the user to
  re-check Section 0's prerequisite — don't fall back to printing a manual
  "go create this PR yourself" message as a silent default; the whole
  point of this step is that it's automatic.

Once the PR exists, merge it — this is no longer a manual follow-up (only
merging *upstream* into `qualcomm-linux/qcom-ptool`, Section 7 item 1,
stays manual). GitHub computes the `mergeable` field asynchronously, so
poll briefly before merging:

```sh
PR_NUMBER=<number from the 201 response>
for i in 1 2 3; do
  MERGEABLE=$(curl -s -H "Authorization: Bearer $GITHUB_TOKEN" -H "Accept: application/vnd.github+json" \
    "https://api.github.com/repos/$QCOM_PTOOL_TARGET/pulls/$PR_NUMBER" | jq -r '.mergeable')
  [ "$MERGEABLE" != "null" ] && break
  sleep 2
done

curl -s -X PUT \
  -H "Authorization: Bearer $GITHUB_TOKEN" \
  -H "Accept: application/vnd.github+json" \
  "https://api.github.com/repos/$QCOM_PTOOL_TARGET/pulls/$PR_NUMBER/merge" \
  -d "{\"commit_title\": \"Merge pull request #$PR_NUMBER: platforms/<machine>: add <storage> partition layout\", \"merge_method\": \"merge\"}"
```

- `merge_method: "merge"` always — a regular merge commit, not
  squash/rebase.
- If `mergeable` came back `false` (a real conflict, not just
  "not computed yet"), stop and report — never force-merge a conflicting
  PR.
- A `200` response with `"merged": true` means success — capture the
  response's `sha` (the merge commit SHA). This is the exact commit a
  caller (e.g. the `distro-smith` orchestrator) bumping
  `qcom-ptool.inc`'s `SRCREV` should point at next. Report the PR
  URL and this merge commit SHA back to the user/caller.
- A `405` (not mergeable) or `409` (SHA mismatch/race) — report the API's
  `message` rather than retrying blindly.

## 7. How this reaches a real qcomflash package (context, not this skill's job)

`meta-qcom` never carries `partitions.conf` — it consumes these generated
`.bin`/`.xml` files by pinning `SRCREV` on the `qcom-ptool` git repo in
`recipes-bsp/partition/qcom-ptool.inc`, building them via
`qcom-partition-conf` (`recipes-bsp/partition/qcom-partition-conf_git.bb`,
which just runs the checkout's `Makefile` through the `qcom-ptool-native`
DEPENDS and deploys everything under `deploy/partitions/<subdir>/`), and
then a machine's `QCOM_PARTITION_FILES_SUBDIR` (set in `conf/machine/
<machine>.conf`, see `qcom-yocto-new-machine`) tells
`classes-recipe/image_types_qcom.bbclass`'s `deploy_partition_files()`
which `<subdir>` to copy `gpt_*.bin`/`rawprogram*.xml`/`patch*.xml`/
`contents.xml` from into the final `<image>.qcomflash/` directory.

This skill gets you through "these files exist, validated inside a
qcom-ptool checkout, and are merged into the fork." Getting them into an
actual `qcomflash` build output additionally requires, as separate
follow-up work — automated by `distro-smith` for items 2-4 below, but
confirm with the user first if running standalone, since it touches what
gets built:

1. Merging the fork PR (Section 6, now automatic) upstream into
   `qualcomm-linux/qcom-ptool` (its own PR against `main`, per
   `CONTRIBUTING.md`: `make lint`, `make generate-checksums` for the new
   files, `make all integration check-checksums` with
   `PTOOL_SEED=qcom-ptool-ci` set) — the fork merge this skill performs is
   a staging step, not the final upstream contribution, unless the user's
   workflow treats the fork as authoritative. This step remains manual.
2. Bumping `SRCREV` in `meta-qcom`'s `recipes-bsp/partition/qcom-ptool.inc`
   to the fork merge commit from Section 6 — the `distro-smith`
   orchestrator does this automatically when given that commit SHA (see
   that skill's own SKILL.md); `qcom-yocto-new-machine` itself no longer
   performs this step.
3. Setting `QCOM_PARTITION_FILES_SUBDIR ?= "partitions/<machine>/<storage>"`
   (and `QCOM_PARTITION_FILES_SUBDIR_SPINOR` if applicable) in the
   machine's `.conf` — this is `qcom-yocto-new-machine`'s territory.
4. `bitbake <image> -c qcomflash` (or building the `qcomflash` `IMAGE_FSTYPES`
   target normally) to produce the final `<image>-<machine>.qcomflash.tar.gz`.

## Notes

- Never fabricate a partition name, size, or type-GUID that isn't either in
  the board-spec entry or copied verbatim from the reference board (or, if
  `reference_board` is `null`, any existing board used as the structural
  template per Section 2) — these correspond to a real boot ROM/XBL/firmware
  contract on physical silicon; a wrong GUID or size produces a board that
  fails to boot, not just a lint error. A `null` `reference_board` only
  means "no single board is the closest match" — it never blocks this
  skill or requires asking the user to name one; pick any existing board
  for boilerplate structure and move on.
- If the board-spec branch is missing, fails `validate_board_spec` with
  `schema_errors`, or has fields that don't map cleanly to the shapes
  described above, stop and ask — do not fall back to inventing a
  partition table from general SoC knowledge. `board-spec` entries are
  human-authored and PR-reviewed in the board-spec repo as
  `machine.yaml`/`partition.yaml`; this skill only reads, it never writes
  to that repo.
- Never guess `DISTRO_GITHUB_ORG` — if it's unset, stop and ask. A wrong
  org silently pushes a branch and opens a PR against someone else's repo.
- Report back exactly which files were written/generated, the
  `check-missing-files` result, the created PR's URL, and the merge
  commit SHA once merged; don't just say "done."
