---
name: qcom-yocto-new-machine
description: >-
  Bring up a new machine (board) in a Yocto BSP layer for a Qualcomm
  platform: conf/machine/<machine>.conf modeled on an existing board, the
  matching ci/<machine>.yml, a new conf/machine/include/qcom-<soc>.inc when
  the SoC has none yet, and — for third-party boards in meta-qcom-3rdparty —
  the firmware-boot/packagegroup/u-boot recipes a new board needs, modeled
  on the uno-q and radxa-dragon-q6a additions. Board facts (SoC, reference
  board, kernel devicetree, boot/partition subdirs, etc.) are pulled from
  the board-spec MCP server (the board-spec repo — see Section 0) when a
  spec already exists for the machine, falling back to asking the user for
  genuinely new boards. Once the machine conf/CI/recipes are written and
  validated, automatically commits them and opens a PR against the
  configured fork (`$DISTRO_GITHUB_ORG/meta-qcom` or
  `$DISTRO_GITHUB_ORG/meta-qcom-3rdparty` — see Section 0) via the GitHub
  REST API. Use when asked to "add a new machine/board to meta-qcom",
  "bring up <board> in meta-qcom-3rdparty", "create a machine conf for
  <SoC>", or "add CI yml for a new board". Do NOT use for building images
  (see qcom-yocto-build-image), flashing/validating hardware (see
  qcom-flash-qdl, qcom-boot-validate), or running pre-PR checks on an
  already-written change (see qcom-yocto-pre-pr-checks).
---

# Bring up a new machine in a Qualcomm Yocto BSP layer

Adds a new board to a Qualcomm BSP layer by reusing the structure of an
existing, similar machine rather than writing one from scratch. Machine
confs in these layers are short and mostly reference a shared per-SoC
include; the work is picking the right template and filling in
board-specific facts, not inventing new patterns.

This skill is part of the `distrosmith` bundle — see that repo's
`README.md` for the one-time `setup.py` install step that provisions the
env vars below and clones the repos this skill needs.

## 0. Prerequisites

- **`DISTRO_GITHUB_ORG`** must be exported in the shell environment — the
  GitHub org or user account that hosts *all* of this user's
  `distrosmith`-managed forks (`meta-qcom`, `meta-qcom-3rdparty` if used,
  `board-spec`, `board-spec-mcp`), always under those exact repo names. If
  it's unset, stop and ask the user for it rather than guessing — this
  value determines whose repo gets a branch pushed and a PR opened
  against it (see Section 10).
- **`GITHUB_TOKEN`** must be exported in the shell environment (a GitHub
  PAT — classic with `repo` scope, or fine-grained with `Contents:
  Read and write` + `Pull requests: Read and write` on the target
  layer repo). Covers both git push/fetch (over HTTPS) and the GitHub
  REST API PR-creation call in Section 10 — no SSH key is used anywhere in
  this skill.
  ```sh
  curl -s -H "Authorization: Bearer $GITHUB_TOKEN" https://api.github.com/user
  ```
- **`BUILD_DISTRO_ROOT`** (optional, defaults to `/tmp/distrosmith-repos`)
  — the local root directory under which layer checkouts live:
  `${BUILD_DISTRO_ROOT:-/tmp/distrosmith-repos}/meta-qcom` and, if the
  target layer is meta-qcom-3rdparty,
  `${BUILD_DISTRO_ROOT:-/tmp/distrosmith-repos}/meta-qcom-3rdparty`. If a
  checkout already exists at that path, use it as-is. If it doesn't exist
  yet, clone the user's own fork over HTTPS using the token (no SSH key
  needed):
  ```sh
  git clone "https://$GITHUB_TOKEN@github.com/$DISTRO_GITHUB_ORG/meta-qcom.git" "${BUILD_DISTRO_ROOT:-/tmp/distrosmith-repos}/meta-qcom"
  ```
  (substitute `meta-qcom-3rdparty` as needed). Only ask the user for a
  different path if they say their checkout lives somewhere else — don't
  default to cloning upstream `qualcomm-linux/meta-qcom` when no local
  checkout is given; this skill always targets the user's own fork so
  Section 10's automated PR has somewhere to push to.

## 1. Pick the target layer

- **meta-qcom** — Qualcomm reference boards (official evaluation/dev kits).
  New machine here is usually a new board on an *already-supported* SoC:
  add `conf/machine/<machine>.conf` requiring the existing
  `conf/machine/include/qcom-<soc>.inc`. A genuinely new SoC additionally
  needs that include created (step 6).
- **meta-qcom-3rdparty** — third-party maintained boards (e.g. Arduino UNO
  Q, Radxa Dragon Q6A). Depends on `meta-qcom` (`meta-qcom.git`, matching
  branch) for the SoC includes and core recipes; only add here what is
  genuinely board-specific: machine conf, CI yml, and — if the board ships
  its own bootloader/firmware/packagegroup — those recipes too (steps 6-7).

Confirm with the user which layer applies; do not guess between an official
reference board and a third-party community board.

## 2. Establish the target

Check the `board-spec` MCP server first: call `list_boards()` and, if the
target machine name is already there, `get_machine_creation_fields(machine)`
(or `get_board_spec(machine)` for the full spec, which also carries the
`partition_conf` half used by `qcom-partition-conf-new-board`). If a spec
exists, it directly supplies:

- **Machine name** — the spec's `machine` field.
- **SoC** — the spec's `soc` field.
- **Closest existing board** — the spec's `reference_board` field.
- `machine_creation.kernel_devicetree`, `boot_files_subdir`,
  `partition_files_subdir`, `cdt_file`, `boot_firmware`, `cdt_firmware`,
  `uboot_config`, `machine_features_add`, `ci_includes` — feed these
  directly into Steps 4 and 8 below instead of asking the user or
  eyeballing a template.
- `machine_creation.fit_dtb_compatible` — feeds Step 5
  (`fit-dtb-compatible.inc`) below. Unlike the fields above, a `null` here
  is easy to mistake for "not needed" when it actually just means "not
  filled in yet" — don't skip Step 5 without checking which is true.

Run `validate_board_spec(machine)` and treat `schema_errors` as blocking;
raise `warnings` to the user rather than silently overriding them.

If `list_boards()` doesn't include the machine yet, this is genuinely new
board work with no spec authored — ask the user (don't guess):

- **Machine name** — kebab-case, matches the board naming already in
  `conf/machine/*.conf` (e.g. `<board>-idp`, `<board>-evk`, `<board>-mtp`,
  `-ride`, `-core-kit`, `-ride-sx`, or a third-party product name like
  `uno-q`, `radxa-dragon-q6a`). This becomes `MACHINE` and the filename.
- **SoC** the board is based on (e.g. qcs6490, qcs8300, sdx75, qcm2290).
- **Closest existing board** to copy from. If unsure, pick a machine on the
  same SoC family — see step 3.
- **Bootloader/firmware ownership** (3rdparty only): does the vendor ship
  its own bootloader/firmware blobs (like UNO Q's Arduino-signed bootloader
  zip), or does the board use the SPI-NOR/EDK2 image flashed independently
  by the vendor (like Radxa Dragon Q6A, which sets the boot firmware
  variables empty with a comment explaining why)? This decides whether you
  need a `firmware-boot` recipe at all.

Mention to the user that once these facts are settled, authoring a
board-spec entry (PR into the board-spec repo, see that repo's README) is
worthwhile follow-up — it makes both this skill and
`qcom-partition-conf-new-board` reusable for this board without re-asking,
but that authoring step is out of scope for this skill (it only reads).

## 3. Find the template to copy from

```sh
ls conf/machine/*.conf
grep -rl "SOC_FAMILY" conf/machine/include/*.inc   # meta-qcom only
```

- If a `conf/machine/include/qcom-<soc>.inc` already exists for this SoC
  (in meta-qcom, or reachable via meta-qcom from a 3rdparty layer), find
  another machine `.conf` that `require`s it — that's your template.
  Example: `qcs6490-rb3gen2-core-kit.conf` requires
  `include/qcom-qcs6490.inc`; UNO Q's `uno-q.conf` requires
  `conf/machine/include/qcom-qcm2290.inc` from meta-qcom even though the
  board itself lives in meta-qcom-3rdparty.
- If no include exists for this SoC yet, this is a **new SoC**, not just a
  new board — go to step 6 first, then come back here. New-SoC work belongs
  in meta-qcom, not in a 3rdparty layer.
- Read the chosen template `.conf` end to end before writing anything new.

## 4. Write `conf/machine/<machine>.conf`

Follow the exact structure used by every existing machine conf. Reference
points: `qcs615-ride.conf` / `rb3gen2-core-kit.conf` / `glymur-crd.conf` in
meta-qcom for reference-board style; `uno-q.conf` / `radxa-dragon-q6a.conf`
in meta-qcom-3rdparty for third-party style.

If step 2 found a board-spec entry, populate the template directly from its
`machine_creation` fields (`kernel_devicetree`, `cdt_file`,
`boot_files_subdir`, `partition_files_subdir`, `boot_firmware`,
`cdt_firmware`, `uboot_config`, `machine_features_add`) instead of asking
the user for each one — only fall back to asking when a field is `null` in
the spec and genuinely board-specific (e.g. no `uboot_config` because the
board doesn't use u-boot-qcom).

```
#@TYPE: Machine
#@NAME: <human-readable board name>
#@DESCRIPTION: Machine configuration for <human-readable board name>, with <SoC>

require conf/machine/include/qcom-<soc>.inc
MACHINEOVERRIDES =. "<vendor>:"        # 3rdparty boards with their own overrides, e.g. "arduino:"

MACHINE_FEATURES += "<features specific to this board>"

KERNEL_DEVICETREE ?= " \
                      qcom/<dtb-name>.dtb \
                      "

MACHINE_ESSENTIAL_EXTRA_RRECOMMENDS += " \
    packagegroup-<board>-firmware \
    packagegroup-<board>-hexagon-dsp-binaries \
"

QCOM_CDT_FILE = "<cdt name>"                        # reference boards
QCOM_BOOT_FILES_SUBDIR = "<subdir under boot firmware>"
QCOM_PARTITION_FILES_SUBDIR ?= "partitions/<board>/<ufs|nvme|spinor|emmc>"

QCOM_BOOT_FIRMWARE = "firmware-qcom-boot-<soc-or-board>"
QCOM_CDT_FIRMWARE = "firmware-qcom-cdt-<soc-or-board>"      # reference boards

UBOOT_CONFIG = "<board defconfig fragment>"                  # if u-boot-qcom/u-boot-<vendor> is the bootloader
```

Rules learned from the existing confs:

- `MACHINE_FEATURES` uses `+=` when the SoC include already sets a base set
  (`qcom-qcs6490.inc` sets `alsa bluetooth usbgadget usbhost wifi`); use `=`
  only when the board must replace the base set entirely (rare — see
  `kaanapali-mtp.conf`).
- If the vendor's bootloader/firmware is flashed independently and not
  built by this layer, blank the `QCOM_BOOT_FIRMWARE` / `QCOM_CDT_*` /
  `QCOM_PARTITION_*` variables with a comment explaining why (see
  `radxa-dragon-q6a.conf`, which uses Radxa's own SPI-NOR EDK2 image and
  sets no `PREFERRED_PROVIDER_virtual/bootloader`).
- If the vendor ships prebuilt bootloader binaries this layer packages
  itself (UNO Q's Arduino zip), point `PREFERRED_PROVIDER_virtual/kernel`
  and `PREFERRED_PROVIDER_virtual/bootloader` at the board's own recipes
  (`linux-arduino`, `u-boot-arduino`) instead of the shared meta-qcom ones,
  and write the recipes in step 7.
- Only add the `QCOM_RT_CPU` / `QCOM_IRQAFF` / `QCOM_RCU_NOCBS` /
  `QCOM_RCU_EXPEDITED` / `QCOM_CPUIDLE_OFF` isolation block if the board
  supports an RT kernel and needs isolated CPUs — copy values from a
  same-SoC sibling if one exists.
- If this is a firmware/config variant of an existing board rather than new
  hardware (e.g. `-open-fw`), `require conf/machine/<base>.conf` instead of
  the SoC include, and add only the deltas — see
  `rb3gen2-core-kit-open-fw.conf`.
- If the new machine is a rename/alias of an existing one, mark the old one
  deprecated instead: `#DEPRECATED, use <new> instead` +
  `require conf/machine/<new>.conf` (see `qrb2210-rb1-core-kit.conf`).

Never invent DTB names, CDT file names, or firmware package/URL details —
take them from the board-spec entry if one exists, otherwise ask the user;
they come from the board's kernel/firmware delivery, not from convention.

## 5. Add `FIT_DTB_COMPATIBLE` entries in `fit-dtb-compatible.inc`

Every DTB/overlay combo in `KERNEL_DEVICETREE` needs a matching
`FIT_DTB_COMPATIBLE[<encoded-compat>] = "<dtb-stem> [<overlay-stem>...]"`
entry in `conf/machine/include/fit-dtb-compatible.inc` (base combos) or
`fit-dtb-compatible-linux-qcom.inc` (linux-qcom-only overlay combos), grouped
under a `# ---------- <soc_family> ----------` comment block. `do_generate_
qcom_fitimage` (`classes-recipe/dtb-fit-image.bbclass`) uses these entries to
emit the FIT image's `configurations` node, which UEFI's `ParseFitDt` matches
against at boot to pick the right DTB.

**This step is easy to miss**: skipping it does not fail the build or even
warn loudly — the task only logs a `bb.note()` ("No FIT_DTB_COMPATIBLE entry
covers '<fname>' for this kernel variant..."), the FIT image still builds
with the DTBs included but zero `conf-N` config nodes, and the board only
fails at boot time with UEFI logging `ParseFitDt: Cannot find correct config
to boot, Falling to default config`. Do not rely on a successful
`kas-container build` (step 9) to catch a missing entry — it won't.

If step 2 found a board-spec entry, use `machine_creation.fit_dtb_compatible`
directly: each `{compatible, dtbs}` pair becomes one flag line, encoding
`,` as `_` in the flag name, e.g. `compatible: qcom,shikracqm-itp, dtbs:
[shikra-cqm-evk, shikra-cqm-evk-imx577-camera]` becomes:

```
FIT_DTB_COMPATIBLE[qcom_shikracqm-itp] = "shikra-cqm-evk shikra-cqm-evk-imx577-camera"
```

If the field is `null` in the spec, don't assume it means "not needed" —
check whether every `kernel_devicetree` entry is already covered by an
existing entry for this `soc_family` (true for a firmware/config variant of
an existing board) before skipping this step. If no spec exists, derive the
compatible string and DTB/overlay stems from the reference board's own
`fit-dtb-compatible.inc` entry and adapt it — never invent the compatible
string from scratch.

## 6. New SoC only: scaffold `conf/machine/include/qcom-<soc>.inc` (meta-qcom)

Only needed when step 3 found no existing include for this SoC — and only
in meta-qcom, never in a 3rdparty layer. Model on
`conf/machine/include/qcom-qcs6490.inc` or `qcom-qcs615.inc`:

```
# Configurations and variables for <SOC> SoC family.

SOC_FAMILY = "<soc-family>"
require conf/machine/include/qcom-base.inc
require conf/machine/include/qcom-common.inc

DEFAULTTUNE = "<armv8-2a-crypto | matching arch tune>"
require conf/machine/include/arm/arch-<matching-armv8-x>.inc

MACHINE_ESSENTIAL_EXTRA_RRECOMMENDS += " \
    packagegroup-qcom-boot-essential \
    packagegroup-machine-essential-qcom-<soc>-soc \
"

MACHINE_EXTRA_RRECOMMENDS += " \
    packagegroup-qcom-boot-additional \
"
```

Confirm the DEFAULTTUNE/arch include by checking what a same-generation SoC
uses in `conf/machine/include/arm/` rather than guessing.

## 7. Third-party boards only: add the board's own recipes

meta-qcom-3rdparty's `AGENTS.md` rule is **no recipe forks** — never copy a
recipe out of meta-qcom to modify it; use a `.bbappend` instead. Only write
new recipes for what is genuinely unique to this board:

- **`recipes-bsp/packagegroups/packagegroup-<board>.bb`** — model on
  `packagegroup-uno-q.bb`: `inherit packagegroup`, a `-firmware` and
  `-hexagon-dsp-binaries` package split, `RRECOMMENDS`/`RDEPENDS` gated by
  `bb.utils.contains(_any)('DISTRO_FEATURES', ...)` for optional features
  (wifi, bluetooth, opengl/vulkan/opencl).
- **`recipes-bsp/firmware-boot/firmware-qcom-boot-<board>_<version>.bb`** —
  only if the vendor ships a prebuilt bootloader/firmware bundle this layer
  fetches and packages (model on
  `firmware-qcom-boot-qrb2210-arduino-imola_251020.bb`): `SRC_URI` to the
  vendor's download with a `sha256sum`, `BOOTBINARIES`,
  `QCOM_BOOT_IMG_SUBDIR`, `COMPATIBLE_MACHINE = "(<machine>)"`, and
  `include recipes-bsp/firmware-boot/firmware-qcom-boot-common.inc`. Skip
  this entirely for boards like Radxa Dragon Q6A where firmware is flashed
  independently.
- **`recipes-bsp/u-boot/u-boot-<vendor>_git.bb`** — only if the board needs
  a vendor-forked bootloader source tree distinct from `u-boot-qcom`.

Do not create per-vendor branches or top-level folder segregation — every
board's recipes live under the layer's normal `recipes-*` tree per
`AGENTS.md`.

## 8. Add the matching CI yaml

Every machine conf has a same-named `ci/<machine>.yml` used by kas.

meta-qcom:

```yaml
# yaml-language-server: $schema=https://raw.githubusercontent.com/siemens/kas/master/kas/schema-kas.json

header:
  version: 14
  includes:
  - ci/base.yml

machine: <machine>
```

meta-qcom-3rdparty additionally pins the meta-qcom dependency
(`ci/meta-qcom.yml` — a `repos:` entry pointing at
`https://github.com/qualcomm-linux/meta-qcom`, matching branch); base it on
`ci/uno-q.yml` or `ci/radxa-dragon-q6a.yml`, which include `ci/base.yml`
(itself pulling in `ci/meta-qcom.yml`) the same way.

## 9. Validate

Per each layer's `AGENTS.md`, before considering this done:

```sh
export KAS_YAMLS="ci/<machine>.yml:ci/qcom-distro.yml"
"${KAS_CONTAINER:-kas-container}" build "${KAS_YAMLS}"
ci/kas-container-shell-helper.sh ci/yocto-patchreview.sh
```

Run `ci/kas-container-shell-helper.sh ci/yocto-check-layer.sh` before
opening or updating a pull request. Do not skip straight to a PR without at
least a successful `bitbake` parse/build of the new machine.

## 10. Commit and open the PR

Commit following the layer's `CONTRIBUTING.md`/`AGENTS.md`: subject
`conf/machine: add <machine>` (or `recipes-bsp/<recipe>: add <machine>` for
a recipe-only commit — keep each logical change atomic and in its own
commit), plain-English body explaining what board this is and why, and a
`Signed-off-by` trailer built from `git config user.name`/`user.email` —
never fabricate identity. Add `Assisted-by: AGENT_NAME:MODEL_VERSION` if an
AI assistant helped write the change.

```sh
cd <layer-checkout>
git fetch origin <layer-default-branch>
git checkout -b add/<machine> origin/<layer-default-branch>
git add <files for this logical change>
git commit -s -m "conf/machine: add <machine>"
git push origin add/<machine>
```

- `<layer-default-branch>` is `master` for meta-qcom, `main` for
  meta-qcom-3rdparty (see Notes).
- Branch name is always `add/<machine>`. If it already exists on `origin`
  (e.g. a prior run for this board), stop and ask the user whether to
  force-push an update or pick a different branch name — never force-push
  silently.
- Before pushing, check whether a PR already exists for this branch to
  avoid opening a duplicate:
  ```sh
  curl -s -H "Authorization: Bearer $GITHUB_TOKEN" -H "Accept: application/vnd.github+json" \
    "https://api.github.com/repos/$DISTRO_GITHUB_ORG/<repo>/pulls?head=$DISTRO_GITHUB_ORG:add/<machine>&state=open"
  ```
  A non-empty array means one's already open — report its `html_url` back
  to the user instead of creating a second one.

Then open the PR against `$DISTRO_GITHUB_ORG/<repo>`'s default branch via
the GitHub REST API (no `gh` CLI or browser step needed):

```sh
curl -s -X POST \
  -H "Authorization: Bearer $GITHUB_TOKEN" \
  -H "Accept: application/vnd.github+json" \
  "https://api.github.com/repos/$DISTRO_GITHUB_ORG/<repo>/pulls" \
  -d @- <<EOF
{
  "title": "conf/machine: add <machine>",
  "head": "add/<machine>",
  "base": "<layer-default-branch>",
  "body": "Adds <machine> (<SoC>) via the qcom-yocto-new-machine skill.\n\nValidated locally with kas-container build, yocto-patchreview.sh, and yocto-check-layer.sh.",
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
  re-check Section 0's prerequisite — don't fall back to printing a manual
  "go create this PR yourself" message as a silent default.
- This PR lands on the user's own fork first (a staging step, same
  philosophy as `qcom-partition-conf-new-board`) — merging it upstream into
  `qualcomm-linux/meta-qcom` (or the 3rdparty layer's upstream) is a
  separate, manual follow-up; don't do that without the user asking.

## Notes

- meta-qcom's primary branch is `master`; meta-qcom-3rdparty's is `main`
  (both also carry LTS branches — check the target repo before branching).
- Reference-board additions (meta-qcom) and third-party additions
  (meta-qcom-3rdparty) share the machine-conf mental model but diverge on
  recipe ownership — meta-qcom centralizes SoC-level recipes, 3rdparty
  layers add only board-unique ones and depend on meta-qcom for the rest.
- Never guess `DISTRO_GITHUB_ORG` — if it's unset, stop and ask. A wrong
  org silently pushes a branch and opens a PR against someone else's repo.
- For subsequent work on the new machine, follow up with
  `qcom-yocto-build-image` (build), `qcom-flash-qdl`/`qcom-boot-validate`
  (flash and validate on hardware), and `qcom-yocto-pre-pr-checks` before
  the PR is reviewed.
