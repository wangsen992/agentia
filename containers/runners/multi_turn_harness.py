#!/usr/bin/env python3
"""
Multi-Turn Harness for OpenClaw Agent Experiments

Pattern:
- Turn 1: Agent delegates task to subagents, spawns them, returns
- Subsequent Turns: Agent checks subagent results, reports, may spawn new subagents
- Continue until: agent returns final answer (no more subagents to spawn)

Key insight: Harness just sends "Continue" repeatedly. Agent handles everything.
"""

import subprocess
import json
import time
import uuid
import os
from pathlib import Path
from typing import Optional


SESSION_DIR = Path.home() / ".openclaw" / "agents" / "main" / "sessions"


def get_session_trace(session_id: str) -> list:
    """Read session trace JSONL and return list of entries."""
    sessions_dir = SESSION_DIR
    if not sessions_dir.exists():
        return []

    session_files = sorted(
        sessions_dir.glob(f"{session_id}*.jsonl"),
        key=lambda f: f.stat().st_mtime,
        reverse=True
    )

    if not session_files:
        return []

    entries = []
    with open(session_files[0]) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return entries


def had_subagents(trace: list) -> bool:
    """Check if session trace contains sessions_spawn calls."""
    for entry in trace:
        if entry.get("type") == "message":
            msg = entry.get("message", {})
            if msg.get("role") == "assistant":
                content = msg.get("content", [])
                if isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "toolCall":
                            name = block.get("name", "")
                            if "spawn" in name.lower():
                                return True
    return False


def send_turn(session_id: str, message: str, workspace: Optional[str] = None) -> dict:
    """Send a turn to the agent via openclaw agent."""
    cmd = [
        "openclaw", "agent",
        "--session-id", session_id,
        "--message", message
    ]

    env = os.environ.copy()
    if workspace:
        env["OPENCLAW_WORKSPACE"] = workspace

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        env=env,
        timeout=120
    )

    return {
        "stdout": result.stdout,
        "stderr": result.stderr,
        "returncode": result.returncode
    }


class MultiTurnHarness:
    """
    Multi-turn harness using openclaw agent.
    
    The agent stays alive across turns via persistent session.
    Harness sends "Continue" until agent signals done.
    
    Flow:
    1. Send initial task with subagent delegation
    2. Agent spawns subagents, returns
    3. Harness sends "Continue"
    4. Agent checks subagent results, may spawn more subagents
    5. Repeat until agent returns final answer
    """

    def __init__(self, workspace: Optional[str] = None, max_turns: int = 10):
        self.workspace = workspace
        self.max_turns = max_turns
        self.turns = []
        self.traces = []

    def run(self, prompt: str, wait_seconds: float = 15.0) -> dict:
        """
        Run multi-turn delegation workflow.
        
        Args:
            prompt: Initial task prompt
            wait_seconds: Time to wait between turns for subagent completion
            
        Returns:
            dict with: session_id, turns (list of responses), final_answer
        """
        session_id = f"multi-{uuid.uuid4().hex[:8]}"

        # ── Turn 1 ───────────────────────────────────────────────────────────
        print(f"[Turn 1] Sending initial prompt...")
        result1 = send_turn(session_id, prompt, self.workspace)
        trace1 = get_session_trace(session_id)
        
        self.turns.append({"turn": 1, "response": result1, "trace": trace1})
        self.traces = trace1

        print(f"[Turn 1] Response: {result1['stdout'][:200].strip()}")

        # ── Multi-Turn Loop ─────────────────────────────────────────────────
        turn_num = 1
        
        while turn_num < self.max_turns:
            # Check if last turn had subagents
            if not had_subagents(self.traces):
                # No subagents in last turn → agent is done
                print(f"[Turn {turn_num}] No subagents spawned → Final answer")
                break
            
            # Wait for subagent completion
            print(f"[Turn {turn_num}] Subagents spawned, waiting {wait_seconds}s...")
            time.sleep(wait_seconds)
            
            # Get trace BEFORE next turn to detect subagents
            prev_trace = self.traces
            
            # Send Continue
            turn_num += 1
            print(f"[Turn {turn_num}] Continue...")
            result = send_turn(session_id, "Continue where you left off", self.workspace)
            trace = get_session_trace(session_id)
            
            self.turns.append({"turn": turn_num, "response": result, "trace": trace})
            self.traces = trace
            
            print(f"[Turn {turn_num}] Response: {result['stdout'][:200].strip()}")

        # ── Build Final Answer ───────────────────────────────────────────────
        final_answer = "\n\n".join(
            f"=== Turn {t['turn']} ===\n{t['response']['stdout'].strip()}"
            for t in self.turns
        )

        return {
            "session_id": session_id,
            "turns": self.turns,
            "total_turns": len(self.turns),
            "final_answer": final_answer
        }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Multi-Turn Harness for OpenClaw")
    parser.add_argument("--prompt", required=True, help="Task prompt")
    parser.add_argument("--workspace", help="Workspace directory")
    parser.add_argument("--wait", type=float, default=15.0, help="Wait seconds between turns")
    parser.add_argument("--max-turns", type=int, default=10, help="Max turns")

    args = parser.parse_args()

    harness = MultiTurnHarness(workspace=args.workspace, max_turns=args.max_turns)
    result = harness.run(args.prompt, wait_seconds=args.wait)

    print("\n" + "="*60)
    print("FINAL RESULT")
    print("="*60)
    print(json.dumps(result, indent=2, default=str))
