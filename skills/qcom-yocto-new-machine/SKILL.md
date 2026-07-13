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
  genuinely new boards. Optionally bumps recipes-bsp/partition/
  qcom-ptool.inc's SRCREV to a merged qcom-ptool commit (see Section 9),
  then triggers a real kas-container build targeting qcom-console-image
  (Section 10) — commits and opens a PR against the configured fork
  (`$DISTRO_GITHUB_ORG/meta-qcom` or `$DISTRO_GITHUB_ORG/meta-qcom-3rdparty`
  — see Section 0) via the GitHub REST API only if that build succeeds, and
  always writes the run's result to distro-params.yaml (Section 12). Use
  when asked to "add a new machine/board to meta-qcom", "bring up <board>
  in meta-qcom-3rdparty", "create a machine conf for <SoC>", or "add CI yml
  for a new board". Do NOT use for flashing/validating hardware (see
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
  against it (see Section 11).
- **`GITHUB_TOKEN`** must be exported in the shell environment (a GitHub
  PAT — classic with `repo` scope, or fine-grained with `Contents:
  Read and write` + `Pull requests: Read and write` on the target
  layer repo). Covers both git push/fetch (over HTTPS) and the GitHub
  REST API PR-creation call in Section 11 — no SSH key is used anywhere in
  this skill.
  ```sh
  curl -s -H "Authorization: Bearer $GITHUB_TOKEN" https://api.github.com/user
  ```
- **`BUILD_DISTRO_ROOT`** (optional, defaults to
  `$(pwd)/.distrosmith-work` — a work directory under the invocation cwd,
  not `/tmp`) — the local root directory under which layer checkouts live:
  `${BUILD_DISTRO_ROOT:-$(pwd)/.distrosmith-work}/meta-qcom` and, if the
  target layer is meta-qcom-3rdparty,
  `${BUILD_DISTRO_ROOT:-$(pwd)/.distrosmith-work}/meta-qcom-3rdparty`. If a
  checkout already exists at that path, use it as-is. If it doesn't exist
  yet, clone the user's own fork over HTTPS using the token (no SSH key
  needed):
  ```sh
  git clone "https://$GITHUB_TOKEN@github.com/$DISTRO_GITHUB_ORG/meta-qcom.git" "${BUILD_DISTRO_ROOT:-$(pwd)/.distrosmith-work}/meta-qcom"
  ```
  (substitute `meta-qcom-3rdparty` as needed). Only ask the user for a
  different path if they say their checkout lives somewhere else — don't
  default to cloning upstream `qualcomm-linux/meta-qcom` when no local
  checkout is given; this skill always targets the user's own fork so
  Section 11's automated PR has somewhere to push to. When this skill runs
  standalone (not via `distro-smith`), leave this checkout in place when
  done — it's reused by follow-up work (see Notes); only `distro-smith`'s
  own orchestration removes it, and only after that flow's
  `distro-params.yaml` is written.
- **`DISTRO_AUTOPILOT`** (optional, defaults to unset/false) — set it (or
  have the user ask to run this "non-interactively" / "just fill in
  placeholders for anything missing") to switch to **autopilot**: never
  call `AskUserQuestion` for a missing board fact for the rest of the run.
  Every fact that would otherwise trigger a question instead gets a
  `TODO_FILL_IN_<FIELD>` placeholder written directly into the generated
  file. Keep a running list of every placeholder written (file + field),
  and print it as a single outstanding-items summary before Section 10's
  build (see that section) instead of interrupting mid-flow. Autopilot
  still never fabricates a real-looking value (sha256sum, build ID,
  download URL, node name) — a placeholder is the only allowed substitute
  for a genuinely unknown fact. This matters because `distro-smith`'s
  orchestrator can invoke this skill headlessly, with no one to answer an
  `AskUserQuestion` prompt. Default (unset) keeps the normal
  ask-when-missing flow described throughout this skill.

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

If `DISTRO_AUTOPILOT` is set (Section 0), skip asking the user for any of
the above that's still unknown — write a `TODO_FILL_IN_<FIELD>` placeholder
into the generated file instead (machine name and layer still can't be
placeholder'd; if either is genuinely unknown, stop and ask regardless of
autopilot, since nothing downstream can proceed without them) and add it to
the running outstanding-items list (Section 0).

Two fields are easy to skip past because they only matter once a later step
needs them, so call them out explicitly rather than silently defaulting to
a placeholder the first time they come up empty — unless autopilot is on,
in which case go straight to the placeholder for both without asking:

- `firmware_boot.bootbinaries_sha256sum` / `firmware_cdt.sha256sum` —
  before writing `firmware-qcom-boot-<soc-or-board>.inc`/`.bb` or
  `firmware-qcom-cdt-<soc-or-board>.bb` (Section 4/6), if either is still
  unknown, ask the user directly for the real sha256sum via
  `AskUserQuestion` — never offer to reuse another board's hash as if it
  were verified. Only write the placeholder if the user picks that option,
  or if autopilot is on.
- `packagegroup.optional_feature_packages.wifi` — before writing
  `packagegroup-<board>.bb` (Section 7), if the board's `MACHINE_FEATURES`
  includes `wifi` (either explicitly or via the SoC include's default) and
  this field is still unknown, ask the user for the wifi firmware
  package(s) via `AskUserQuestion` rather than omitting the RRECOMMENDS
  entry or guessing a package name. Only write the placeholder if the user
  explicitly chooses that option, or if autopilot is on.
- `fit_dtb_compatible` — before finishing Section 5, if this is still
  empty, check `qcom-metadata.dts` (in the `qcom-dtb-metadata` fetch)
  yourself for the real soc/board node names first — this is research, not
  a question only the user can answer. Only fall back to asking the user
  (or, in autopilot, to a placeholder) if no matching node exists yet
  upstream — see Section 5.

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
`cdt_firmware`, `uboot_config`, `machine_features_add`,
`machine_features_set`) instead of asking the user for each one — only fall
back to asking when a field is `null` in the spec and genuinely
board-specific (e.g. no `uboot_config` because the board doesn't use
u-boot-qcom).

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
  `kaanapali-mtp.conf`). If the board-spec entry has
  `machine_creation.machine_features_set` populated, that's this rare case:
  emit `MACHINE_FEATURES = "<the listed features>"` (replace, no `+=`)
  instead of `machine_features_add`'s `+=` form — e.g. a board that drops a
  feature the SoC include enables by default (no wifi firmware package
  available yet) has to replace the whole set since `+=` can't subtract.
  Only one of `machine_features_add`/`machine_features_set` should be
  populated for a given board; if both are empty, fall back to asking the
  user whether this board needs any delta from the SoC include's base set.
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

For the matching `recipes-bsp/packagegroups/packagegroup-<board>.bb`,
`recipes-bsp/firmware-boot/firmware-qcom-boot-<soc-or-board>.inc`/`.bb`, and
`recipes-bsp/firmware-boot/firmware-qcom-cdt-<soc-or-board>.bb` on a
**meta-qcom reference board**, model on `qcm6490-idp` or `qcs9100-ride-sx`
(e.g. `packagegroup-qcm6490-idp.bb`, `firmware-qcom-boot-qcs6490.inc` +
`firmware-qcom-boot-qcs6490_<version>.bb`, `firmware-qcom-cdt-qcs6490.bb`) —
their `FW_ARTIFACTORY`/`BOOTBINARIES` and `CDT_ARTIFACTORY` shape is the
current mainline pattern. Avoid `kaanapali-mtp` as a recipe/packagegroup
template — its `MACHINE_FEATURES = ` (replace-all) and package split are
board-specific outliers, not representative of how most reference boards
are configured.

**`LIC_FILES_CHKSUM` points inside the bootbinaries tarball itself, not at
a separately-fetched `LICENSE.txt`.** Every current `firmware-qcom-boot-*`
`.inc` (e.g. `firmware-qcom-boot-qcs9100.inc`) uses:

```
LICENSE = "LICENSE.qcom-2"
LIC_FILES_CHKSUM = "file://${UNPACKDIR}/${BOOTBINARIES}/LICENSE.qcom-2.txt;md5=<license_md5sum>"
```

Take `<license_md5sum>` from the board-spec entry's
`firmware_boot.license_md5sum` when one exists — don't hardcode a specific
md5 value from memory or from another board's recipe/documentation without
cross-checking; a hardcoded value that's wrong for one board and copied
into another board's recipe/notes is exactly how a data-entry error
propagates (board-spec has recorded one such case in a `firmware_boot.notes`
field — check there before trusting any md5 you find in docs). When
scaffolding a genuinely new board with no board-spec entry yet, reuse the
reference board's own recipe's md5 verbatim rather than typing a value in
from a comment or template, since it's shared across every board on that
same `LICENSE.qcom-2` text. Don't add a second `SRC_URI` entry to fetch
`LICENSE.txt` separately — the license file is already unpacked as part of
the same bootbinaries zip that `SRC_URI[bootbinaries.sha256sum]` covers.

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
`kas-container build` (Section 10) to catch a missing entry — it won't.

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

**The key is NOT the kernel DTS's `compatible` property.** It looks similar
but is a different, independently-maintained string defined by
[qcom-dtb-metadata](https://github.com/qualcomm-linux/qcom-dtb-metadata)
(`recipes-kernel/linux/qcom-dtb-metadata_<pv>.bb`, deployed as
`qcom-metadata.dtb`), not derived from the DTS at all. `<soc-node>` and
`<board-node>` in `qcom,<soc-node>-<board-node>[-<boardrev-node>]
[-<subtype-node>...]` are literal node names from `qcom-metadata.dts`'s
`soc { }` and `board { }` blocks in the `qcom-dtb-metadata` repo — **not**
the SoC/board names used anywhere else in this layer, and often a different
spelling than the kernel DTS's own `compatible` string. For example
`hamoa-iot-evk.dts` declares `compatible = "qcom,hamoa-iot-evk", ...` but
the matching entry is `FIT_DTB_COMPATIBLE[qcom_hamoa-evk]`, because
`qcom-metadata.dts` names the SoC node `hamoa` (not `hamoa-iot`) and the
board node `evk`. Never assume the DTS compatible string is reusable
verbatim — always check the metadata source. This matters most when no
board-spec entry and no matching reference-board `.inc` entry exist yet to
copy from — reaching for the reference board's entry (above) only works
when one actually covers this DTB combo already.

**How to find the real soc/board node names** when neither a board-spec
entry nor a reference-board `.inc` entry covers this DTB combo — don't
guess or reuse the machine name:

1. Check whether `qcom-metadata.dts` (in the `qcom-dtb-metadata` fetch,
   under `build/tmp/work/*/qcom-dtb-metadata/*/` after a `do_fetch`/
   `do_unpack`, or read directly from the pinned `SRCREV` on
   https://github.com/qualcomm-linux/qcom-dtb-metadata) already has `soc {}`
   sub-nodes for this SoC (added upstream ahead of the board landing in this
   layer — this is common, since the chip ID allocation happens earlier than
   BSP bring-up) and a `board {}` sub-node matching this board type (`evk`,
   `idp`, `mtp`, `crd`, `qam`, etc.).
2. If the SoC has multiple chip variants that need distinguishing (e.g. one
   SoC family with several die/package SKUs, each producing its own DTB),
   expect one `soc` node per variant — match each `KERNEL_DEVICETREE` base
   DTB to its own variant node, not one shared node for all of them.
3. If no matching `soc`/`board` node exists yet upstream, this is a real gap
   — do not invent a `msm-id`/`board-id` value. Tell the user their new
   board needs an entry added to `qcom-dtb-metadata` first (a separate PR to
   that repo, out of scope for this layer), and (per Section 0's autopilot
   mode, or if the user prefers) leave a
   `TODO_FILL_IN_FIT_DTB_COMPATIBLE_<board>` placeholder rather than a
   fabricated key.
4. Camera/other overlays generally don't carry their own board-level
   `compatible` override (they only add a `compatible` inside an internal
   fragment node, e.g. for the sensor) — they're referenced purely as
   additional `<overlay-stem>` entries appended to the base DTB's combo, not
   as separate `FIT_DTB_COMPATIBLE` keys of their own.

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

`packagegroup-machine-essential-qcom-<soc>-soc` referenced above is a
package inside the shared
`recipes-bsp/packagegroups/packagegroup-machine-essential.bb`, not a
separate recipe — add the new SoC there too, in the same pattern as every
other SoC (alphabetically among the `${PN}-qcom-*-soc` entries):

```
PACKAGES = " \
    ...
    ${PN}-qcom-<soc>-soc \
"

RRECOMMENDS:${PN}-qcom-<soc>-soc += " \
    ${PN}-board-generic \
    ${PN}-qcom-generic \
    kernel-module-<soc-specific-module> \
    ...
"
```

The SoC-specific kernel modules (camcc/dispcc/gpucc/videocc/etc. for that
chip) come from the board-spec entry's `soc_kernel_modules` field — that
field is populated only when scaffolding a genuinely new `soc_family` (see
the schema's description), which is exactly this case, so use those values
directly instead of asking. If it's `null`/empty (no board-spec entry, or
the field wasn't filled in), ask the user for the SoC's kernel module list;
if that's declined (or autopilot is on, per Section 0), add the entry with
just `${PN}-board-generic`/`${PN}-qcom-generic` and a
`TODO_FILL_IN_<SOC>_SOC_KERNEL_MODULES` placeholder — don't skip the
`PACKAGES`/`RRECOMMENDS` entry entirely, since
`MACHINE_ESSENTIAL_EXTRA_RRECOMMENDS` in the SoC include above already
depends on this package existing.

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
  independently. Point `LIC_FILES_CHKSUM` at the license file already
  inside that same fetched bundle (see Section 4's note on the in-tarball
  `LIC_FILES_CHKSUM` pattern) — don't add a second `SRC_URI` entry and
  `SRC_URI[license.sha256sum]` flag to fetch a `LICENSE.txt` separately.
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

## 9. New qcom-ptool commit only: bump `qcom-ptool.inc`'s `SRCREV`

Skip this step entirely unless you were given a qcom-ptool commit SHA to
point at — typically the merge commit SHA that `qcom-partition-conf-new-board`
reports after Section 6's auto-merge (e.g. when invoked via the
`distro-smith` orchestrator). This is not something to do speculatively
when this skill is invoked standalone with no such SHA.

If the layer has `recipes-bsp/partition/qcom-ptool.inc` and you do have a
target SHA:

```sh
sed -i \
  -e "s#^SRC_URI = .*#SRC_URI = \"git://github.com/\$DISTRO_GITHUB_ORG/qcom-ptool.git;branch=main;protocol=https\"#" \
  -e "s#^SRCREV = .*#SRCREV = \"<merged-commit-sha>\"#" \
  recipes-bsp/partition/qcom-ptool.inc
```

This is its own atomic commit, separate from the `conf/machine: add
<machine>` commit (per `AGENTS.md`'s "each patch must be logically
coherent, self-contained" rule):

```sh
git add recipes-bsp/partition/qcom-ptool.inc
git commit -s -m "recipes-bsp/partition: point qcom-ptool at merged <machine> partitions"
```

## 9a. Autopilot outstanding-items summary

If `DISTRO_AUTOPILOT` was set (Section 0) and any `TODO_FILL_IN_...`
placeholder was written during the run (Sections 2/5/6/7), stop here and
print a single consolidated list before moving to validation: one line per
placeholder, giving the file it's in and the variable/field name (e.g.
`firmware-qcom-boot-<board>_00036.bb: SRC_URI[bootbinaries.sha256sum] =
TODO_FILL_IN_BOOTBINARIES_SHA256SUM`). This is the one point in an
autopilot run where these gaps surface — do not also raise them earlier
mid-run, and do not silently drop them. If nothing was left as a
placeholder, skip this step. When autopilot was not used, this step is a
no-op (any missing field was already resolved interactively as each
section needed it).

## 10. Validate: trigger a real build

Per each layer's `AGENTS.md`, before considering this done, run an actual
build — do not skip it or treat it as merely a parse check:

```sh
export KAS_YAMLS="ci/<machine>.yml:ci/qcom-distro.yml"
"${KAS_CONTAINER:-kas-container}" build "${KAS_YAMLS}" --target qcom-console-image
```

The explicit `--target qcom-console-image` restricts the build to that
one image instead of the full `ci/qcom-distro.yml` target list
(`qcom-multimedia-image`, `qcom-multimedia-proprietary-image`,
`qcom-container-orchestration-image`, `qcom-networking-image`) — the same
`--target` override CI already uses for its SDK build step
(`.github/workflows/compile.yml`).

Record the actual build result (pass/fail; on failure, the tail of the
build log) — **this result gates Section 11 next.**

If the build fails, diagnose the actual error from the log (bitbake's
`ERROR:` lines usually name the missing/broken recipe or dependency
directly) and attempt a fix:

- Prefer the smallest change that addresses the real cause — e.g. drop an
  RDEPENDS/RRECOMMENDS on a package that genuinely doesn't exist upstream
  yet, correct a typo'd recipe/package name, add a missing `require`, fix
  a bad `SRC_URI`/`SRCREV`/checksum. Don't paper over the error by deleting
  functionality beyond the specific broken reference.
- Re-run the exact same build command after each fix attempt.
- Cap retries at 3 distinct fix attempts. If the build still fails after
  3 attempts, or if the root cause isn't something this skill's own
  written files control (e.g. an upstream repo genuinely missing a
  package, a network/infra failure, a disk-space error), stop — do not
  keep iterating blindly. Go to Section 12 to report the failure (include
  what was tried and why it didn't resolve it) and write
  `distro-params.yaml` with `status: "fail"`.
- Any fix applied here becomes part of the same commit(s) in Section 11 —
  don't create separate "fixup" commits; the change that goes into the PR
  should look like it was written correctly the first time.

Once the build passes (whether on the first attempt or after a fix),
continue below.

If the build succeeds, continue:

```sh
ci/kas-container-shell-helper.sh ci/yocto-patchreview.sh
```

Run `ci/kas-container-shell-helper.sh ci/yocto-check-layer.sh` before
opening or updating a pull request.

## 11. Commit and open the PR

**Only reachable after Section 10's build succeeded** — do not commit or
open/update a PR off a failed or skipped build.

Commit following the layer's `CONTRIBUTING.md`/`AGENTS.md`: split the
change into logically separate, independently buildable commits rather
than one bundled commit — this mirrors the "avoid mixing unrelated
changes" / "each patch must be logically coherent, self-contained, and
independently buildable" rule in the target layer's `AGENTS.md`/
`CONTRIBUTING.md`. A typical new-machine change decomposes along the
recipe boundaries introduced in Sections 4-8, in dependency order so the
tree stays buildable after every commit even though the machine only
becomes selectable once the final commit lands:

1. **New SoC plumbing** (only when Section 6 ran) — the new
   `conf/machine/include/qcom-<soc>.inc` plus its
   `packagegroup-machine-essential-qcom-<soc>-soc` entry in
   `recipes-bsp/packagegroups/packagegroup-machine-essential.bb`. Subject:
   `conf/machine: add <soc> SoC family`.
2. **Boot/CDT firmware recipes** (Sections 4/7) — the
   `firmware-qcom-boot-<soc-or-board>.inc`/`.bb` and
   `firmware-qcom-cdt-<soc-or-board>.bb` pair. Subject:
   `recipes-bsp/firmware-boot: add <soc-or-board> boot and CDT firmware recipes`.
3. **Board packagegroup** (Sections 4/7) — the `packagegroup-<board>.bb`
   recipe. Subject: `recipes-bsp/packagegroups: add packagegroup-<board>`.
4. **The machine itself** — `conf/machine/<machine>.conf`, its
   `FIT_DTB_COMPATIBLE` entries (Section 5) in
   `conf/machine/include/fit-dtb-compatible.inc`, and `ci/<machine>.yml`
   (Section 8). This is the commit that wires everything above together
   and is the point at which the machine becomes selectable/buildable, so
   it must land last. Subject: `conf/machine: add <machine>`.

Commits 1-3 add recipes nothing references yet, so they don't change any
existing machine's behavior — safe to land independently of each other,
but all three must precede commit 4. Skip a slot here the same way its
corresponding write step was skipped (no new SoC → no commit 1; board
reuses an existing packagegroup pattern instead of a new one → fold into
commit 4 rather than inventing a split that isn't there). For a small/
simple addition (existing SoC, no new firmware, no new packagegroup), it
is fine to collapse to a single `conf/machine: add <machine>` commit —
logical separation means matching commit boundaries to genuinely distinct
pieces of work, not hitting a fixed commit count.

For each commit: `git add` only the files for that piece, plain-English
body explaining what and why for anything non-trivial, and a
`Signed-off-by` trailer built from `git config user.name`/`user.email` —
never fabricate identity. Add `Assisted-by: AGENT_NAME:MODEL_VERSION` if an
AI assistant helped write the change.

```sh
cd <layer-checkout>
git fetch origin <layer-default-branch>
git checkout -b add/<machine> origin/<layer-default-branch>
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

## 12. Write `distro-params.yaml`

Always write this file, whether Section 10's build passed or failed —
write it in the directory this skill was invoked from (the invocation
cwd, not the `BUILD_DISTRO_ROOT` checkout).

On a successful build + PR (Section 11 ran):

```yaml
status: "pass"

repo:        "https://github.com/$DISTRO_GITHUB_ORG/<repo>.git"
branch:      "add/<machine>"
type:        "distro"

changes:
  - type: pr
    url: <qcom-ptool PR html_url, only if Section 9 ran this invocation>
  - type: pr
    url: <meta-qcom PR html_url from Section 11>
  # Add more changes below (applied in listed order):
  # - type: pr
  #   url: https://github.com/qualcomm-linux/meta-qcom/pull/2717
  # - type: commit
  #   url: https://github.com/qualcomm-linux/meta-qcom/commit/abc1234
  # - type: patch
  #   path: /home/user/fixes/fix-audio.patch

workspace:    "<local meta-qcom/meta-qcom-3rdparty checkout path used>"
machine:      "<machine>"
distro:       "qcom-distro"
image:        "<image built in Section 10, e.g. qcom-console-image>"
build_config: "<KAS_YAMLS value used, e.g. ci/<machine>.yml:ci/qcom-distro.yml>"
```

- List every PR/commit the whole chain produced, in the order they were
  applied (qcom-ptool merge first if this run included Section 9, then
  the meta-qcom PR) — not just this skill's own PR.
- If invoked standalone (no Section 9 SRCREV-bump leg this run), omit the
  first `changes` entry — only list what this run itself produced.
- `workspace`/`machine`/`distro`/`image`/`build_config` are filled with
  the actual values already known at this point, not left blank. `image`
  must match the actual `--target` Section 10 built, not always the
  sample value shown here.

On a failed build (Section 10 stopped things short):

```yaml
status: "fail"

repo:        "https://github.com/$DISTRO_GITHUB_ORG/<repo>.git"
branch:      "add/<machine>"
type:        "distro"

changes: []

workspace:    "<local meta-qcom/meta-qcom-3rdparty checkout path used>"
machine:      "<machine>"
distro:       "qcom-distro"
image:        "<image built in Section 10, e.g. qcom-console-image>"
build_config: "<KAS_YAMLS value used>"
```

`machine`/`distro`/`image`/`build_config` stay filled in even on failure —
those are known regardless of whether the build succeeded; only `changes`
is empty since nothing was committed or opened.

## Notes

- meta-qcom's primary branch is `master`; meta-qcom-3rdparty's is `main`
  (both also carry LTS branches — check the target repo before branching).
- Reference-board additions (meta-qcom) and third-party additions
  (meta-qcom-3rdparty) share the machine-conf mental model but diverge on
  recipe ownership — meta-qcom centralizes SoC-level recipes, 3rdparty
  layers add only board-unique ones and depend on meta-qcom for the rest.
- Never guess `DISTRO_GITHUB_ORG` — if it's unset, stop and ask. A wrong
  org silently pushes a branch and opens a PR against someone else's repo.
- On a failed build (Section 10), attempt a fix (capped at 3 attempts)
  before reporting failure — see Section 10 for the diagnose/fix/retry
  loop and its limits.
- For subsequent work on the new machine, follow up with
  `qcom-yocto-build-image` (build), `qcom-flash-qdl`/`qcom-boot-validate`
  (flash and validate on hardware), and `qcom-yocto-pre-pr-checks` before
  the PR is reviewed.
