"""Tests for Sapphire confirmation reply interception in the gateway."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest


def _write_fake_sapphire(tmp_path: Path, body: str) -> Path:
    repo = tmp_path / "Sapphire"
    module_dir = repo / "lib" / "core"
    module_dir.mkdir(parents=True)
    (repo / "lib" / "__init__.py").write_text("")
    (module_dir / "__init__.py").write_text("")
    (module_dir / "confirmation_firewall.py").write_text(body)
    return repo


def _drop_fake_module() -> None:
    for name in (
        "lib.core.confirmation_firewall",
        "lib.core",
        "lib",
    ):
        sys.modules.pop(name, None)


@pytest.fixture(autouse=True)
def _clean_imports(monkeypatch):
    _drop_fake_module()
    monkeypatch.delenv("SAPPHIRE_REPO_PATH", raising=False)
    yield
    _drop_fake_module()


def test_non_confirmation_text_falls_through() -> None:
    from gateway.run import _handle_sapphire_confirmation_reply_text

    assert _handle_sapphire_confirmation_reply_text("please explain approve ABC12345") is None


def test_missing_sapphire_repo_returns_unavailable(monkeypatch, tmp_path) -> None:
    from gateway.run import _handle_sapphire_confirmation_reply_text

    monkeypatch.setenv("SAPPHIRE_REPO_PATH", str(tmp_path / "missing"))

    assert (
        _handle_sapphire_confirmation_reply_text("approve ABC12345")
        == "Sapphire confirmation handler is unavailable."
    )


def test_approve_reply_uses_sapphire_handler(monkeypatch, tmp_path) -> None:
    from gateway.run import _handle_sapphire_confirmation_reply_text

    repo = _write_fake_sapphire(
        tmp_path,
        "def handle_confirmation_reply(raw):\n"
        "    return {'ok': True, 'code': 'abc12345', 'action': 'approve'}\n",
    )
    monkeypatch.setenv("SAPPHIRE_REPO_PATH", str(repo))

    assert (
        _handle_sapphire_confirmation_reply_text("approve ABC12345")
        == "Approved Sapphire confirmation ABC12345."
    )


def test_deny_reply_uses_sapphire_handler(monkeypatch, tmp_path) -> None:
    from gateway.run import _handle_sapphire_confirmation_reply_text

    repo = _write_fake_sapphire(
        tmp_path,
        "def handle_confirmation_reply(raw):\n"
        "    return {'ok': True, 'code': 'def67890', 'action': 'deny'}\n",
    )
    monkeypatch.setenv("SAPPHIRE_REPO_PATH", str(repo))

    assert (
        _handle_sapphire_confirmation_reply_text("/deny DEF67890")
        == "Denied Sapphire confirmation DEF67890."
    )


def test_not_found_reply_reports_no_active_confirmation(monkeypatch, tmp_path) -> None:
    from gateway.run import _handle_sapphire_confirmation_reply_text

    repo = _write_fake_sapphire(
        tmp_path,
        "def handle_confirmation_reply(raw):\n"
        "    return {'ok': False, 'code': 'abc12345'}\n",
    )
    monkeypatch.setenv("SAPPHIRE_REPO_PATH", str(repo))

    assert (
        _handle_sapphire_confirmation_reply_text("confirm ABC12345")
        == "No active Sapphire confirmation found for ABC12345."
    )


def test_handler_none_falls_through(monkeypatch, tmp_path) -> None:
    from gateway.run import _handle_sapphire_confirmation_reply_text

    repo = _write_fake_sapphire(
        tmp_path,
        "def handle_confirmation_reply(raw):\n"
        "    return None\n",
    )
    monkeypatch.setenv("SAPPHIRE_REPO_PATH", str(repo))

    assert _handle_sapphire_confirmation_reply_text("cancel ABC12345") is None


def test_handler_exception_returns_failure(monkeypatch, tmp_path) -> None:
    from gateway.run import _handle_sapphire_confirmation_reply_text

    repo = _write_fake_sapphire(
        tmp_path,
        "def handle_confirmation_reply(raw):\n"
        "    raise RuntimeError('boom')\n",
    )
    monkeypatch.setenv("SAPPHIRE_REPO_PATH", str(repo))

    assert (
        _handle_sapphire_confirmation_reply_text("reject ABC12345")
        == "Sapphire confirmation handler failed; check gateway logs."
    )
