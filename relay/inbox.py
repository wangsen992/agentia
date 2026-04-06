"""
Inbox — async message inbox with file-based persistence.

Each agent has an inbox file: <inbox_dir>/<agent_id>.jsonl
Messages are appended as received. Agent reads and processes them.

Usage:
    inbox = Inbox(agent_id="agent-b", base_dir="/workspace/inbox")
    inbox.append(Message(from_agent="agent-a", content="hello"))
    messages = inbox.read_all()  # returns and marks as read
    inbox.mark_processed(message_ids)  # optional cleanup
"""

import json
import os
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional


@dataclass
class Message:
    """A message in the inbox."""
    id: str
    from_agent: str
    to_agent: str
    content: str
    timestamp: float
    correlation_id: Optional[str] = None
    reply_to: Optional[str] = None

    @classmethod
    def new(cls, from_agent: str, to_agent: str, content: str,
            correlation_id: Optional[str] = None, reply_to: Optional[str] = None) -> "Message":
        return cls(
            id=str(uuid.uuid4()),
            from_agent=from_agent,
            to_agent=to_agent,
            content=content,
            timestamp=datetime.now().timestamp(),
            correlation_id=correlation_id,
            reply_to=reply_to,
        )

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, line: str) -> "Message":
        data = json.loads(line)
        return cls(**data)


class Inbox:
    """
    Persistent inbox for one agent, stored as JSON Lines.

    File format: one JSON object per line, newest last.
    After reading, caller should mark messages as processed.
    """

    def __init__(self, agent_id: str, base_dir: str = "/workspace/inbox"):
        self.agent_id = agent_id
        self.path = Path(base_dir) / f"{agent_id}.jsonl"
        self._processed_marker = Path(base_dir) / f".{agent_id}.processed"

        # Ensure directory exists
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, message: Message) -> bool:
        """Append a message to the inbox file. Returns True on success."""
        try:
            with open(self.path, "a") as f:
                f.write(message.to_json() + "\n")
            return True
        except Exception as e:
            return False

    def read_all(self) -> list[Message]:
        """
        Read all messages from the inbox (newest last).
        Does NOT mark them as processed — call mark_processed() after handling.
        Returns empty list if file doesn't exist.
        """
        if not self.path.exists():
            return []

        messages = []
        try:
            with open(self.path, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    messages.append(Message.from_json(line))
        except Exception:
            return []

        return messages

    def mark_processed(self, message_ids: list[str]) -> None:
        """
        Remove processed messages from the inbox file.
        Rewrites the file with only unprocessed messages.
        """
        if not self.path.exists():
            return

        ids_to_remove = set(message_ids)
        remaining = []

        try:
            with open(self.path, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    msg = Message.from_json(line)
                    if msg.id not in ids_to_remove:
                        remaining.append(line)

            # Rewrite file with remaining messages
            with open(self.path, "w") as f:
                for line in remaining:
                    f.write(line + "\n")

        except Exception:
            pass

    def pending_count(self) -> int:
        """Return number of pending messages."""
        if not self.path.exists():
            return 0
        try:
            with open(self.path, "r") as f:
                return sum(1 for line in f if line.strip())
        except Exception:
            return 0

    def clear(self) -> None:
        """Clear all messages from inbox."""
        if self.path.exists():
            self.path.unlink()


class InboxStore:
    """
    Manages inboxes for all agents.

    Provides factory methods to get/create inboxes per agent.
    """

    def __init__(self, base_dir: str = "/workspace/inbox"):
        self.base_dir = base_dir
        Path(base_dir).mkdir(parents=True, exist_ok=True)

    def get_inbox(self, agent_id: str) -> Inbox:
        """Get the inbox for an agent."""
        return Inbox(agent_id=agent_id, base_dir=self.base_dir)

    def list_agents(self) -> list[str]:
        """List all agent IDs that have inboxes."""
        inbox_dir = Path(self.base_dir)
        if not inbox_dir.exists():
            return []
        return [
            p.stem for p in inbox_dir.iterdir()
            if p.suffix == ".jsonl" and not p.name.startswith(".")
        ]
