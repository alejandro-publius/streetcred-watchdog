"""The decision journal, rendered as a page you can hand to a sceptic.

Two rules govern everything here and they are worth stating before the markup:

  The restraint rate is computed, not asserted. It is the share of evaluations
  that ended in no action, over every evaluation in the journal, and the page
  prints that definition beside the number so nobody has to take the arithmetic
  on faith. Nothing is filtered out to improve it.

  A decline is rendered at full size. Same padding, same type, same prominence
  as an action, never collapsed behind a disclosure triangle and never greyed
  down. The moment a decline is cheaper to render than an action, the page has
  quietly become the highlight reel this project exists to avoid.

Rehearsal entries, whose baselines were constructed rather than observed, are
rendered in their own section, labelled, and left out of every headline figure.
"""

from __future__ import annotations

import datetime as _dt
import html
from pathlib import Path
from typing import Any

from .schema import UNJUDGED_BASES
from .store import LocalJsonStore

TITLE = "The Restraint Ledger"

ACTION_WORDS = {
    "rescore": "rescored the corner",
    "regenerate_letter": "redrafted the letter",
    "reaudit_imagery": "re-audited the imagery",
    "flag": "flagged it for a human",
}


def _e(s: Any) -> str:
    return html.escape(str(s if s is not None else ""))


def _decided_by(entry: dict[str, Any]) -> str:
    if entry.get("tier2"):
        return "Deliberation"
    if (entry.get("tier1") or {}).get("byRule"):
        return "Rule floor"
    return "Triage"


# How each basis reads on the page. The wording matters: these are the labels
# that stop "declined" from covering two different events.
BASIS_LABEL = {
    "first_sighting": "no baseline yet",
    "no_change": "nothing changed",
    "unreliable": "comparison refused",
    "fetch_failed": "could not read the record",
    "methodology": "the query itself changed",
    "rule_fatal": "rule floor, new fatality",
    "rule_severe": "rule floor, new severe injury",
    "triage": "triage weighed it",
    # Entries written before the basis field existed. Counted as unjudged, never
    # as judged: a missing field must not be able to inflate the one claim this
    # breakdown exists to deflate.
    "unrecorded": "basis not recorded, older entry",
}


def summarise(entries: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(entries)
    held = [e for e in entries if not e.get("actions")]
    acted = total - len(held)
    escalated = sum(1 for e in entries if e.get("tier2"))
    by_rule = sum(1 for e in entries if (e.get("tier1") or {}).get("byRule"))
    intents = sum(len(e.get("intents") or []) for e in entries)
    actions = sum(len(e.get("actions") or []) for e in entries)
    corners = {e.get("slug") for e in entries if e.get("slug")}

    # The distinction the whole page turns on. A decline settled by a rule
    # observing that there was nothing to compare is not the same event as a
    # tier weighing a real change and choosing not to act, and a restraint rate
    # that adds them together describes a quiet city while reading as a careful
    # agent.
    bases: dict[str, int] = {}
    for e in held:
        b = (e.get("tier1") or {}).get("basis") or "unrecorded"
        bases[b] = bases.get(b, 0) + 1
    unjudged = sum(n for b, n in bases.items() if b in UNJUDGED_BASES)
    judged_declines = len(held) - unjudged
    deliberated_declines = sum(1 for e in held if e.get("tier2"))
    triage_declines = judged_declines - deliberated_declines

    return {
        "total": total,
        "held": len(held),
        "acted": acted,
        "escalated": escalated,
        "by_rule": by_rule,
        "intents": intents,
        "actions": actions,
        "corners": len(corners),
        "restraint": (len(held) / total * 100) if total else 0.0,
        "bases": bases,
        "unjudged_declines": unjudged,
        "judged_declines": judged_declines,
        "triage_declines": triage_declines,
        "deliberated_declines": deliberated_declines,
    }


def _breakdown_html(s: dict[str, Any]) -> str:
    """What the restraint rate is actually made of.

    Printed directly under the headline rather than further down the page,
    because a reader who stops after the big number should already have been
    told what it does and does not measure.
    """
    if not s["held"]:
        return ""

    rows = []
    for basis, count in sorted(s["bases"].items(), key=lambda kv: -kv[1]):
        judged = basis not in UNJUDGED_BASES
        label = BASIS_LABEL.get(basis, basis)
        rows.append(
            f'<li class="split-row"><span class="split-n">{count}</span>'
            f'<span class="split-label">{_e(label)}</span>'
            f'<span class="split-tag split-{"judged" if judged else "observed"}">'
            f'{"weighed" if judged else "observed"}</span></li>'
        )

    judged = s["judged_declines"]
    if judged == 0:
        verdict = (
            f"<strong>None of these {s['held']} declines involved a judgment call.</strong> Every one "
            "was settled by a rule observing that there was nothing to compare or nothing had moved. "
            "Neither tier was consulted. On this journal the restraint rate is a measurement of a "
            "quiet city, not of an agent exercising restraint, and it would look exactly the same if "
            "both tiers were broken."
        )
    else:
        parts = []
        if s["triage_declines"]:
            parts.append(f"{s['triage_declines']} at triage")
        if s["deliberated_declines"]:
            parts.append(f"{s['deliberated_declines']} after deliberation")
        verdict = (
            f"<strong>{judged} of these {s['held']} declines involved a judgment call</strong> "
            f"({', '.join(parts)}). The other {s['unjudged_declines']} were settled by a rule before "
            "either tier was consulted. Only the first group is evidence that anything is exercising "
            "restraint; the second is evidence that the city was quiet."
        )

    return f"""<div class="breakdown">
  <p class="eyebrow">What the number is made of</p>
  <ul class="split">{"".join(rows)}</ul>
  <p class="split-verdict">{verdict}</p>
</div>"""


def _entry_html(entry: dict[str, Any]) -> str:
    t1 = entry.get("tier1") or {}
    t2 = entry.get("tier2") or {}
    actions = entry.get("actions") or []
    intents = entry.get("intents") or []
    held = not actions
    decided = _decided_by(entry)

    if held:
        badge = "Held"
        tone = "held"
    else:
        badge = "Acted"
        tone = "acted"

    reasons = []
    if t1.get("reason"):
        label = "Rule floor" if t1.get("byRule") else "Triage"
        reasons.append((label, t1["reason"]))
    if t2.get("reasoning"):
        reasons.append(("Deliberation", t2["reasoning"]))

    reason_html = "".join(
        f'<div class="reason"><span class="who">{_e(who)}</span>'
        f'<p class="says">{_e(text)}</p></div>'
        for who, text in reasons
    )

    if actions:
        taken = ", ".join(ACTION_WORDS.get(a, a) for a in actions)
        outcome = f'<p class="outcome outcome-acted">Acted: {_e(taken)}.</p>'
    else:
        outcome = '<p class="outcome outcome-held">No action taken.</p>'

    intents_html = ""
    if intents:
        items = "".join(f"<li>{_e(i)}</li>" for i in intents)
        intents_html = (
            '<div class="intents"><span class="who">Budget refused</span>'
            f"<ul>{items}</ul></div>"
        )

    degraded = entry.get("degraded")
    degraded_html = f'<p class="caveat">{_e(degraded)}</p>' if degraded else ""

    conf = t1.get("confidence")
    conf_html = f'<span class="meta-bit">confidence {_e(conf)}</span>' if conf is not None else ""

    basis = t1.get("basis")
    basis_html = (
        f'<span class="meta-bit">{_e(BASIS_LABEL.get(basis, basis))}</span>' if basis else ""
    )

    return f"""<article class="entry entry-{tone}">
  <header class="entry-head">
    <h3>{_e(entry.get("name") or entry.get("slug") or "an unnamed corner")}</h3>
    <span class="badge badge-{tone}">{badge}</span>
  </header>
  <p class="delta">{_e(entry.get("delta"))}</p>
  {reason_html}
  {outcome}
  {intents_html}
  {degraded_html}
  <footer class="entry-foot">
    <span class="meta-bit">{_e(entry.get("ts"))}</span>
    <span class="meta-bit">{_e(entry.get("slug"))}</span>
    <span class="meta-bit">decided by {_e(decided.lower())}</span>
    {basis_html}
    <span class="meta-bit">trigger {_e(entry.get("trigger"))}</span>
    {conf_html}
  </footer>
</article>"""


STYLE = """
:root {
  --ground: #f4f6f4;
  --surface: #ffffff;
  --ink: #161d1f;
  --muted: #5c6a6e;
  --hairline: #d5dbd7;
  --held: #2f5d50;
  --held-wash: #e7efea;
  --acted: #a1571c;
  --acted-wash: #f7ecdf;
  --rule: #8c2f2f;
  --shadow: 0 1px 0 rgba(22, 29, 31, 0.05);
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --ground: #0f1413;
    --surface: #161c1b;
    --ink: #e7ece9;
    --muted: #93a29e;
    --hairline: #2a3331;
    --held: #74c1a5;
    --held-wash: #17251f;
    --acted: #e0a468;
    --acted-wash: #241a11;
    --rule: #e08a8a;
    --shadow: none;
  }
}
:root[data-theme="dark"] {
  --ground: #0f1413;
  --surface: #161c1b;
  --ink: #e7ece9;
  --muted: #93a29e;
  --hairline: #2a3331;
  --held: #74c1a5;
  --held-wash: #17251f;
  --acted: #e0a468;
  --acted-wash: #241a11;
  --rule: #e08a8a;
  --shadow: none;
}

* { box-sizing: border-box; }

body {
  margin: 0;
  background: var(--ground);
  color: var(--ink);
  font-family: "Public Sans", ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
  font-size: 16px;
  line-height: 1.6;
  -webkit-font-smoothing: antialiased;
}

.wrap {
  max-width: 46rem;
  margin: 0 auto;
  padding: clamp(1.5rem, 4vw, 3.5rem) 1.25rem 5rem;
  display: flex;
  flex-direction: column;
  gap: 2.5rem;
}

.eyebrow {
  font-family: "IBM Plex Mono", ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 0.7rem;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--muted);
  margin: 0;
}

.masthead { display: flex; flex-direction: column; gap: 1.25rem; }

.masthead h1 {
  font-family: "IBM Plex Serif", Georgia, "Times New Roman", serif;
  font-weight: 600;
  font-size: clamp(1.75rem, 4.5vw, 2.4rem);
  line-height: 1.15;
  letter-spacing: -0.01em;
  text-wrap: balance;
  margin: 0;
}

.masthead .standfirst {
  margin: 0;
  color: var(--muted);
  max-width: 34rem;
}

.headline {
  background: var(--surface);
  border: 1px solid var(--hairline);
  box-shadow: var(--shadow);
  padding: clamp(1.25rem, 3vw, 2rem);
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.rate {
  display: flex;
  align-items: baseline;
  gap: 0.6rem;
  flex-wrap: wrap;
}

.rate .figure {
  font-family: "IBM Plex Serif", Georgia, serif;
  font-variant-numeric: tabular-nums;
  font-weight: 600;
  font-size: clamp(3.25rem, 13vw, 5.5rem);
  line-height: 0.95;
  letter-spacing: -0.03em;
  color: var(--held);
}

.rate .unit {
  font-family: "IBM Plex Serif", Georgia, serif;
  font-size: 1.6rem;
  color: var(--held);
}

.rate .what {
  font-family: "IBM Plex Mono", ui-monospace, monospace;
  font-size: 0.72rem;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--muted);
  margin-left: auto;
  text-align: right;
}

.bar {
  display: flex;
  height: 0.5rem;
  overflow: hidden;
  background: var(--hairline);
}
.bar span { display: block; height: 100%; }
.bar .seg-held { background: var(--held); }
.bar .seg-acted { background: var(--acted); }

.definition {
  margin: 0;
  font-size: 0.9rem;
  color: var(--muted);
}

.breakdown {
  border-top: 1px solid var(--hairline);
  padding-top: 1rem;
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}
.split { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; }
.split-row {
  display: flex;
  align-items: baseline;
  gap: 0.75rem;
  padding: 0.4rem 0;
  border-bottom: 1px solid var(--hairline);
}
.split-row:last-child { border-bottom: none; }
.split-n {
  font-family: "IBM Plex Mono", ui-monospace, monospace;
  font-variant-numeric: tabular-nums;
  font-size: 1rem;
  min-width: 2.25rem;
  text-align: right;
}
.split-label { flex: 1; }
.split-tag {
  font-family: "IBM Plex Mono", ui-monospace, monospace;
  font-size: 0.62rem;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  padding: 0.15rem 0.45rem;
  white-space: nowrap;
}
.split-judged { background: var(--held-wash); color: var(--held); }
.split-observed { background: var(--hairline); color: var(--muted); }
.split-verdict { margin: 0; font-size: 0.92rem; }
.split-verdict strong { font-weight: 600; }

.counts {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(9rem, 1fr));
  gap: 1px;
  background: var(--hairline);
  border: 1px solid var(--hairline);
}
.count {
  background: var(--surface);
  padding: 0.9rem 1rem;
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
}
.count .n {
  font-family: "IBM Plex Mono", ui-monospace, monospace;
  font-variant-numeric: tabular-nums;
  font-size: 1.5rem;
  line-height: 1.1;
}
.count .k {
  font-family: "IBM Plex Mono", ui-monospace, monospace;
  font-size: 0.66rem;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--muted);
}

.notice {
  border-left: 3px solid var(--rule);
  background: var(--surface);
  border-top: 1px solid var(--hairline);
  border-right: 1px solid var(--hairline);
  border-bottom: 1px solid var(--hairline);
  padding: 1rem 1.25rem;
  font-size: 0.92rem;
}
.notice p { margin: 0 0 0.5rem; }
.notice p:last-child { margin-bottom: 0; }
.notice strong { font-weight: 600; }

.section-head {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
  border-bottom: 1px solid var(--hairline);
  padding-bottom: 0.75rem;
}
.section-head h2 {
  font-family: "IBM Plex Serif", Georgia, serif;
  font-weight: 600;
  font-size: 1.3rem;
  margin: 0;
}
.section-head p { margin: 0; color: var(--muted); font-size: 0.92rem; }

.entries { display: flex; flex-direction: column; gap: 1rem; }

.entry {
  background: var(--surface);
  border: 1px solid var(--hairline);
  border-left: 3px solid var(--held);
  box-shadow: var(--shadow);
  padding: 1.15rem 1.25rem;
  display: flex;
  flex-direction: column;
  gap: 0.7rem;
}
.entry-acted { border-left-color: var(--acted); }

.entry-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 1rem;
}
.entry-head h3 {
  font-family: "IBM Plex Serif", Georgia, serif;
  font-size: 1.05rem;
  font-weight: 600;
  margin: 0;
}

.badge {
  font-family: "IBM Plex Mono", ui-monospace, monospace;
  font-size: 0.64rem;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  padding: 0.2rem 0.5rem;
  white-space: nowrap;
}
.badge-held { background: var(--held-wash); color: var(--held); }
.badge-acted { background: var(--acted-wash); color: var(--acted); }

.delta { margin: 0; font-weight: 500; }

.reason { display: flex; flex-direction: column; gap: 0.2rem; }
.who {
  font-family: "IBM Plex Mono", ui-monospace, monospace;
  font-size: 0.64rem;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--muted);
}
.says { margin: 0; color: var(--ink); }

.outcome { margin: 0; font-weight: 500; }
.outcome-held { color: var(--held); }
.outcome-acted { color: var(--acted); }

.intents { display: flex; flex-direction: column; gap: 0.2rem; }
.intents ul { margin: 0; padding-left: 1.1rem; }

.caveat {
  margin: 0;
  font-size: 0.85rem;
  color: var(--muted);
  border-top: 1px dashed var(--hairline);
  padding-top: 0.6rem;
}

.entry-foot {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem 1rem;
  border-top: 1px solid var(--hairline);
  padding-top: 0.6rem;
}
.meta-bit {
  font-family: "IBM Plex Mono", ui-monospace, monospace;
  font-size: 0.68rem;
  color: var(--muted);
  font-variant-numeric: tabular-nums;
}

.colophon {
  font-size: 0.85rem;
  color: var(--muted);
  border-top: 1px solid var(--hairline);
  padding-top: 1rem;
}
.colophon p { margin: 0 0 0.5rem; }
.colophon p:last-child { margin-bottom: 0; }
.colophon code {
  font-family: "IBM Plex Mono", ui-monospace, monospace;
  font-size: 0.85em;
}
"""


HEAD = f"""<title>{TITLE}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Serif:wght@400;600&family=Public+Sans:wght@400;500;600&display=swap">
<style>{STYLE}</style>"""


def render_body(
    entries: list[dict[str, Any]],
    *,
    rehearsal: list[dict[str, Any]] | None = None,
    generated_at: str | None = None,
) -> str:
    rehearsal = rehearsal or []
    s = summarise(entries)
    generated_at = generated_at or _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")

    held_pct = s["restraint"]
    acted_pct = 100 - held_pct if s["total"] else 0
    breakdown = _breakdown_html(s)

    degradations = sorted({e["degraded"] for e in entries if e.get("degraded")})
    notice = ""
    if degradations:
        lines = "".join(f"<p>{_e(d)}</p>" for d in degradations)
        notice = f"""<section class="notice">
  <p><strong>What was standing in for what, on this run.</strong></p>
  {lines}
  <p>Recorded here because an agent that degrades quietly produces output
  indistinguishable from one that did not.</p>
</section>"""

    entry_html = "".join(_entry_html(e) for e in reversed(entries))
    if not entries:
        entry_html = (
            '<article class="entry"><p class="delta">The journal is empty. '
            "Nothing has been evaluated yet.</p></article>"
        )

    rehearsal_section = ""
    if rehearsal:
        r = summarise(rehearsal)
        rehearsal_entries = "".join(_entry_html(e) for e in reversed(rehearsal))
        rehearsal_section = f"""<section class="rehearsal">
  <div class="section-head">
    <p class="eyebrow">Not observations</p>
    <h2>Rehearsal, kept apart</h2>
    <p>{r["total"]} evaluations run against constructed baselines so the deliberation tier,
    the budget and the letter renderer are exercised rather than assumed. The current readings
    are real snapshots; the previous readings were made up on purpose. None of this counts
    toward the restraint rate above and none of it is evidence that anything happened at these
    corners.</p>
  </div>
  <div class="entries">{rehearsal_entries}</div>
</section>"""

    return f"""<div class="wrap">
  <header class="masthead">
    <p class="eyebrow">The Corner Watchdog &middot; decision journal</p>
    <h1>Most of what this agent decided was to leave things alone</h1>
    <p class="standfirst">Every evaluation it made is below, in full, including and especially
    the ones that ended in nothing. A monitor that only publishes its actions is showing you a
    highlight reel.</p>
  </header>

  <section class="headline">
    <div class="rate">
      <span class="figure">{held_pct:.0f}</span><span class="unit">%</span>
      <span class="what">restraint rate</span>
    </div>
    <div class="bar" role="img" aria-label="{held_pct:.0f} percent held, {acted_pct:.0f} percent acted">
      <span class="seg-held" style="width: {held_pct:.2f}%"></span>
      <span class="seg-acted" style="width: {acted_pct:.2f}%"></span>
    </div>
    <p class="definition">{s["held"]} of {s["total"]} evaluations ended in no action. That is the
    whole definition: every entry in the journal is the denominator, nothing is filtered out,
    and the {s["acted"]} that did end in action are shown below with the same weight as the rest.</p>
    {breakdown}
  </section>

  <section class="counts">
    <div class="count"><span class="n">{s["corners"]}</span><span class="k">corners watched</span></div>
    <div class="count"><span class="n">{s["total"]}</span><span class="k">evaluations</span></div>
    <div class="count"><span class="n">{s["by_rule"]}</span><span class="k">settled by rule</span></div>
    <div class="count"><span class="n">{s["escalated"]}</span><span class="k">sent to deliberation</span></div>
    <div class="count"><span class="n">{s["actions"]}</span><span class="k">actions taken</span></div>
    <div class="count"><span class="n">{s["intents"]}</span><span class="k">refused by budget</span></div>
  </section>

  {notice}

  <section>
    <div class="section-head">
      <p class="eyebrow">Newest first</p>
      <h2>The journal</h2>
      <p>A decline is rendered at the same size as an action, with its reasoning attached.
      Nothing here is collapsed or greyed out.</p>
    </div>
    <div class="entries">{entry_html}</div>
  </section>

  {rehearsal_section}

  <footer class="colophon">
    <p>Rendered {_e(generated_at)} from <code>state/journal.jsonl</code>. Static page, no
    scripts, no analytics, nothing fetched at view time.</p>
    <p>Counts come from San Francisco's open data portal within 150 metres of each corner:
    injury collisions over five years, filtered street-condition 311 reports over three.
    The watched set is the worst 25 corners on StreetCred's public scoreboard.</p>
    <p>This run posted nothing anywhere. Every action shown was rendered to a local outbox
    and read by nobody but the person who ran it.</p>
  </footer>
</div>"""


def render_fragment(entries, *, rehearsal=None, generated_at=None) -> str:
    """Head bits and content together, for a host that supplies the skeleton."""
    return HEAD + "\n" + render_body(entries, rehearsal=rehearsal, generated_at=generated_at)


def render_document(entries, *, rehearsal=None, generated_at=None) -> str:
    """A standalone file, openable straight from disk."""
    body = render_body(entries, rehearsal=rehearsal, generated_at=generated_at)
    return (
        '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"{HEAD}\n</head>\n<body>\n{body}\n</body>\n</html>\n"
    )


def render_to_file(
    *,
    state_dir: str | Path = "state",
    out_path: str | Path = "docs/ledger.html",
    rehearsal_dir: str | Path | None = "state-rehearsal",
) -> Path:
    entries = LocalJsonStore(state_dir).read_journal()
    rehearsal: list[dict[str, Any]] = []
    if rehearsal_dir and Path(rehearsal_dir).exists():
        rehearsal = LocalJsonStore(rehearsal_dir).read_journal()

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_document(entries, rehearsal=rehearsal))
    return out
