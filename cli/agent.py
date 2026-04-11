#!/usr/bin/env python3
"""
agentia-agent — Agent-side CLI

Runs on the machine where the agent is deployed.
Commands: setup, serve
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path

# Default paths for agent setup.
# When running inside a Docker container with a bind mount at /workspace,
# these resolve inside the container. The Docker run command overrides them
# with explicit --workspace and --config arguments.
#
# New design: host ~/.agentia/agents/<name>/ mounted to container ~/.pi/agent/
# PI_DIR is set via environment variable.
DEFAULT_CONFIG_PATH = (
    Path.home() / ".agentia" / "agents"
)  # parent; agent name appended at runtime
DEFAULT_WORKSPACE = Path.home() / ".pi" / "agent"


def cmd_setup(
    adapter: str,
    config_path: str,
    agent_id: str,
    provider: str,
    model: str,
    workspace: str,
    role_goal: str,
    backstory: str,
    skills: list[str],
    var_overrides: dict,
    setup_dir: Path,
) -> int:
    """
    Render bootstrap files (AGENTS.md, SYSTEM.md, TOOLS.md) + run install.sh.
    Must be called before first `serve`.
    """
    config_path = Path(config_path)

    context = _build_context(
        agent_id=agent_id,
        adapter=adapter,
        provider=provider,
        model=model,
        workspace=workspace,
        role_goal=role_goal,
        backstory=backstory,
        skills=skills,
        var_overrides=var_overrides,
    )

    _render_templates(
        adapter=adapter,
        context=context,
        config_output=config_path,
        workspace=Path(workspace),
        setup_dir=setup_dir,
    )

    install_sh = setup_dir / "adapters" / adapter / "install.sh"
    if install_sh.exists():
        result = subprocess.run(
            ["bash", str(install_sh), workspace, str(config_path)],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            print(f"[agentia-agent] install.sh failed:\n{result.stderr}")
            return 1
        print(f"[agentia-agent] Runtime installed: {adapter}")
    else:
        print(f"[agentia-agent] No install.sh for {adapter}, skipping runtime install")

    print(f"[agentia-agent] Setup complete for {agent_id}")
    return 0


def cmd_serve(
    config_path: str,
    setup_dir: Path,
    install_adapter: str | None,
    agent_id: str,
    provider: str,
    model: str,
    workspace: str,
    role_goal: str,
    backstory: str,
    skills: list[str],
    var_overrides: dict,
    session_ttl: int = 1800,
    max_sessions: int = 10,
    context_threshold: int = 75,
) -> int:
    """
    Start AgentServer HTTP API.

    If --install <adapter> is given, runs setup first.
    """
    if install_adapter:
        print(f"[agentia-agent] Installing {install_adapter} runtime...")
        result = cmd_setup(
            adapter=install_adapter,
            config_path=config_path,
            agent_id=agent_id,
            provider=provider,
            model=model,
            workspace=workspace,
            role_goal=role_goal,
            backstory=backstory,
            skills=skills,
            var_overrides=var_overrides,
            setup_dir=setup_dir,
        )
        if result != 0:
            print(f"[agentia-agent] Setup failed, not starting AgentServer")
            return result

    print(f"[agentia-agent] Starting AgentServer with config: {config_path}")
    cmd = [
        "python3",
        "/agent/agent_runtime/server.py",
        "--config",
        str(config_path),
        "--session-ttl",
        str(session_ttl),
        "--max-sessions",
        str(max_sessions),
        "--context-threshold",
        str(context_threshold),
    ]
    os.execvp("python3", cmd)


# ─── Template rendering (shared) ───────────────────────────────────────────────


def _render_templates(
    adapter: str,
    context: dict,
    config_output: Path,
    workspace: Path,
    setup_dir: Path,
):
    try:
        from jinja2 import Environment, FileSystemLoader
    except ImportError:
        print("[agentia-agent] Jinja2 required: pip install jinja2")
        raise RuntimeError("Jinja2 not installed: pip install jinja2")

    adapter_dir = setup_dir / "adapters" / adapter
    if not adapter_dir.exists():
        raise ValueError(f"Unknown adapter: {adapter}")

    env = Environment(
        loader=FileSystemLoader(str(adapter_dir)), keep_trailing_newline=True
    )
    env.globals["env"] = os.environ

    config_output.parent.mkdir(parents=True, exist_ok=True)
    config_tmpl = env.get_template("config.tmpl")
    rendered_config = config_tmpl.render(**context)
    config_output.write_text(rendered_config)
    print(f"[agentia-agent] Config rendered: {config_output}")

    bootstrap_dir = adapter_dir / "bootstrap"
    if bootstrap_dir.exists():
        for tmpl_file in bootstrap_dir.glob("*.tmpl"):
            output_name = tmpl_file.stem
            tmpl = env.get_template(f"bootstrap/{tmpl_file.name}")
            rendered = tmpl.render(**context)
            output_path = workspace / output_name
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(rendered)
            print(f"[agentia-agent] Bootstrap rendered: {output_path}")


def _build_context(
    agent_id: str,
    adapter: str,
    provider: str,
    model: str,
    workspace: str,
    role_goal: str,
    backstory: str,
    skills: list[str],
    var_overrides: dict,
) -> dict:
    context = {
        "agent_id": agent_id,
        "adapter": adapter,
        "provider": provider,
        "model": model,
        "workspace": workspace,
        "role_goal": role_goal or "",
        "backstory": backstory or "",
        "skills": skills or [],
        "env": {},
    }
    for k, v in os.environ.items():
        if k.startswith("AGENT_"):
            context["env"][k] = v
    context["env"].update(var_overrides)
    context.update(var_overrides)
    return context


# ─── CLI ───────────────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="agentia-agent",
        description="agentia-agent — Agent-side CLI for setup and serving",
    )
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    # agentia-agent setup <adapter>
    p_setup = sub.add_parser("setup", help="Render bootstrap files + install runtime")
    p_setup.add_argument(
        "adapter", choices=["pi-agent", "openclaw"], help="Agent runtime adapter"
    )
    p_setup.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG_PATH),
        help=f"Config output path (default: {DEFAULT_CONFIG_PATH})",
    )
    p_setup.add_argument("--agent-id", default="agent-001", help="Agent ID")
    p_setup.add_argument("--provider", default="minimax", help="LLM provider")
    p_setup.add_argument("--model", default="MiniMax-M2.7", help="Model name")
    p_setup.add_argument(
        "--workspace",
        default=str(DEFAULT_WORKSPACE),
        help=f"Agent workspace path (default: {DEFAULT_WORKSPACE})",
    )
    p_setup.add_argument("--role-goal", default="", help="Agent role goal")
    p_setup.add_argument("--backstory", default="", help="Agent backstory")
    p_setup.add_argument("--skills", action="append", default=[], help="Skill name")
    p_setup.add_argument(
        "--var",
        action="append",
        default=[],
        dest="vars",
        help="key=value template variable override",
    )

    # agentia-agent serve
    p_serve = sub.add_parser("serve", help="Start AgentServer HTTP API")
    p_serve.add_argument(
        "--install",
        choices=["pi-agent", "openclaw"],
        default=None,
        help="Run setup first before serving",
    )
    p_serve.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG_PATH),
        help=f"Config path (default: {DEFAULT_CONFIG_PATH})",
    )
    p_serve.add_argument("--agent-id", default="agent-001", help="Agent ID")
    p_serve.add_argument("--provider", default="minimax", help="LLM provider")
    p_serve.add_argument("--model", default="MiniMax-M2.7", help="Model name")
    p_serve.add_argument(
        "--workspace",
        default=str(DEFAULT_WORKSPACE),
        help=f"Agent workspace path (default: {DEFAULT_WORKSPACE})",
    )
    p_serve.add_argument("--role-goal", default="", help="Agent role goal")
    p_serve.add_argument("--backstory", default="", help="Agent backstory")
    p_serve.add_argument("--skills", action="append", default=[], help="Skill name")
    p_serve.add_argument(
        "--var",
        action="append",
        default=[],
        dest="vars",
        help="key=value template variable override",
    )
    p_serve.add_argument(
        "--session-ttl",
        type=int,
        default=1800,
        help="Session idle TTL in seconds (default: 1800)",
    )
    p_serve.add_argument(
        "--max-sessions",
        type=int,
        default=10,
        help="Max concurrent running sessions (default: 10)",
    )
    p_serve.add_argument(
        "--context-threshold",
        type=int,
        default=75,
        help="Context %% threshold for auto-compact (default: 75)",
    )

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 0

    # __file__ is /workspace/cli/agent.py — go up two levels to /workspace
    agentia_root = Path(__file__).parent.parent
    setup_dir = agentia_root / "setup"

    if args.command == "setup":
        var_overrides = {}
        for v in getattr(args, "vars", []):
            if "=" in v:
                k, val = v.split("=", 1)
                var_overrides[k] = val
        return cmd_setup(
            adapter=args.adapter,
            config_path=args.config,
            agent_id=args.agent_id,
            provider=args.provider,
            model=args.model,
            workspace=args.workspace,
            role_goal=args.role_goal,
            backstory=args.backstory,
            skills=args.skills or [],
            var_overrides=var_overrides,
            setup_dir=setup_dir,
        )

    if args.command == "serve":
        var_overrides = {}
        for v in getattr(args, "vars", []):
            if "=" in v:
                k, val = v.split("=", 1)
                var_overrides[k] = val
        return cmd_serve(
            config_path=args.config,
            setup_dir=setup_dir,
            install_adapter=args.install,
            agent_id=args.agent_id,
            provider=args.provider,
            model=args.model,
            workspace=args.workspace,
            role_goal=args.role_goal,
            backstory=args.backstory,
            skills=args.skills or [],
            var_overrides=var_overrides,
            session_ttl=args.session_ttl,
            max_sessions=args.max_sessions,
            context_threshold=args.context_threshold,
        )


if __name__ == "__main__":
    sys.exit(main())
