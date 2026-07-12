#!/usr/bin/env python3
"""Set up the distrosmith skill bundle: provisions env vars, clones the
repos both skills need, installs board-spec-mcp, registers it in a
project's .mcp.json, and copies the skills into ~/.claude/skills/.
"""
import argparse
import getpass
import json
import os
import shutil
import subprocess
import sys
import venv
from pathlib import Path

REPO_NAMES = ["meta-qcom", "qcom-ptool", "board-spec", "board-spec-mcp"]
DEFAULT_REPO_ROOT = "/tmp/distrosmith-repos"
ENV_FILE = Path.home() / ".distrosmith" / "env"
SKILLS_SRC = Path(__file__).resolve().parent / "skills"
SKILLS_DEST = Path.home() / ".claude" / "skills"


def parse_args():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--org", default=os.environ.get("DISTRO_GITHUB_ORG"),
                    help="GitHub org/user hosting the forks (or set DISTRO_GITHUB_ORG)")
    p.add_argument("--repo-root", default=os.environ.get("BUILD_DISTRO_ROOT", DEFAULT_REPO_ROOT),
                    help=f"Local root to clone repos into (default: {DEFAULT_REPO_ROOT})")
    p.add_argument("--token", default=os.environ.get("GITHUB_TOKEN"),
                    help="GitHub PAT (or set GITHUB_TOKEN); prompted for if omitted")
    p.add_argument("--project-dir", default=os.getcwd(),
                    help="Directory whose .mcp.json should get the board-spec server entry")
    p.add_argument("--skip-clone", action="store_true",
                    help="Skip cloning the 4 repos (useful for re-running the rest)")
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


def clone_repo(org, name, root, token):
    dest = Path(root) / name
    if dest.exists():
        print(f"  {name}: already present at {dest}, skipping clone")
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    url = f"https://{token}@github.com/{org}/{name}.git"
    print(f"  {name}: cloning into {dest}")
    subprocess.run(["git", "clone", url, str(dest)], check=True)


def setup_board_spec_mcp(root):
    bsm = Path(root) / "board-spec-mcp"
    if not bsm.exists():
        print("  board-spec-mcp checkout missing, skipping venv setup")
        return None
    venv_dir = bsm / ".venv"
    if not venv_dir.exists():
        print(f"  creating venv at {venv_dir}")
        venv.create(str(venv_dir), with_pip=True)
    pip = venv_dir / "bin" / "pip"
    print("  pip install -e . (board-spec-mcp)")
    subprocess.run([str(pip), "install", "-e", "."], check=True, cwd=str(bsm))
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


def install_skills():
    SKILLS_DEST.mkdir(parents=True, exist_ok=True)
    for skill_dir in sorted(SKILLS_SRC.iterdir()):
        if not skill_dir.is_dir():
            continue
        dest = SKILLS_DEST / skill_dir.name
        shutil.rmtree(dest, ignore_errors=True)
        shutil.copytree(skill_dir, dest)
        print(f"  installed skill: {skill_dir.name} -> {dest}")


def persist_env(org, repo_root, token):
    ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
    ENV_FILE.write_text(
        f'export DISTRO_GITHUB_ORG="{org}"\n'
        f'export BUILD_DISTRO_ROOT="{repo_root}"\n'
        f'export GITHUB_TOKEN="{token}"\n'
    )
    ENV_FILE.chmod(0o600)


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
        print(f"Cloning repos under {args.repo_root} from org '{args.org}'...")
        for name in REPO_NAMES:
            clone_repo(args.org, name, args.repo_root, token)

    print("Setting up board-spec-mcp...")
    board_spec_mcp_bin = setup_board_spec_mcp(args.repo_root)

    print(f"Registering board-spec MCP server in {args.project_dir}/.mcp.json...")
    merge_mcp_json(args.project_dir, board_spec_mcp_bin)

    print(f"Installing skills into {SKILLS_DEST}...")
    install_skills()

    persist_env(args.org, args.repo_root, token)

    print()
    print("Setup complete.")
    print(f"  Repos cloned under: {args.repo_root}")
    print(f"  Skills installed:   {SKILLS_DEST}")
    print(f"  Env vars written to: {ENV_FILE} (chmod 600)")
    print()
    print(f"Add this to your shell rc to persist across sessions:")
    print(f"  source {ENV_FILE}")
    print("No SSH key is required — all git and GitHub API auth uses GITHUB_TOKEN over HTTPS.")


if __name__ == "__main__":
    main()
