#!/usr/bin/env python3
"""
agentia provision — Agent provisioning CLI

Provisions agent containers for the agentia multi-agent system.

Usage:
    python3 provision.py create <agent-id> <role> [options]
    python3 provision.py teardown <agent-id> [options]
    python3 provision.py list
    python3 provision.py status [agent-id]

Examples:
    python3 provision.py create analyst "You are the Analyst"
    python3 provision.py create critic "You are the Critic"
    python3 provision.py teardown analyst
    python3 provision.py status
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

# Add this dir to path so adapters can be imported
sys.path.insert(0, str(Path(__file__).parent))

from adapters.openclaw import OpenClawAdapter

DEFAULT_BASE_DIR = Path("/tmp/agentia")
DEFAULT_IMAGE = "agentia"


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def build_workspace(
    workspace_dir: Path,
    role: str,
    base_template: Path,
    roles_dir: Path,
) -> None:
    """
    Build a workspace from the template, then apply role overrides.
    """
    # Copy from template
    if base_template.exists():
        for item in base_template.iterdir():
            dest = workspace_dir / item.name
            if item.is_file():
                shutil.copy2(item, dest)
            elif item.is_dir() and item.name != "__pycache__":
                shutil.copytree(item, dest, dirs_exist_ok=True)

    # Apply role override if it exists
    role_file = roles_dir / f"{role}.md"
    if role_file.exists():
        dest_soul = workspace_dir / "SOUL.md"
        role_content = role_file.read_text()
        # Remove the header comment since it's injected
        if role_content.startswith("# SOUL.md Override"):
            role_content = role_content.split("\n", 2)[-1]
        dest_soul.write_text(role_content.strip() + "\n")
        print(f"[provision] Applied role override for '{role}'")
    else:
        print(f"[provision] No role override found for '{role}', using template")


def cmd_create(args) -> int:
    base_dir = Path(args.base_dir)
    workspace_dir = base_dir / "workspaces" / args.agent_id
    openclaw_dir = base_dir / "openclaw" / args.agent_id
    inbox_dir = base_dir / "inbox"

    print(f"[provision] Creating agent '{args.agent_id}'")
    print(f"  workspace: {workspace_dir}")
    print(f"  openclaw:  {openclaw_dir}")
    print(f"  inbox:     {inbox_dir}")

    # Check if already exists
    container_name = f"agent-{args.agent_id}"
    result = subprocess.run(
        ["docker", "ps", "--filter", f"name={container_name}", "--format", "{{.Names}}"],
        capture_output=True,
        text=True,
    )
    if container_name in result.stdout:
        print(f"[provision] Container {container_name} already running — tearing down first")
        cmd_teardown(args)

    # Create directories
    ensure_dir(workspace_dir)
    ensure_dir(openclaw_dir)
    ensure_dir(inbox_dir)

    # Build workspace from template
    script_dir = Path(__file__).parent
    template_dir = script_dir / "workspaces" / "template"
    roles_dir = script_dir / "workspaces" / "roles"

    build_workspace(workspace_dir, args.role, template_dir, roles_dir)

    # Provision identity
    adapter = OpenClawAdapter(image=args.image)
    adapter.setup_identity(openclaw_dir, reuse=args.reuse_identity)

    # Start container
    adapter.start_container(
        agent_id=args.agent_id,
        workspace_dir=workspace_dir,
        openclaw_dir=openclaw_dir,
        inbox_dir=inbox_dir,
        mode=args.mode,
        poll_interval=args.poll_interval,
    )

    # Verify
    if not adapter.verify_ready(container_name, inbox_dir):
        print(f"[provision] WARNING: container started but may not be ready")

    print(f"[provision] Agent '{args.agent_id}' provisioned successfully")
    return 0


def cmd_teardown(args) -> int:
    adapter = OpenClawAdapter(image=args.image)
    container_name = f"agent-{args.agent_id}"

    # Stop container
    result = subprocess.run(
        ["docker", "ps", "--filter", f"name={container_name}", "--format", "{{.Names}}"],
        capture_output=True,
        text=True,
    )
    if container_name in result.stdout:
        adapter.stop_container(args.agent_id)
    else:
        print(f"[provision] No running container named '{container_name}'")

    # Clean up directories
    if not args.keep_state:
        base_dir = Path(args.base_dir)
        for subdir in ["workspaces", "openclaw"]:
            path = base_dir / subdir / args.agent_id
            if path.exists():
                shutil.rmtree(path)
                print(f"[provision] Removed {path}")

    print(f"[provision] Agent '{args.agent_id}' torn down")
    return 0


def cmd_list(args) -> int:
    base_dir = Path(args.base_dir)
    print(f"Agents in {base_dir}:")
    print()

    for subdir in ["workspaces", "openclaw"]:
        dir_path = base_dir / subdir
        if not dir_path.exists():
            continue
        for agent_dir in sorted(dir_path.iterdir()):
            if not agent_dir.is_dir():
                continue
            container_name = f"agent-{agent_dir.name}"
            result = subprocess.run(
                ["docker", "ps", "--filter", f"name={container_name}", "--format", "{{.Status}}"],
                capture_output=True,
                text=True,
            )
            status = result.stdout.strip() or "not running"
            print(f"  {agent_dir.name}: {status}")

    return 0


def cmd_status(args) -> int:
    base_dir = Path(args.base_dir)
    agent_id = args.agent_id

    container_name = f"agent-{agent_id}"
    result = subprocess.run(
        ["docker", "ps", "--filter", f"name={container_name}", "--format", "{{.Status}}"],
        capture_output=True,
        text=True,
    )
    status = result.stdout.strip() or "not running"
    print(f"Agent: {agent_id}")
    print(f"Container: {status}")

    for subdir in ["workspaces", "openclaw"]:
        dir_path = base_dir / subdir / agent_id
        exists = "exists" if dir_path.exists() else "not found"
        print(f"  {subdir}: {exists}")

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="agentia agent provisioning")
    sub = parser.add_subparsers(dest="command")

    # create
    p_create = sub.add_parser("create", help="Provision a new agent")
    p_create.add_argument("agent_id", help="Unique agent identifier")
    p_create.add_argument("role", help="Role name (analyst, critic, etc.)")
    p_create.add_argument(
        "--base-dir",
        default=str(DEFAULT_BASE_DIR),
        help=f"Base directory for all agentia state (default: {DEFAULT_BASE_DIR})",
    )
    p_create.add_argument(
        "--image", default=DEFAULT_IMAGE, help="Docker image name"
    )
    p_create.add_argument(
        "--mode",
        default="agent",
        choices=["echo", "agent"],
        help="Poller mode (default: agent)",
    )
    p_create.add_argument(
        "--poll-interval",
        type=float,
        default=2.0,
        help="Poll interval in seconds (default: 2.0)",
    )
    p_create.add_argument(
        "--no-reuse-identity",
        dest="reuse_identity",
        action="store_false",
        default=True,
        help="Regenerate identity even if it already exists",
    )

    # teardown
    p_teardown = sub.add_parser("teardown", help="Tear down an agent")
    p_teardown.add_argument("agent_id", help="Agent identifier")
    p_teardown.add_argument(
        "--base-dir",
        default=str(DEFAULT_BASE_DIR),
        help=f"Base directory (default: {DEFAULT_BASE_DIR})",
    )
    p_teardown.add_argument(
        "--image", default=DEFAULT_IMAGE, help="Docker image name"
    )
    p_teardown.add_argument(
        "--keep-state",
        action="store_true",
        help="Keep workspace and openclaw directories",
    )

    # list
    p_list = sub.add_parser("list", help="List all agents")
    p_list.add_argument(
        "--base-dir",
        default=str(DEFAULT_BASE_DIR),
        help=f"Base directory (default: {DEFAULT_BASE_DIR})",
    )

    # status
    p_status = sub.add_parser("status", help="Show agent status")
    p_status.add_argument("agent_id", help="Agent identifier")
    p_status.add_argument(
        "--base-dir",
        default=str(DEFAULT_BASE_DIR),
        help=f"Base directory (default: {DEFAULT_BASE_DIR})",
    )

    args = parser.parse_args()

    if args.command == "create":
        return cmd_create(args)
    elif args.command == "teardown":
        return cmd_teardown(args)
    elif args.command == "list":
        return cmd_list(args)
    elif args.command == "status":
        return cmd_status(args)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
