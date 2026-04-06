#!/usr/bin/env python3
"""
Multi-Turn Harness for OpenClaw Agent Experiments

Pattern:
- Turn 1: Agent delegates task to subagents, spawns them, returns
- Subsequent Turns: Agent checks subagent results, reports, may spawn new subagents
- Continue until: agent returns final answer (no more subagents to spawn)

Key insight: Harness just sends "Continue" repeatedly. Agent handles everything.

Uses AgentAdapter — fully decoupled from OpenClaw specifics.
Session trace read via adapter.get_session_trace().
"""

import sys
import json
import time
import uuid
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from agents.adapters import get_adapter


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


def send_turn(adapter, message: str) -> dict:
    """Send a turn to the agent via the adapter."""
    result = adapter.send(message)
    return {
        "stdout": result.stdout,
        "stderr": result.stderr,
        "returncode": result.returncode
    }


class MultiTurnHarness:
    """
    Multi-turn harness using AgentAdapter.

    The agent stays alive across turns via persistent session.
    Harness sends "Continue" until agent signals done.
    """

    def __init__(self, workspace: Optional[str] = None, max_turns: int = 10):
        self.workspace = workspace
        self.max_turns = max_turns
        self.turns = []

    def run(self, prompt: str, wait_seconds: float = 15.0) -> dict:
        self._adapter = get_adapter(workspace=self.workspace)
        self._adapter.setup()
        session_id = self._adapter.start()

        try:
            # ── Turn 1 ───────────────────────────────────────────────────────────
            print(f"[Turn 1] Sending initial prompt...")
            result1 = send_turn(self._adapter, prompt)
            trace1 = self._adapter.get_session_trace(session_id)

            self.turns.append({"turn": 1, "response": result1, "trace": trace1})
            traces = trace1

            print(f"[Turn 1] Response: {result1['stdout'][:200].strip()}")

            # ── Multi-Turn Loop ─────────────────────────────────────────────────
            turn_num = 1

            while turn_num < self.max_turns:
                if not had_subagents(traces):
                    print(f"[Turn {turn_num}] No subagents spawned → Final answer")
                    break

                print(f"[Turn {turn_num}] Subagents spawned, waiting {wait_seconds}s...")
                time.sleep(wait_seconds)

                turn_num += 1
                print(f"[Turn {turn_num}] Continue...")
                result = send_turn(self._adapter, "Continue where you left off")
                trace = self._adapter.get_session_trace(session_id)

                self.turns.append({"turn": turn_num, "response": result, "trace": trace})
                traces = trace

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

        finally:
            self._adapter.stop()
            self._adapter.teardown()


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
