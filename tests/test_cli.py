"""Tests for command-line server configuration."""

from __future__ import annotations

from frosthaven_arbiter import cli


def test_serve_enables_uvicorn_reload(monkeypatch, settings) -> None:
    calls: list[tuple[object, dict[str, object]]] = []
    monkeypatch.setattr(cli, "load_settings", lambda: settings)
    monkeypatch.setattr(cli.uvicorn, "run", lambda app, **kwargs: calls.append((app, kwargs)))

    cli._serve_command()

    assert calls == [
        (
            "frosthaven_arbiter.cli:create_production_app",
            {
                "host": settings.web.host,
                "port": settings.web.port,
                "reload": True,
                "factory": True,
            },
        )
    ]
