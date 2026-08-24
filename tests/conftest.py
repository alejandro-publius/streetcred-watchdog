"""The test suite is offline by construction, not by coincidence.

`DECIDER` now defaults to the ADK judgment agent, which means the default wiring
calls a real model on a real Vertex project. That is correct for the agent and
unacceptable for the tests: a suite whose behaviour depends on whether the
machine running it happens to have `GOOGLE_CLOUD_PROJECT` exported is a suite
that passes on a laptop, spends money in CI, and tells you nothing either way.

Relying on the credentials simply being absent is not good enough. It is true on
this machine today and it is one `export` away from being false, and the failure
that export causes is a paid, non-deterministic test run rather than an error.

So the environment is scrubbed for every test. A test that wants the ADK path
builds it explicitly with a scripted model, which is how every ADK test in this
suite is written. Nothing here can reach Vertex by default, and
`test_the_suite_cannot_reach_vertex_by_accident` fails if that stops being true.
"""

from __future__ import annotations

import pytest

# Everything that could turn a local test run into a billed one.
VERTEX_ENV = (
    "GOOGLE_CLOUD_PROJECT",
    "GOOGLE_CLOUD_LOCATION",
    "GOOGLE_APPLICATION_CREDENTIALS",
    "GOOGLE_GENAI_USE_VERTEXAI",
    "GOOGLE_API_KEY",
    "GEMINI_API_KEY",
)


@pytest.fixture(autouse=True)
def offline_by_default(monkeypatch):
    """No test reaches a paid model unless it builds one on purpose."""
    for name in VERTEX_ENV:
        monkeypatch.delenv(name, raising=False)
    # The stand-in, so a cycle under test never constructs a live ADK decider.
    # Tests that exercise the ADK path pass their own decider or agent.
    monkeypatch.setenv("DECIDER", "rule")
