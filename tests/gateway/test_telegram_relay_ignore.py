"""Tests for Telegram relay-only user suppression."""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from gateway.config import GatewayConfig, Platform, PlatformConfig
from gateway.platforms.base import MessageEvent
from gateway.session import SessionEntry, SessionSource, build_session_key


def _make_source(*, user_id: str = "relay-user") -> SessionSource:
    return SessionSource(
        platform=Platform.TELEGRAM,
        user_id=user_id,
        chat_id="chat-1",
        user_name="Relay",
        chat_type="dm",
    )


def _make_event(text: str, *, user_id: str = "relay-user") -> MessageEvent:
    return MessageEvent(
        text=text,
        source=_make_source(user_id=user_id),
        message_id="msg-1",
    )


def _make_runner(session_entry: SessionEntry):
    from gateway.run import GatewayRunner

    runner = object.__new__(GatewayRunner)
    runner.config = GatewayConfig(
        platforms={Platform.TELEGRAM: PlatformConfig(enabled=True, token="***")}
    )
    adapter = MagicMock()
    adapter.send = AsyncMock()
    runner.adapters = {Platform.TELEGRAM: adapter}
    runner.hooks = SimpleNamespace(emit=AsyncMock(), loaded_hooks=False)
    runner.session_store = MagicMock()
    runner.session_store.get_or_create_session.return_value = session_entry
    runner.session_store.load_transcript.return_value = [
        {"role": "user", "content": "previous"}
    ]
    runner.session_store.has_any_sessions.return_value = True
    runner._set_session_env = lambda _context: []
    runner._clear_session_env = lambda _tokens: None
    runner._prepare_inbound_message_text = AsyncMock()
    runner._bind_adapter_run_generation = lambda *_args, **_kwargs: None
    runner._run_agent = AsyncMock(
        return_value={"final_response": "agent response", "messages": [], "api_calls": 1}
    )
    return runner


@pytest.mark.asyncio
async def test_ignored_relay_user_emits_hook_but_does_not_run_agent(monkeypatch):
    source = _make_source(user_id="relay-user")
    session_entry = SessionEntry(
        session_key=build_session_key(source),
        session_id="sess-1",
        created_at=datetime.now() - timedelta(seconds=1),
        updated_at=datetime.now(),
        platform=Platform.TELEGRAM,
        chat_type="dm",
    )
    runner = _make_runner(session_entry)
    long_message = "x" * 17000
    runner._prepare_inbound_message_text.return_value = long_message
    monkeypatch.setenv("TELEGRAM_IGNORED_USER_IDS", "relay-user, other")

    result = await runner._handle_message_with_agent(
        _make_event(long_message),
        source,
        session_entry.session_key,
        1,
    )

    assert result is None
    runner._run_agent.assert_not_called()
    agent_start_calls = [
        call
        for call in runner.hooks.emit.await_args_list
        if call.args and call.args[0] == "agent:start"
    ]
    assert agent_start_calls
    hook_ctx = agent_start_calls[-1].args[1]
    assert hook_ctx["user_id"] == "relay-user"
    assert len(hook_ctx["message"]) == 16000


@pytest.mark.asyncio
async def test_non_ignored_relay_user_runs_agent(monkeypatch):
    source = _make_source(user_id="normal-user")
    session_entry = SessionEntry(
        session_key=build_session_key(source),
        session_id="sess-2",
        created_at=datetime.now() - timedelta(seconds=1),
        updated_at=datetime.now(),
        platform=Platform.TELEGRAM,
        chat_type="dm",
    )
    runner = _make_runner(session_entry)
    runner._prepare_inbound_message_text.return_value = "hello"
    monkeypatch.setenv("TELEGRAM_IGNORED_USER_IDS", "relay-user")
    monkeypatch.setattr(runner, "_is_session_run_current", lambda *_args: False)

    result = await runner._handle_message_with_agent(
        _make_event("hello", user_id="normal-user"),
        source,
        session_entry.session_key,
        1,
    )

    assert result is None
    runner._run_agent.assert_awaited_once()
