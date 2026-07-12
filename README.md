# distrosmith

Claude Code skills for working on Qualcomm Yocto BSP layers (`meta-qcom`,
`meta-qcom-3rdparty`) and the `qcom-ptool` partition tooling, packaged with
a single setup script so they work against *your own* forks — no
hardcoded org, repo path, or SSH key required.

## Skills

- **`qcom-yocto-new-machine`** — bring up a new machine (board) in a Yocto
  BSP layer: `conf/machine/<machine>.conf`, matching `ci/<machine>.yml`, a
  new per-SoC include when needed, and (for third-party boards) the
  firmware-boot/packagegroup/u-boot recipes a board needs. Also commits
  the change and opens a PR against your fork automatically.
- **`qcom-partition-conf-new-board`** — generate `qcom-ptool`'s
  `partitions.conf` and `contents.xml.in` for a new board, validate them by
  running `qcom-ptool` locally to produce flashable artifacts, then
  automatically commit the two source files to a new `add/<machine>`
  branch and open a PR against your `qcom-ptool` fork.

Both skills source board facts (SoC, reference board, kernel devicetree,
partition table, chip IDs, etc.) from the `board-spec` MCP server when a
spec already exists for the target machine, falling back to asking the
user directly for genuinely new boards not yet documented there.

## Env var contract

Both skills — and `setup.py` — are driven by three env vars. Nothing else
is configurable; repo names are always `meta-qcom`, `qcom-ptool`,
`board-spec`, `board-spec-mcp`.

| Var | Required? | Meaning |
|---|---|---|
| `DISTRO_GITHUB_ORG` | **Yes** | GitHub org/user hosting your forks of all four repos above. Never guessed — both skills stop and ask if it's unset. |
| `GITHUB_TOKEN` | **Yes** | A GitHub PAT used for *both* git operations (HTTPS clone/push) and GitHub REST API calls (PR creation). Classic PAT with `repo` scope, or fine-grained with `Contents: Read and write` + `Pull requests: Read and write` on the relevant repos. **No SSH key is used anywhere in this bundle.** |
| `BUILD_DISTRO_ROOT` | No (default `/tmp/distrosmith-repos`) | Local root under which the four repos get cloned, kept separate from any other checkouts you already have. |

Generate a token at https://github.com/settings/tokens if you don't have
one. Never commit it or paste it into a chat — `setup.py` only ever reads
it from `--token`/`GITHUB_TOKEN`/an interactive prompt, and persists it to
`~/.distrosmith/env` (chmod 600), never into any file tracked by this repo
or the cloned repos.

## Installing

```sh
git clone <this-repo> distrosmith
cd distrosmith
export DISTRO_GITHUB_ORG=<your-github-username-or-org>
python3 setup.py --project-dir /path/to/your/meta-qcom-checkout
```

`setup.py` will:

1. Prompt for `GITHUB_TOKEN` if not already exported, and verify it works.
2. Clone `meta-qcom`, `qcom-ptool`, `board-spec`, `board-spec-mcp` from
   `$DISTRO_GITHUB_ORG` under `$BUILD_DISTRO_ROOT` (skipping any that
   already exist there).
3. Create a venv for `board-spec-mcp` and `pip install -e .` it.
4. Merge a `board-spec` MCP server entry into `--project-dir`'s
   `.mcp.json` (preserving any other entries already there).
5. Copy both skills into `~/.claude/skills/`.
6. Write `DISTRO_GITHUB_ORG`/`BUILD_DISTRO_ROOT`/`GITHUB_TOKEN` to
   `~/.distrosmith/env` (chmod 600) and print a `source` line to add to
   your shell rc — it never edits your shell rc for you.

Restart Claude Code (or run `/mcp`/reload skills) to pick up the new MCP
server and skills.

## Related repos

- `board-spec` — the git-branch-per-machine spec data these skills read
  (`boards/<machine>/machine.yaml` + `boards/<machine>/partition.yaml`).
- `board-spec-mcp` — the MCP server that serves `board-spec` to these
  skills.
