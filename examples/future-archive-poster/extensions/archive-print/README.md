# archive-print

A deterministic three-ink editorial filter for the Future Archive poster example. It maps a
photograph into warm paper and deep ink, carries cool highlights into an electric accent ink,
then adds restrained screening, scan bands, misregistration, and seeded texture.

## Workflow

```
arcavex ext validate .
arcavex ext test .
arcavex ext add .
arcavex ext enable archive-print
```

Then use the `archive-print` effect from a template and render as usual. Disabling takes effect
on the next run; the loader registers only enabled extensions at start.

## Parameters

- `shadow`, `paper`, `accent`: the three authored inks.
- `levels`, `contrast`: tonal compression.
- `screen`, `scan_pitch`: ordered micro-screen and horizontal scan rhythm.
- `texture`: deterministic paper speckle.
- `accent_strength`, `misregister`: edge/cool-highlight accent registration.

## Files

- `extension.toml` — the manifest (name, version, engine/IR floors, component list).
- `component.py` — the implementation. Import only `arcavex.sdk`.
- `golden_test.py` — the check `arcavex ext test` runs (determinism + contract behaviour).

## Regenerating the golden

After an intentional change to the look, regenerate the committed golden image and review the diff before committing:

```
python golden_test.py --update
```
