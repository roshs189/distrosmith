# distrosmith

A Claude Code plugin for working on Qualcomm Yocto BSP layers (`meta-qcom`,
`meta-qcom-3rdparty`) and the `qcom-ptool` partition tooling. Skills work
against *your own* forks — no hardcoded org, repo path, or SSH key
required.

## Skills

- **`qcom-yocto-new-machine`** — bring up a new machine (board) in a Yocto
  BSP layer: `conf/machine/<machine>.conf`, matching `ci/<machine>.yml`, a
  new per-SoC include when needed, and (for third-party boards) the
  firmware-boot/packagegroup/u-boot recipes a board needs. Runs a single
  real `kas-container` build to validate the result but does not retry a
  failure, commit, or open a PR itself — see `distro-smith` for that.
- **`qcom-partition-conf-new-board`** — generate `qcom-ptool`'s
  `partitions.conf` and `contents.xml.in` for a new board, validate them by
  running `qcom-ptool` locally to produce flashable artifacts, then
  automatically commit the two source files to a new `add/<machine>`
  branch, open a PR against your `qcom-ptool` fork, and merge it.
- **`distro-smith`** — the combined end-to-end flow: runs
  `qcom-partition-conf-new-board` then `qcom-yocto-new-machine` for one
  board in a single invocation, bumping `qcom-ptool.inc`'s `SRCREV` to the
  merged partition commit, triggering a real `kas-container` build of
  `qcom-multimedia-image`, and — only if that build succeeds — opening the
  `meta-qcom` PR. Writes the run's outcome to `distro-params.yaml`
  outside the clone work directory. This orchestration is currently
  **meta-qcom-specific** (not
  `meta-qcom-3rdparty`), since the `SRCREV` bump it performs assumes that
  layer's `qcom-ptool.inc`.

All three skills source board facts (SoC, reference board, kernel
devicetree, partition table, chip IDs, etc.) from the `board-spec` MCP
server when a spec already exists for the target machine, falling back to
asking the user directly for genuinely new boards not yet documented
there.

## Env var contract

All three skills are driven by three env vars, exported in your own shell
before invoking them. Nothing else is configurable; repo names are always
`meta-qcom`, `qcom-ptool`, `board-spec`.

| Var | Required? | Meaning |
|---|---|---|
| `DISTRO_GITHUB_ORG` | **Yes** | GitHub org/user hosting your forks of `meta-qcom`, `qcom-ptool`, and `board-spec`. Never guessed — all three skills stop and ask if it's unset. |
| `GITHUB_TOKEN` | **Yes** | A GitHub PAT used for *both* git operations (HTTPS clone/push) and GitHub REST API calls (PR creation). Classic PAT with `repo` scope, or fine-grained with `Contents: Read and write` + `Pull requests: Read and write` on the relevant repos. **No SSH key is used anywhere in this bundle.** |
| `BUILD_DISTRO_ROOT` | No (default `$(pwd)/.distrosmith-work`, a work directory under the invocation cwd) | Local root under which the skills clone `meta-qcom`/`qcom-ptool`/`board-spec` themselves at run time, kept separate from any other checkouts you already have. `distro-smith` writes `distro-params.yaml` outside this directory, then removes this directory only on a successful run — a failed run's checkout is left in place for debugging. |

Generate a token at https://github.com/settings/tokens if you don't have
one. Never commit it or paste it into a chat.

## Installing

The three skills (`distro-smith`, `qcom-partition-conf-new-board`,
`qcom-yocto-new-machine`) are packaged as a Claude Code plugin — install
this repo with `claude plugin install` (or `--plugin-dir` for local dev)
rather than copying files by hand.

`setup.py` handles only the `board-spec` MCP server, which is a separate
concern from the skills themselves: it clones your `board-spec-mcp` fork,
installs it into a dedicated venv, and registers it in a project's
`.mcp.json`. Run it from whichever project directory you'll invoke the
skills from — that's where the MCP server gets registered.

```sh
export DISTRO_GITHUB_ORG=<your-github-username-or-org>
export GITHUB_TOKEN=<your-github-pat>
cd /path/to/your/project
python3 /path/to/distrosmith/setup.py
```

`setup.py` will:

1. Verify `GITHUB_TOKEN` (prompting for it if not already exported).
2. Clone `board-spec-mcp` from `$DISTRO_GITHUB_ORG` into
   `~/.distrosmith/board-spec-mcp` (skipping if it already exists there).
3. Create a venv for `board-spec-mcp` and `pip install -e .` it.
4. Merge a `board-spec` MCP server entry into the current directory's
   `.mcp.json` (preserving any other entries already there).

Restart Claude Code (or run `/mcp`) to pick up the new MCP server.

`meta-qcom`, `qcom-ptool`, and `board-spec` are cloned by the skills
themselves under `$BUILD_DISTRO_ROOT` the first time you invoke them —
`setup.py` no longer touches those repos.

## Related repos

- `board-spec` — the git-branch-per-machine spec data these skills read
  (`boards/<machine>/machine.yaml` + `boards/<machine>/partition.yaml`).
- `board-spec-mcp` — the MCP server that serves `board-spec` to these
  skills.
