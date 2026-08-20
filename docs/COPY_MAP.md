# Copy map

One home per idea. A judge reading the README, then the FAQ, then the ledger
should meet each argument once, in full, and afterwards meet only a pointer.

This file is the contract. `tools/check_copy_map.py` enforces it, so a block
reappearing outside its home fails the build rather than waiting to be noticed by
somebody reading three documents in a row.

## What is not in scope

- **`DECISIONS.md` and `LOG.md`** are append-only records. Repetition in them is
  history, and editing them to remove it would be the opposite of a decision
  journal.
- **`docs/blog_draft.md`, `docs/demo_script.md`, `docs/social_draft.md`** are
  standalone artefacts. Each one is read alone, by somebody who has read nothing
  else, so each must restate whatever it needs. Deduplicate within one of them,
  never across them.
- **Journal entries and ledger data.** Only the page chrome around them is here.
- **`CONTRIBUTING.md`** is read by a contributor rather than a judge, and it is
  outside the traversal this pass is about. It appears below only where it pins a
  number.

## The map

| Block | Canonical home | Everywhere else |
| --- | --- | --- |
| Restraint thesis | `README.md`, "Why the declines are the product" | one line and a pointer |
| Origin disclosure | `README.md`, "Disclosure", first bullet | one line and a pointer |
| Two-tier brain and the rule floor | `docs/architecture.md` | one line and a pointer |
| Degradation admission, current behaviour | `README.md`, "Says when it is degraded" | one line and a pointer |
| Degradation admission, how it was false | `LOG.md`, the audit section | one line and a pointer |
| ADK status | `README.md` disclosure sentence and requirements row | pointer only |
| No cloud account touched | `README.md`, "Disclosure", second bullet | one line and a pointer |
| Numbers | wherever `tools/check_numbers.py` pins them | relative reference, no figure |

### Restraint thesis

Full statement stays in the README, which is where a judge meets it first.

The ledger page header gets one line and a pointer. It keeps its own headline,
"Most of what this agent decided was to leave things alone", because that is the
page making its own claim about its own contents rather than restating the
argument for it.

The FAQ's "Why are the declines the product?" answer links rather than restates.
Its second paragraph, the one about confident noise training readers to ignore a
monitor within a week, appears nowhere else and stays.

### Two-tier brain

The instruction placed this in a README architecture section. There is no such
section: the D2 rewrite replaced it with a link to `docs/architecture.md`, which
is now the architecture section of this project and is linked from the README
masthead. Canonical home is therefore `docs/architecture.md`, and this is
recorded as a map correction rather than followed off a cliff.

The README keeps its one-line "Routes by cost" capability bullet, which is a
statement rather than an explanation. `GEMINI_WIRING.md` and the FAQ point at
`architecture.md`.

### Degradation admission

This is two blocks that were being moved as one, which is why it ended up in four
places.

The **current behaviour**, that every entry names which tier was not a model and
the ledger counts how many carry it, is a capability. It belongs in the README's
capability bullet.

The **story of how that claim was false**, that the caveat used to attach only to
entries a tier had weighed so none of the first 150 carried it, is history. It is
already recorded in `LOG.md` under the audit section, which is append only and
exempt. Everywhere else points there.

`docs/architecture.md` keeps a short statement of the behaviour, because a
diagram genuinely cannot show it and the section exists to say so, and points at
`LOG.md` for the story. The FAQ points at both.

### Numbers

Any figure that moves belongs where `tools/check_numbers.py` already pins it, so
that changing it is one edit. Twelve figures are pinned across `README.md`,
`docs/FAQ.md`, `docs/blog_draft.md`, `docs/social_draft.md` and
`CONTRIBUTING.md`.

Mentions outside those become relative references with no figure in them, for
example "the full suite" rather than a test count. The two drafts keep their
pinned figures because they are standalone artefacts.

## Rules

1. **Nothing that appears only once may be deleted.** This pass removes
   duplicates and relocates blocks. It does not cut content, and it does not
   rewrite meaning.
2. **The README must still fully brief a cold judge** who reads nothing else. If
   removing a duplicate breaks that, the map is wrong and gets fixed here first.
3. **A pointer says where and why**, not just "see above". A reader who cannot
   follow the link should still learn where the argument lives.
4. **Guards move with the text.** Any check pinning a sentence is updated in the
   same commit that moves it, so no commit exists where a guard asserts text that
   is no longer there.
