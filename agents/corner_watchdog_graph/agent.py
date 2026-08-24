"""The graph, exposed where `adk web`, `adk run` and `adk eval` look for it.

    adk web agents
    adk eval agents/corner_watchdog_graph evals/decisions.evalset.json

The ADK's tooling loads `root_agent` from a package under an agents directory,
so this file exists to be that package and to do nothing else. The graph itself
is built in `corner_watchdog.adk_graph`, which is where it belongs: a console
that runs a different agent than production is a demo of itself.

The directory is `corner_watchdog_graph` and not `corner_watchdog` on purpose.
`adk web` puts this directory's parent on `sys.path`, so a package here sharing
a name with the project's own package would shadow it and every import in this
file would resolve to this file's own directory. That is the same collision the
project already hit with the PyPI `watchdog` distribution, arriving from the
opposite direction. See tests/test_package_name.py.

The model comes from `DELIBERATION_MODEL`, so pointing this at a Vertex project
is environment rather than code. With no project configured the console still
loads and tier one still runs, which is worth having, because tier one settles
most corners and settling them is the thing this project is about.
"""

from __future__ import annotations

from corner_watchdog.adk_decider import build_decider_agent
from corner_watchdog.adk_graph import build_graph
from corner_watchdog.config import deliberation_model

root_agent = build_graph(build_decider_agent(model=deliberation_model()))
