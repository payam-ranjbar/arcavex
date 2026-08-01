# Graphic Style Lab

Four production-style Arcavex templates in four different contexts. Each starts with neutral,
typography-free source photography; the custom effect and template create the visible style.

![Four Graphic Style Lab reference sheets](output/style-lab-overview.jpg)

| Style | Context | Native format | Custom effect |
|---|---|---|---|
| Signal Grid | Event announcement | 4:5 portrait | `swiss-cut` |
| Xerox Pulse | Video thumbnail | 16:9 landscape | `xerox-pulse` |
| Night Emulsion | Fictional movie poster | 2:3 poster | `cinema-emulsion` |
| Riso Object | Product-launch social ad | 1:1 square | `riso-register` |

Reference sheets: [Signal Grid](output/reference-01-swiss.jpg) ·
[Xerox Pulse](output/reference-02-xerox.jpg) ·
[Night Emulsion](output/reference-03-cinema.jpg) ·
[Riso Object](output/reference-04-riso.jpg)

The shared [`style-lab.yaml`](style-lab.yaml) holds palettes and effect presets. The trusted local
[`style-lab-filters`](extensions/style-lab-filters/) extension contains all four deterministic
filters and their reviewed golden fixtures.

## Run it

```sh
arcavex ext add examples/graphic-style-lab/extensions/style-lab-filters
arcavex ext enable style-lab-filters

arcavex render examples/graphic-style-lab/announcement-poster.yaml \
  --data examples/graphic-style-lab/data/announcement.yaml \
  --format portrait -o announcement.png
```

Use the equivalent template, data, and format names for the other three pieces. The shared
[`reference-sheet.yaml`](reference-sheet.yaml) renders the source-versus-output demonstration
sheets. [`verify_mcp.py`](verify_mcp.py) runs inspection, validation, preview, layout inspection,
rendering, and repeat-hash verification through the real stdio MCP server.

## Verification

- Four custom effects pass extension validation and golden tests.
- Four deliverables and four reference sheets pass the same MCP-backed render path.
- Repeated rendering is byte-identical for fixed inputs.
- Generated source assets contain no embedded typography or final style treatment.

See [`output/mcp-report.json`](output/mcp-report.json) for the recorded run.
