# Prospect list, SF Bay Area city street-safety staff

**Built:** 2026-08-24, for All Things Agentic (deadline Aug 31, 5pm PDT).
**48 hours from now:** through end of Wednesday 2026-08-26.

**Total:** 35 (target band 20 to 50)
**Reachable in 48h with a published, verified contact:** 29 / 35
**Need a two-minute email lookup first:** 6 / 35, each flagged `VERIFY` in the CSV

## Positioning this list assumes

> For **San Francisco Bay Area city street-safety staff** who **own a published safety record that goes stale, and who cannot trust a monitoring tool that fires on every change**, the Corner Watchdog is an autonomous agent that reads the city's own data every morning and publishes what it decided **not** to do, with the reasoning attached.

This was not written by a positioning exercise. It is assembled from the answer "city street-safety staff" plus what the repository already does, and it is the weakest link in this list. If it is wrong, the ranking below is wrong. Run `/marketing:positioning-statement` before the outreach goes out if you want it load-bearing.

## The hook that makes this list different

The agent already knows which supervisor district every watched corner sits in, so each office can be told about **its own corners** rather than about the product. Computed from `state/snapshots/` on 2026-08-24:

| District | Supervisor | Watched corners | Fatalities (5y) | Severe injuries (5y) |
| --- | --- | --- | --- | --- |
| 6 | Matt Dorsey | **17 of 25** | 5 | 98 |
| 5 | Bilal Mahmood | 6 | 3 | 27 |
| 9 | Jackie Fielder | 2 | **4** | 4 |

District 9 is the sharpest single line you have: two corners, a third of every death in the watched set.

## Top 10 (talk to first)

| # | Name | Why this person | How to reach | Status |
|---|------|-----------------|--------------|--------|
| 1 | Matt Dorsey, Supervisor D6 | 17 of 25 watched corners, 5 deaths, 98 severe injuries. The agent's letters are literally addressed to his office. | dorseystaff@sfgov.org / 415-554-7970 | not yet |
| 2 | Dominica Donovan, Chief of Staff, D6 | Decides whether a constituent-facing data tool gets 20 minutes. | Same office line, ask for her | not yet |
| 3 | Madison Tam, Legislative Aide, D6 | Fields the street-safety casework this agent's deltas are made of. | Same office line | not yet |
| 4 | Fiona Hinze, Chair, SFMTA Street Safety Committee | Chairs the committee this project was built for, at a board that must read public comment. Most reliable verified route into SFMTA. | MTABoard@sfmta.com | not yet |
| 5 | Jackie Fielder, Supervisor D9 | Two watched corners carrying 4 of the 12 fatalities. One sentence. | fielderstaff@sfgov.org / 415-554-5144 | not yet |
| 6 | Ricardo Olea, City Traffic Engineer, SFMTA | Owns the collision record the agent reads and the engineering decisions it would trigger. If the ledger is credible to anyone, it is him. | LinkedIn DM; verify email first | not yet |
| 7 | Bilal Mahmood, Supervisor D5 | 6 watched corners, 3 deaths, 27 severe injuries. | MahmoodStaff@sfgov.org / 415-554-7630 | not yet |
| 8 | Brian Xi, MTC | Staffs the Bay Area Vision Zero Working Group. One conversation, a route to every Vision Zero program in the region. | bxi@bayareametro.gov / 415-778-4433 | not yet |
| 9 | Megan Wier, Assistant Director, OakDOT | Co-chaired SF's Vision Zero Task Force from its inception, ran SFDPH health and equity, now Oakland. Has lived on both sides of this exact data. | LinkedIn DM, or ask Brian Xi for the intro | not yet |
| 10 | Uyen Ngo, Vision Zero Program Manager, SFMTA | Runs the program the agent is built around. "Most mornings it decides to do nothing" is aimed at someone drowning in alerts that all say act. | Verify title and email first, see below | not yet |

Full list of 35 in [`prospects.csv`](prospects.csv).

## Channels searched

- [x] SF Board of Supervisors, official sf.gov profile pages (11 supervisors, 13 named staff, published office emails and phones)
- [x] SFMTA official pages: Streets Division, Vision Zero Committee, Board of Directors
- [x] MTC Bay Area Vision Zero Working Group, named staff contact and public email
- [x] OakDOT and City of Berkeley Transportation Division
- [x] Vision Zero SF task force pages (yielded no individual names, only agency co-chairs)
- [ ] **Venue scan.** You told me All Things Agentic but not the venue or city. I cannot scan a room I do not know the location of. **Do this yourself in 10 minutes:** walk the room and ask who works in or with a city transportation, planning, or public-health department.
- [ ] **LinkedIn 2nd-degree.** I cannot see your network. **Do this yourself:** search LinkedIn for `SFMTA`, `Oakland Department of Transportation`, `Vision Zero`, filtered to 2nd-degree, and note anyone Berkeley CS or Build Club connects you to. Every name found this way outranks everything above it, because a warm intro beats a cold published inbox.
- [ ] Civic-tech Slacks: Code for San Francisco, OpenSF. Not searched; membership is not public.

## What is soft about this list, said plainly

- **Six rows need a two-minute email lookup before you send.** The SFMTA address pattern looks like `First.Last@sfmta.com`, but the only address I actually verified is `Erica.Kato@sfmta.com`. One confirmed example is not a confirmed pattern. Row 35 exists to resolve that cheaply.
- **Uyen Ngo's title comes from a February 2024 SFMTA document.** Confirm she is still Vision Zero Program Manager before addressing her as one. Two years is long enough for that to be wrong and embarrassing.
- **Legislative aides share one office inbox.** `dorseystaff@sfgov.org` reaches all four D6 aides. Treat rows 2 to 5 as one email naming a person, not four emails.
- **This is a business-to-government list.** Everything on it is a published professional contact at a public agency, which is the only kind of contact appropriate for cold outreach. No personal emails, no phone numbers that are not the published office line.
- **Nobody here has agreed to anything.** Every `status` is `not yet`.

## Disqualifications

Considered and rejected, so the ICP stays tight.

| Who | Why not |
|---|---|
| Jason Kligier, Mobility Manager, Santa Monica DOT | Surfaced in a Berkeley-hosted safety database and looked local. He is not: Santa Monica, outside the Bay Area reach constraint you set. Post-hackathon list. |
| Walk San Francisco, SF Bicycle Coalition | Advocacy, not city staff. You chose city street-safety staff as the ICP, and these are the second-best-fit segment, not this one. Keep for the pivot. |
| Vision Zero Network | National nonprofit. Great amplifier, not a buyer, and not city staff. |
| Caltrans District 4 | State rather than city, and owns highways rather than the intersections this agent watches. Slower procurement than a hackathon can use. |
| SFCTA | Funds and evaluates Vision Zero rather than publishing the corner record the agent corrects. Wrong side of the problem. |
| SFDPH, as an agency | Co-chairs the Vision Zero task force and would be a real prospect, but no individual staff member is named on any public page I could find. Nothing concrete enough to contact. |
| The Bay Area Vision Zero Working Group meeting itself | The next quarterly meeting was 2026-08-13, eleven days ago. The meeting is not a 48-hour channel; Brian Xi is. |
| SF supervisors in D1, D2, D3, D4, D7, D10, D11 | Kept on the list at ranks 25 to 32, but they have no watched corners, so there is no specific fact to open with. Contact only after the three priority offices have replied. |
| Erica Kato, SFMTA press office | On the list at rank 35 as a routing call, not a pitch. Pitching the press office is how you get a press response to a product question. |

## What to do next

1. Send to ranks 1, 5 and 7 first, one email each, leading with that district's own numbers. Not the product.
2. Send to rank 4 at `MTABoard@sfmta.com` the same morning; it is the highest-confidence inbox on the list.
3. Do the venue scan and the LinkedIn 2nd-degree pass yourself. Anything warm you find goes to the top.
4. Log the first reply as a `stakeholder-conversation` milestone. Nothing here counts until a real person answers.
