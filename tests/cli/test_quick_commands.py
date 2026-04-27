"""Tests for user-defined quick commands that bypass the agent loop."""
import asyncio
import sys
import subprocess
import types
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock
from rich.text import Text
import pytest


@pytest.fixture(autouse=True)
def _clean_quick_command_guard_state(monkeypatch):
    monkeypatch.delenv("SAPPHIRE_REPO_PATH", raising=False)
    sys.modules.pop("_hermes_sapphire_command_guard", None)
    try:
        from tools import approval as approval_mod
        approval_mod._gateway_queues.clear()
        approval_mod._gateway_notify_cbs.clear()
        approval_mod._session_approved.clear()
        approval_mod._permanent_approved.clear()
        approval_mod._pending.clear()
    except Exception:
        pass
    yield
    sys.modules.pop("_hermes_sapphire_command_guard", None)
    try:
        from tools import approval as approval_mod
        approval_mod._gateway_queues.clear()
        approval_mod._gateway_notify_cbs.clear()
        approval_mod._session_approved.clear()
        approval_mod._permanent_approved.clear()
        approval_mod._pending.clear()
    except Exception:
        pass


# ── CLI tests ──────────────────────────────────────────────────────────────

class TestCLIQuickCommands:
    """Test quick command dispatch in HermesCLI.process_command."""

    @staticmethod
    def _printed_plain(call_arg):
        if isinstance(call_arg, Text):
            return call_arg.plain
        return str(call_arg)

    def _make_cli(self, quick_commands):
        from cli import HermesCLI
        cli = HermesCLI.__new__(HermesCLI)
        cli.config = {"quick_commands": quick_commands}
        cli.console = MagicMock()
        cli.agent = None
        cli.conversation_history = []
        # session_id is accessed by the fallback skill/fuzzy-match path in
        # process_command; without it, tests that exercise `/alias args`
        # can trip an AttributeError when cross-test state leaks a skill
        # command matching the alias target.
        cli.session_id = "test-session"
        return cli

    def test_exec_command_runs_and_prints_output(self):
        cli = self._make_cli({"dn": {"type": "exec", "command": "echo daily-note"}})
        result = cli.process_command("/dn")
        assert result is True
        cli.console.print.assert_called_once()
        printed = self._printed_plain(cli.console.print.call_args[0][0])
        assert printed == "daily-note"

    def test_exec_command_uses_chat_console_when_tui_is_live(self):
        cli = self._make_cli({"dn": {"type": "exec", "command": "echo daily-note"}})
        cli._app = object()
        live_console = MagicMock()

        with patch("cli.ChatConsole", return_value=live_console):
            result = cli.process_command("/dn")

        assert result is True
        live_console.print.assert_called_once()
        printed = self._printed_plain(live_console.print.call_args[0][0])
        assert printed == "daily-note"
        cli.console.print.assert_not_called()

    def test_exec_command_stderr_shown_on_no_stdout(self):
        cli = self._make_cli({"err": {"type": "exec", "command": "echo error >&2"}})
        result = cli.process_command("/err")
        assert result is True
        # stderr fallback — should print something
        cli.console.print.assert_called_once()

    def test_exec_command_no_output_shows_fallback(self):
        cli = self._make_cli({"empty": {"type": "exec", "command": "true"}})
        cli.process_command("/empty")
        cli.console.print.assert_called_once()
        args = cli.console.print.call_args[0][0]
        assert "no output" in args.lower()

    def test_alias_command_routes_to_target(self):
        """Alias quick commands rewrite to the target command."""
        cli = self._make_cli({"shortcut": {"type": "alias", "target": "/help"}})
        with patch.object(cli, "process_command", wraps=cli.process_command) as spy:
            cli.process_command("/shortcut")
            # Should recursively call process_command with /help
            spy.assert_any_call("/help")

    def test_alias_command_passes_args(self):
        """Alias quick commands forward user arguments to the target."""
        cli = self._make_cli({"sc": {"type": "alias", "target": "/context"}})
        with patch.object(cli, "process_command", wraps=cli.process_command) as spy:
            cli.process_command("/sc some args")
            spy.assert_any_call("/context some args")

    def test_alias_no_target_shows_error(self):
        cli = self._make_cli({"broken": {"type": "alias", "target": ""}})
        cli.process_command("/broken")
        cli.console.print.assert_called_once()
        args = cli.console.print.call_args[0][0]
        assert "no target defined" in args.lower()

    def test_unsupported_type_shows_error(self):
        cli = self._make_cli({"bad": {"type": "prompt", "command": "echo hi"}})
        cli.process_command("/bad")
        cli.console.print.assert_called_once()
        args = cli.console.print.call_args[0][0]
        assert "unsupported type" in args.lower()

    def test_missing_command_field_shows_error(self):
        cli = self._make_cli({"oops": {"type": "exec"}})
        cli.process_command("/oops")
        cli.console.print.assert_called_once()
        args = cli.console.print.call_args[0][0]
        assert "no command defined" in args.lower()

    def test_quick_command_takes_priority_over_skill_commands(self):
        """Quick commands must be checked before skill slash commands."""
        cli = self._make_cli({"mygif": {"type": "exec", "command": "echo overridden"}})
        with patch("cli._skill_commands", {"/mygif": {"name": "gif-search"}}):
            cli.process_command("/mygif")
        cli.console.print.assert_called_once()
        printed = self._printed_plain(cli.console.print.call_args[0][0])
        assert printed == "overridden"

    def test_unknown_command_still_shows_error(self):
        cli = self._make_cli({})
        with patch("cli._cprint") as mock_cprint:
            cli.process_command("/nonexistent")
            mock_cprint.assert_called()
            printed = " ".join(str(c) for c in mock_cprint.call_args_list)
            assert "unknown command" in printed.lower()

    def test_timeout_shows_error(self):
        cli = self._make_cli({"slow": {"type": "exec", "command": "sleep 100"}})
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("sleep", 30)):
            cli.process_command("/slow")
        cli.console.print.assert_called_once()
        args = cli.console.print.call_args[0][0]
        assert "timed out" in args.lower()


# ── Gateway tests ──────────────────────────────────────────────────────────

class TestGatewayQuickCommands:
    """Test quick command dispatch in GatewayRunner._handle_message."""

    @staticmethod
    def _stub_tirith(monkeypatch):
        fake_tirith = types.ModuleType("tools.tirith_security")
        fake_tirith.check_command_security = lambda _command: {
            "action": "allow",
            "findings": [],
            "summary": "",
        }
        monkeypatch.setitem(sys.modules, "tools.tirith_security", fake_tirith)

    def _make_event(self, command, args=""):
        event = MagicMock()
        event.get_command.return_value = command
        event.get_command_args.return_value = args
        event.text = f"/{command} {args}".strip()
        event.source = MagicMock()
        event.source.user_id = "test_user"
        event.source.user_name = "Test User"
        event.source.platform.value = "telegram"
        event.source.chat_type = "dm"
        event.source.chat_id = "123"
        event.source.thread_id = None
        return event

    @pytest.mark.asyncio
    async def test_exec_command_returns_output(self):
        from gateway.run import GatewayRunner
        runner = GatewayRunner.__new__(GatewayRunner)
        runner.config = {"quick_commands": {"limits": {"type": "exec", "command": "echo ok"}}}
        runner._running_agents = {}
        runner._pending_messages = {}
        runner._is_user_authorized = MagicMock(return_value=True)

        event = self._make_event("limits")
        result = await runner._handle_message(event)
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_exec_command_waits_for_hermes_approval_before_running(self, monkeypatch):
        from gateway.run import GatewayRunner
        from tools.approval import has_blocking_approval, resolve_gateway_approval

        self._stub_tirith(monkeypatch)
        runner = GatewayRunner.__new__(GatewayRunner)
        runner.config = {
            "quick_commands": {
                "py": {"type": "exec", "command": "python3 -c \"print('ok')\""}
            }
        }
        runner.adapters = {}
        runner._running_agents = {}
        runner._pending_messages = {}
        runner._is_user_authorized = MagicMock(return_value=True)

        event = self._make_event("py")
        session_key = runner._session_key_for_source(event.source)

        task = asyncio.create_task(runner._handle_message(event))
        for _ in range(100):
            if has_blocking_approval(session_key):
                break
            await asyncio.sleep(0.01)

        assert has_blocking_approval(session_key) is True
        resolve_gateway_approval(session_key, "once")

        result = await asyncio.wait_for(task, timeout=5)
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_exec_command_does_not_run_when_hermes_approval_times_out(self, monkeypatch):
        from gateway.run import GatewayRunner

        self._stub_tirith(monkeypatch)
        runner = GatewayRunner.__new__(GatewayRunner)
        runner.config = {
            "quick_commands": {
                "danger": {"type": "exec", "command": "rm -rf /tmp/hermes-quick-test"}
            }
        }
        runner.adapters = {}
        runner._running_agents = {}
        runner._pending_messages = {}
        runner._is_user_authorized = MagicMock(return_value=True)

        event = self._make_event("danger")
        with patch("tools.approval._get_approval_config", return_value={"gateway_timeout": 0}), \
             patch("asyncio.create_subprocess_shell", new_callable=AsyncMock) as mock_spawn:
            result = await runner._handle_message(event)

        assert "blocked" in result.lower() or "timed out" in result.lower()
        mock_spawn.assert_not_called()

    @staticmethod
    def _write_fake_sapphire_guard(tmp_path: Path, body: str) -> Path:
        repo = tmp_path / "Sapphire"
        guard_dir = repo / "infra" / "sandbox"
        guard_dir.mkdir(parents=True)
        (guard_dir / "command_guard.py").write_text(body, encoding="utf-8")
        return repo

    @pytest.mark.asyncio
    async def test_sapphire_command_guard_block_prevents_exec(self, monkeypatch, tmp_path):
        from gateway.run import GatewayRunner

        self._stub_tirith(monkeypatch)
        repo = self._write_fake_sapphire_guard(
            tmp_path,
            "class Result:\n"
            "    blocked = True\n"
            "    requires_confirmation = False\n"
            "    action = 'block'\n"
            "    reason = 'blocked by test policy'\n"
            "    matched_rule = 'blocked-rule'\n"
            "class CommandGuard:\n"
            "    def __init__(self, component):\n"
            "        self.component = component\n"
            "    def check(self, command):\n"
            "        return Result()\n",
        )
        monkeypatch.setenv("SAPPHIRE_REPO_PATH", str(repo))

        runner = GatewayRunner.__new__(GatewayRunner)
        runner.config = {"quick_commands": {"sg": {"type": "exec", "command": "echo nope"}}}
        runner.adapters = {}
        runner._running_agents = {}
        runner._pending_messages = {}
        runner._is_user_authorized = MagicMock(return_value=True)

        with patch("asyncio.create_subprocess_shell", new_callable=AsyncMock) as mock_spawn:
            result = await runner._handle_message(self._make_event("sg"))

        assert "blocked by sapphire commandguard" in result.lower()
        mock_spawn.assert_not_called()

    @pytest.mark.asyncio
    async def test_sapphire_command_guard_confirm_uses_gateway_approval(self, monkeypatch, tmp_path):
        from gateway.run import GatewayRunner
        from tools.approval import has_blocking_approval, resolve_gateway_approval

        self._stub_tirith(monkeypatch)
        repo = self._write_fake_sapphire_guard(
            tmp_path,
            "class Result:\n"
            "    blocked = False\n"
            "    requires_confirmation = True\n"
            "    action = 'confirm'\n"
            "    reason = 'needs operator check'\n"
            "    matched_rule = 'confirm-rule'\n"
            "class CommandGuard:\n"
            "    def __init__(self, component):\n"
            "        self.component = component\n"
            "    def check(self, command):\n"
            "        return Result()\n",
        )
        monkeypatch.setenv("SAPPHIRE_REPO_PATH", str(repo))

        runner = GatewayRunner.__new__(GatewayRunner)
        runner.config = {"quick_commands": {"sg": {"type": "exec", "command": "echo ok"}}}
        runner.adapters = {}
        runner._running_agents = {}
        runner._pending_messages = {}
        runner._is_user_authorized = MagicMock(return_value=True)

        event = self._make_event("sg")
        session_key = runner._session_key_for_source(event.source)
        task = asyncio.create_task(runner._handle_message(event))

        for _ in range(500):
            if has_blocking_approval(session_key):
                break
            await asyncio.sleep(0.01)

        assert has_blocking_approval(session_key) is True
        resolve_gateway_approval(session_key, "once")

        result = await asyncio.wait_for(task, timeout=5)
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_sapphire_guard_import_error_blocks_production_adjacent_command(
        self, monkeypatch, tmp_path,
    ):
        from gateway.run import GatewayRunner

        self._stub_tirith(monkeypatch)
        repo = tmp_path / "Sapphire"
        (repo / "infra" / "sandbox").mkdir(parents=True)
        monkeypatch.setenv("SAPPHIRE_REPO_PATH", str(repo))

        runner = GatewayRunner.__new__(GatewayRunner)
        runner.config = {
            "quick_commands": {
                "svc": {
                    "type": "exec",
                    "command": "launchctl bootstrap gui/501 ~/Library/LaunchAgents/ai.hermes.plist",
                }
            }
        }
        runner.adapters = {}
        runner._running_agents = {}
        runner._pending_messages = {}
        runner._is_user_authorized = MagicMock(return_value=True)

        with patch("asyncio.create_subprocess_shell", new_callable=AsyncMock) as mock_spawn:
            result = await runner._handle_message(self._make_event("svc"))

        assert "sapphire commandguard is unavailable" in result.lower()
        mock_spawn.assert_not_called()

    @pytest.mark.asyncio
    async def test_unsupported_type_returns_error(self):
        from gateway.run import GatewayRunner
        runner = GatewayRunner.__new__(GatewayRunner)
        runner.config = {"quick_commands": {"bad": {"type": "prompt", "command": "echo hi"}}}
        runner._running_agents = {}
        runner._pending_messages = {}
        runner._is_user_authorized = MagicMock(return_value=True)

        event = self._make_event("bad")
        result = await runner._handle_message(event)
        assert result is not None
        assert "unsupported type" in result.lower()

    @pytest.mark.asyncio
    async def test_timeout_returns_error(self):
        from gateway.run import GatewayRunner
        import asyncio
        runner = GatewayRunner.__new__(GatewayRunner)
        runner.config = {"quick_commands": {"slow": {"type": "exec", "command": "sleep 100"}}}
        runner._running_agents = {}
        runner._pending_messages = {}
        runner._is_user_authorized = MagicMock(return_value=True)

        event = self._make_event("slow")
        with patch("asyncio.wait_for", side_effect=asyncio.TimeoutError):
            result = await runner._handle_message(event)
        assert result is not None
        assert "timed out" in result.lower()

    @pytest.mark.asyncio
    async def test_gateway_config_object_supports_quick_commands(self):
        from gateway.config import GatewayConfig
        from gateway.run import GatewayRunner

        runner = GatewayRunner.__new__(GatewayRunner)
        runner.config = GatewayConfig(
            quick_commands={"limits": {"type": "exec", "command": "echo ok"}}
        )
        runner._running_agents = {}
        runner._pending_messages = {}
        runner._is_user_authorized = MagicMock(return_value=True)

        event = self._make_event("limits")
        result = await runner._handle_message(event)
        assert result == "ok"
