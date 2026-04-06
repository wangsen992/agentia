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

    Returns list of {"timestamp", "session_id", "agent_id", "message"} dicts.
    """
    results = []
    for entry in trace:
        if entry.get("type") != "message":
            continue
        msg = entry.get("message", {})
        if msg.get("role") != "assistant":
            continue
        for block in msg.get("content", []):
            if block.get("type") == "toolCall":
                name = block.get("name", "")
                if name == "sessions_spawn":
                    raw_args = block.get("rawArgs", {})
                    results.append({
                        "timestamp": entry.get("timestamp"),
                        "session_id": raw_args.get("sessionId", ""),
                        "agent_id": raw_args.get("agentId", ""),
                        "message": raw_args.get("message", "")[:200],
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
