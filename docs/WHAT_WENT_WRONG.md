# What went wrong

**A filter that matched nothing, for the entire life of the project.**

`SEVERE_VALUES` held `("Severe Injury", "Suspected Serious Injury")` from the first commit.
Those are CHP's category names. DataSF publishes `Injury (Severe)`. The query was valid
SoQL, matched zero rows, and returned a clean zero for every corner on every sweep, which
made the rule "any new severe injury is significant" a rule that could never fire.

Nothing failed. Nothing could fail. A filter matching nothing is indistinguishable from a
corner where nothing happened. It was found by running the loop against live data and
noticing that all 25 corners reported zero severe injuries while StreetCred's own board
showed 9 at one of them.

Two things came out of it that are worth more than the fix. Every enumerated value the code
puts in a WHERE clause is now pinned against the live vocabulary with the row count carried
alongside, and a cycle refuses to start if they disagree. And the same class of bug turned
up twice more once I knew to look: a `count(*)` alias rename parsing as zero, and a tie in
the district group-by resolving to whatever order the API returned, so a tied corner would
flip district between sweeps and journal it as a real change.

**Then fixing a different bug nearly caused the exact failure this repo exists to prevent.**
Measuring against StreetCred's published figures showed the radius should be 80 metres, not
150. Changing it would have made the next sweep subtract 80 metre counts from 150 metre
counts and report a 40 percent collapse in collisions at all 25 corners on the same
morning, with confident reasoning attached. Snapshots now carry a fingerprint of the query
that produced them and the delta engine refuses to subtract across a change in it. The
cycle after the change journaled 25 refusals naming both fingerprints and took no action.

Full evidence in [`LOG.md`](../LOG.md).
