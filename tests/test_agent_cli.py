import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cli.agent as agent_cli


class AgentCliServePathTest(unittest.TestCase):
    def test_cmd_serve_execs_agent_runtime_server_path(self):
        with tempfile.TemporaryDirectory() as td:
            config_path = str(Path(td) / "agent.json")
            setup_dir = Path(td) / "setup"
            setup_dir.mkdir(parents=True)

            with patch.object(agent_cli.os, "execvp") as execvp:
                agent_cli.cmd_serve(
                    config_path=config_path,
                    setup_dir=setup_dir,
                    install_adapter=None,
                    agent_id="agent-001",
                    provider="minimax",
                    model="MiniMax-M2.7",
                    workspace="/workspace",
                    role_goal="",
                    backstory="",
                    skills=[],
                    var_overrides={},
                    session_ttl=1800,
                    max_sessions=10,
                    context_threshold=75,
                )

        execvp.assert_called_once()
        program, argv = execvp.call_args.args
        self.assertEqual(program, "python3")
        self.assertEqual(argv[0], "python3")
        self.assertEqual(argv[1], "/agent/agent_runtime/server.py")
        self.assertNotIn("/agent/agent_side/server.py", argv)
        self.assertIn("--config", argv)
        self.assertIn(config_path, argv)


if __name__ == "__main__":
    unittest.main()
