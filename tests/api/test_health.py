"""API smoke test — health endpoint works with no DB, and no write routes exist."""

from __future__ import annotations

from fastapi.testclient import TestClient

from rcm.api.app import app


def test_health_ok() -> None:
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_no_write_routes_exist() -> None:
    """Phase 0 is read-only: every route is a GET. This is a security invariant."""
    for route in app.routes:
        methods = getattr(route, "methods", set()) or set()
        mutating = methods & {"POST", "PUT", "PATCH", "DELETE"}
        assert not mutating, f"unexpected write route: {getattr(route, 'path', route)} {mutating}"
