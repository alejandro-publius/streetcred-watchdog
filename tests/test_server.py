"""The HTTP surface, and the two ways a push endpoint quietly costs money.

Everything here runs offline. No Firestore client is constructed, no topic is
touched, and the two routes that would reach the cloud are exercised only where
they fail before getting there, which is the half worth testing anyway.

The two behaviours that are easy to get wrong and expensive to get wrong:

  A misspelled SERVICE must not boot as the observer. An instance that quietly
  picks a default answers /healthz cheerfully, passes every uptime check, and
  never deliberates on anything.

  An undecodable push must be acknowledged, not retried. Pub/Sub redelivers
  anything that is not a 2xx until the subscription's retention expires, so a
  payload this build cannot parse becomes an infinite loop that bills a model on
  every attempt.
"""

from __future__ import annotations

import base64
import json

import pytest

# server.py is the deployed half, so it needs the `cloud` extra. A clean
# `pip install -e ".[dev]"` has neither, and skipping is the honest answer there:
# these tests are about code that only ever runs on Cloud Run.
pytest.importorskip("fastapi", reason="the cloud extra is not installed")
pytest.importorskip("google.cloud.firestore", reason="the cloud extra is not installed")

from fastapi.testclient import TestClient

from corner_watchdog.server import (
    ACTOR,
    OBSERVER,
    app,
    decode_push,
    service_role,
)


def client(monkeypatch, role: str) -> TestClient:
    monkeypatch.setenv("SERVICE", role)
    return TestClient(app)


# ================================================================ which service

def test_the_status_route_is_not_named_healthz():
    """Cloud Run's front end reserves /healthz and answers it with its own 404.

    The container never sees the request, so the route looks broken while the
    service is fine. Pinned here because the next person to tidy route names
    would reach for /healthz first.
    """
    paths = {r.path for r in app.routes}
    assert "/status" in paths
    assert "/healthz" not in paths


def test_the_observer_says_it_is_the_observer(monkeypatch):
    body = client(monkeypatch, OBSERVER).get("/status").json()
    assert body["ok"] is True
    assert body["service"] == OBSERVER


def test_the_actor_says_it_is_the_actor(monkeypatch):
    body = client(monkeypatch, ACTOR).get("/status").json()
    assert body["service"] == ACTOR


def test_health_reports_the_wiring_rather_than_only_that_it_is_alive(monkeypatch):
    """A check that proves the process is up says nothing about what it will do."""
    body = client(monkeypatch, OBSERVER).get("/status").json()
    assert "decider=" in body["config"]
    assert "actionBudget" in body and "tokenBudget" in body


@pytest.mark.parametrize("value", ["observerr", "OBSERVE", "both", "actor2", "x"])
def test_a_misspelled_service_raises_rather_than_defaulting(monkeypatch, value):
    monkeypatch.setenv("SERVICE", value)
    with pytest.raises(RuntimeError, match="Refusing to guess"):
        service_role()


def test_an_unset_service_is_the_observer(monkeypatch):
    """Matches the Dockerfile's ENV SERVICE=observer, so the default is stated twice."""
    monkeypatch.delenv("SERVICE", raising=False)
    assert service_role() == OBSERVER


@pytest.mark.parametrize("value", [" observer ", "Observer", "ACTOR"])
def test_case_and_whitespace_are_tolerated(monkeypatch, value):
    monkeypatch.setenv("SERVICE", value)
    assert service_role() in (OBSERVER, ACTOR)


# ================================================================ role guards

def test_the_actor_refuses_to_sweep(monkeypatch):
    body = client(monkeypatch, ACTOR).post("/sweep").json()
    assert "does not sweep" in body["error"]


def test_the_observer_refuses_to_deliberate(monkeypatch):
    r = client(monkeypatch, OBSERVER).post("/deliberate", json={})
    assert r.status_code == 400


# ============================================================ the push envelope

def envelope() -> dict:
    return {
        "corner": {"slug": "6th-and-mission", "name": "6th and Mission"},
        "delta": {"slug": "6th-and-mission", "name": "6th and Mission", "empty": True},
    }


def wrap(payload: dict) -> dict:
    data = base64.b64encode(json.dumps(payload).encode()).decode()
    return {"message": {"data": data, "messageId": "1"}, "subscription": "s"}


def test_a_well_formed_push_decodes_to_the_envelope_that_was_published():
    assert decode_push(wrap(envelope())) == envelope()


@pytest.mark.parametrize(
    "body, expected",
    [
        ({}, "no 'message' object"),
        ({"message": "not an object"}, "no 'message' object"),
        ({"message": {}}, "no base64 'data'"),
        ({"message": {"data": 42}}, "no base64 'data'"),
        ({"message": {"data": "!!!not base64!!!"}}, "not valid base64"),
    ],
)
def test_every_malformed_push_shape_is_named_rather_than_guessed_at(body, expected):
    with pytest.raises(ValueError, match=expected):
        decode_push(body)


def test_a_json_array_is_refused_because_an_envelope_is_an_object():
    data = base64.b64encode(json.dumps([1, 2, 3]).encode()).decode()
    with pytest.raises(ValueError, match="must be a JSON object"):
        decode_push({"message": {"data": data}})


def test_the_outbox_is_somewhere_writable_on_an_ephemeral_filesystem():
    """Cloud Run's disk is in-memory. A relative path would fail on first write."""
    from corner_watchdog.server import OUTBOX_DIR

    assert OUTBOX_DIR.startswith("/"), "a relative outbox path fails on first write"
