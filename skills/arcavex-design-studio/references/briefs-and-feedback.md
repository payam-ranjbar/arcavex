# Briefs, facts and feedback

How to turn a brief and a round of feedback into the next render without guessing or inventing.

## Asking

Ask exactly **one** question when:

- a fact the design needs is missing — a date with no time, a talk with no venue; ask before the
  first render, not after it
- feedback is garbled or could mean two things
- a pronoun or vague noun ("it", "the image", "the text", "that gap") could refer to more than one
  element

Build the options from the canvas, not from memory: list node ids with
`arcavex template inspect T --json`, name every candidate (e.g. hero photo / speaker headshot /
both / something else), and say which one you would pick.

Do not ask when the feedback is clear or the fact is already in the brief or data. Do not ask
several questions at once. While waiting for an answer, do not render a guess — a wrong guess costs
a full revision.

## Never invent

Facts (dates, times, places, names, prices, credits) come only from the brief, the data, or the
user. Missing fact: ask. If the user wants a draft first, use a visibly fake placeholder and say so
in the reply.

Sample data (`preview_data`, data files) and stress fixtures use obviously fake values such as
`00:00 TBD`, `Speaker Name`, `Venue Name`, `Lorem ipsum` for long-copy tests. Never put real facts
and fake values in the same fixture: later sessions copy fixtures as if they were facts.

Decorative copy (tagline, eyebrow, kicker, slogan, "featured" labels) appears only if the user or
brand kit supplied it. Never reuse another organization's slogan, tagline or trademark, even as a
placeholder.

## Matching a reference

When the user says "match X" (last event's spacing, the old poster's size), open X's **delivered
render** — the PNG/PDF the user saw — and measure the property at full resolution (pixel gaps, cap
heights, margins). Then set the template to reproduce those pixels.

The source may differ from what was delivered (later edits, a different build, shrink), so do not
call a visible difference "intentional" from the YAML. Report the measured numbers.

## Attachments

A file the user attached is the asset to use. Find it on disk first: the harness stores attachments
somewhere local (for example pi keeps pasted images under `~/.pi/agent/image-view/blobs/`; other
harnesses pass a path in the message or a temp folder). Copy it into the project's assets, record
its provenance (original path or name, date, who supplied it) next to the asset or in the handoff,
and use that copy.

If you cannot find the file, ask for a path. Never web-search for a substitute or a lookalike: a
download can be an HTML page, a different version, or unlicensed.
