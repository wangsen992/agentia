"""
Internal harness for AgentServer.

Runs the delivery pattern (inbox or sync) in a background thread.
"""

import threading
import time
from typing import Optional

from .config import AgentServerConfig
from .patterns.inbox import InboxDelivery
from .patterns.sync import SyncDelivery


class Harness:
    """
    Manages the agent subprocess lifecycle and delivery pattern.

    The harness runs in a background thread. For inbox delivery, it polls
    the inbox file. For sync delivery, messages are processed directly.
    """

    def __init__(self, agent_id: str, config: AgentServerConfig):
        self.agent_id = agent_id
        self.config = config
        self._delivery = self._create_delivery()
        self._poller_thread: Optional[threading.Thread] = None
        self._running = False
        self._uptime = time.time()

    def _create_delivery(self):
        """Create the appropriate delivery pattern based on config."""
        if self.config.delivery == "inbox":
            return InboxDelivery(
                agent_id=self.agent_id,
                inbox_dir=self.config.inbox_dir,
                responses_dir=self.config.responses_dir,
                poll_interval=self.config.poll_interval,
                agent_timeout=self.config.agent_timeout,
            )
        elif self.config.delivery == "sync":
            return SyncDelivery(
                agent_id=self.agent_id,
                agent_timeout=self.config.agent_timeout,
            )
        else:
            raise ValueError(f"Unknown delivery pattern: {self.config.delivery}")

    def start(self):
        """Start the harness (background thread for inbox polling)."""
        self._running = True
        if self.config.delivery == "inbox":
            self._poller_thread = threading.Thread(
                target=self._run_inbox_loop,
                daemon=True,
                name=f"harness-{self.agent_id}",
            )
            self._poller_thread.start()
        print(
            f"[Harness] Started with {self.config.delivery} delivery for {self.agent_id}"
        )

    def _run_inbox_loop(self):
        """Background loop for inbox polling (inbox delivery only)."""
        while self._running:
            try:
                self._delivery.poll_once()
            except Exception as e:
                print(f"[Harness] poll_once error: {e}")
            time.sleep(self.config.poll_interval)

    def stop(self):
        """Stop the harness."""
        self._running = False
        if self._poller_thread is not None:
            self._poller_thread.join(timeout=5)
        print(f"[Harness] Stopped for {self.agent_id}")

    def teardown(self):
        """Teardown delivery pattern (adapter teardown)."""
        self._delivery.teardown()
        self._uptime = None

    def restart_agent(self):
        """Restart the agent subprocess by tearing down and recreating delivery."""
        print(f"[Harness] Restarting agent {self.agent_id}...")
        self._delivery.teardown()
        self._delivery = self._create_delivery()
        self._uptime = time.time()
        print(f"[Harness] Agent {self.agent_id} restarted")

    def get_status(self) -> dict:
        """Return harness status."""
        return {
            "agent_id": self.agent_id,
            "delivery": self.config.delivery,
            "uptime": time.time() - self._uptime if self._uptime else 0,
            "running": self._running,
        }

    def process_message_sync(self, content: str, correlation_id: str) -> dict:
        """
        Process a message synchronously (for sync delivery or when blocking is desired).

        Returns response dict.
        """
        if self.config.delivery != "sync":
            raise ValueError("process_message_sync only valid for sync delivery")
        return self._delivery.send(content, correlation_id)
