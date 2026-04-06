"""
Session trace utilities — parse thinking blocks and subagent IDs from OpenClaw traces.

Usage:
    from observability.session_trace import extract_thinking, extract_subagent_ids, parse_trace

    thinking = extract_thinking(trace)
    subagent_ids = extract_subagent_ids(trace)
"""

import json
from typing import List, Dict, Any, Optional


def extract_thinking(trace: list) -> List[Dict[str, Any]]:
    """
    Extract all thinking blocks from a session trace.

    Returns list of {"timestamp", "thinking"} dicts.
    """
    results = []
    for entry in trace:
        if entry.get("type") != "message":
            continue
        msg = entry.get("message", {})
        if msg.get("role") != "assistant":
            continue
        for block in msg.get("content", []):
            if block.get("type") == "thinking":
                results.append({
                    "timestamp": entry.get("timestamp"),
                    "thinking": block.get("thinking", ""),
                    "signature": block.get("thinkingSignature", ""),
                })
    return results


def extract_subagent_ids(trace: list) -> List[Dict[str, Any]]:
    """
    Extract all subagent session IDs spawned via sessions_spawn tool calls.

    Returns list of {"timestamp", "session_id", "agent_id", "task", "session_id_known"} dicts.

    Note on session_id: OpenClaw assigns session IDs internally after sessions_spawn
    returns. The UUID may appear in the thinking text (format: "agent:main:subagent:<uuid>")
    but this is not guaranteed — thinking may be truncated or omit it. When the UUID
    is not found in thinking, session_id is set to None and session_id_known=False.
    """
    import re
    results = []
    session_key_pattern = re.compile(
        r"agent:[^:]+:subagent:([a-f0-9-]{36})", re.IGNORECASE
    )

    for entry in trace:
        if entry.get("type") != "message":
            continue
        msg = entry.get("message", {})
        if msg.get("role") != "assistant":
            continue

        for block in msg.get("content", []):
            if not isinstance(block, dict):
                continue
            if block.get("type") != "toolCall":
                continue
            name = block.get("name", "")
            if name != "sessions_spawn":
                continue

            args = block.get("arguments", {})

            # Try to extract session UUID from thinking text of the same message
            session_id = None
            session_id_known = False
            for b2 in msg.get("content", []):
                if not isinstance(b2, dict):
                    continue
                if b2.get("type") != "thinking":
                    continue
                thinking_text = b2.get("thinking", "")
                match = session_key_pattern.search(thinking_text)
                if match:
                    session_id = match.group(1)
                    session_id_known = True
                    break

            results.append({
                "timestamp": entry.get("timestamp"),
                "session_id": session_id,
                "session_id_known": session_id_known,
                "agent_id": args.get("agentId", ""),
                "task": args.get("task", "")[:200],
            })
    return results


def parse_trace(trace: list) -> Dict[str, Any]:
    """
    Full parse of a session trace.

    Returns:
        dict with: thinking (list), subagents (list), tool_calls (list),
                   message_count, has_thinking, has_subagents
    """
    thinking = extract_thinking(trace)
    subagents = extract_subagent_ids(trace)

    tool_calls = []
    for entry in trace:
        if entry.get("type") != "message":
            continue
        msg = entry.get("message", {})
        if msg.get("role") != "assistant":
            continue
        for block in msg.get("content", []):
            if block.get("type") == "toolCall":
                tool_calls.append({
                    "name": block.get("name", ""),
                    "input": block.get("input", {}),
                })

    return {
        "thinking": thinking,
        "subagents": subagents,
        "tool_calls": tool_calls,
        "message_count": sum(1 for e in trace if e.get("type") == "message"),
        "has_thinking": len(thinking) > 0,
        "has_subagents": len(subagents) > 0,
    }
