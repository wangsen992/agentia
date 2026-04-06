# Agents package — agent runtime adapters
#
# Design: Agent Adapter Pattern
# See: specs/002_agent_adapter.md
#
# The relay and harnesses talk to the AgentAdapter interface,
# not to specific agent runtimes. This makes it trivial to
# switch between OpenClaw, pi-agent, AutoGen, etc.
