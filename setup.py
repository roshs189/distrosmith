#!/usr/bin/env python3
"""Set up the board-spec MCP server for the distrosmith skills: clones
board-spec-mcp from your fork, installs it into a dedicated venv, and
registers it in a project's .mcp.json. Cloning meta-qcom, qcom-ptool, and
board-spec is handled by the skills themselves at run time, not by this
script.
"""
import argparse
import getpass
import json
import os
import subprocess
import sys
import venv
from pathlib import Path

BOARD_SPEC_MCP_ROOT = Path.home() / ".distrosmith" / "board-spec-mcp"


def parse_args():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--org", default=os.environ.get("DISTRO_GITHUB_ORG"),
                    help="GitHub org/user hosting your board-spec-mcp fork (or set DISTRO_GITHUB_ORG)")
    p.add_argument("--token", default=os.environ.get("GITHUB_TOKEN"),
                    help="GitHub PAT (or set GITHUB_TOKEN); prompted for if omitted")
    p.add_argument("--skip-clone", action="store_true",
                    help="Skip cloning board-spec-mcp (useful for re-running the rest)")
    return p.parse_args()


def verify_token(token):
    import urllib.request
    req = urllib.request.Request(
        "https://api.github.com/user",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        if e.code == 401:
            sys.exit("GITHUB_TOKEN is invalid (401 from GET /user). Generate a new PAT at "
                      "https://github.com/settings/tokens and re-run.")
        raise
    login = data.get("login")
    if not login:
        sys.exit("GET /user succeeded but returned no 'login' field — unexpected response.")
    print(f"Token OK, authenticated as {login}")
    return login


def clone_board_spec_mcp(org, dest, token):
    if dest.exists():
        print(f"  board-spec-mcp: already present at {dest}, skipping clone")
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    url = f"https://{token}@github.com/{org}/board-spec-mcp.git"
    print(f"  board-spec-mcp: cloning into {dest}")
    subprocess.run(["git", "clone", url, str(dest)], check=True)
    # Strip the token back out of the stored remote URL — git writes the
    # clone URL verbatim into .git/config, which would otherwise leave the
    # PAT sitting in plaintext on disk (and in any `git remote -v` output).
    clean_url = f"https://github.com/{org}/board-spec-mcp.git"
    subprocess.run(["git", "-C", str(dest), "remote", "set-url", "origin", clean_url], check=True)


def setup_board_spec_mcp(root):
    if not root.exists():
        print("  board-spec-mcp checkout missing, skipping venv setup")
        return None
    venv_dir = root / ".venv"
    if not venv_dir.exists():
        print(f"  creating venv at {venv_dir}")
        venv.create(str(venv_dir), with_pip=True)
    pip = venv_dir / "bin" / "pip"
    print("  pip install -e . (board-spec-mcp)")
    subprocess.run([str(pip), "install", "-e", "."], check=True, cwd=str(root))
    return venv_dir / "bin" / "board-spec-mcp"


def merge_mcp_json(project_dir, board_spec_mcp_bin):
    if board_spec_mcp_bin is None:
        return
    mcp_json_path = Path(project_dir) / ".mcp.json"
    data = {"mcpServers": {}}
    if mcp_json_path.exists():
        data = json.loads(mcp_json_path.read_text())
        data.setdefault("mcpServers", {})
    data["mcpServers"]["board-spec"] = {"command": str(board_spec_mcp_bin)}
    mcp_json_path.write_text(json.dumps(data, indent=2) + "\n")
    print(f"  merged board-spec entry into {mcp_json_path}")


def main():
    args = parse_args()

    if not args.org:
        sys.exit("DISTRO_GITHUB_ORG is required — pass --org or export DISTRO_GITHUB_ORG.")
    token = args.token or getpass.getpass("GitHub PAT (GITHUB_TOKEN): ")
    if not token:
        sys.exit("GITHUB_TOKEN is required — pass --token or export GITHUB_TOKEN.")

    print("Verifying GitHub token...")
    verify_token(token)

    if not args.skip_clone:
        clone_board_spec_mcp(args.org, BOARD_SPEC_MCP_ROOT, token)

    print("Setting up board-spec-mcp...")
    board_spec_mcp_bin = setup_board_spec_mcp(BOARD_SPEC_MCP_ROOT)

    project_dir = os.getcwd()
    print(f"Registering board-spec MCP server in {project_dir}/.mcp.json...")
    merge_mcp_json(project_dir, board_spec_mcp_bin)

    print()
    print("Setup complete.")
    print(f"  board-spec-mcp checkout: {BOARD_SPEC_MCP_ROOT}")
    print(f"  MCP server registered in: {project_dir}/.mcp.json")
    print()
    print("The distro-smith, qcom-partition-conf-new-board, and "
          "qcom-yocto-new-machine skills are installed as a Claude Code "
          "plugin (see README.md) — this script no longer copies them into "
          "~/.claude/skills/.")
    print()
    print("Export DISTRO_GITHUB_ORG and GITHUB_TOKEN in your shell before "
          "invoking any of the skills — they clone meta-qcom, qcom-ptool, "
          "and board-spec themselves at run time.")
    print("No SSH key is required — all git and GitHub API auth uses GITHUB_TOKEN over HTTPS.")


if __name__ == "__main__":
    main()
