from __future__ import annotations

from pathlib import Path

from app import create_app


def test_create_app_does_not_touch_live_instance_db() -> None:
    live = Path(__file__).resolve().parent.parent / "instance" / "email_tools.db"
    before_mtime = live.stat().st_mtime if live.is_file() else None
    before_size = live.stat().st_size if live.is_file() else None

    app = create_app()
    store_path = Path(app.config["DATABASE"]).resolve()
    live_resolved = live.resolve() if live.exists() else live

    assert store_path != live_resolved
    assert "email_tools.db" in store_path.name

    if live.is_file() and before_mtime is not None:
        assert live.stat().st_mtime == before_mtime
        assert live.stat().st_size == before_size
