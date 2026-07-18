# Quick start

Ten minutes from a first render to exports, a locale, and provenance. Every command below is a real
Arcavex command run against the shipped examples; the output shown is what it actually prints. If
`arcavex` is not on your path yet, see [install.md](install.md); from a source checkout the binary is
`.venv/Scripts/arcavex.exe` (Windows) or `.venv/bin/arcavex` (POSIX).

Confirm the engine is healthy first:

```console
$ arcavex doctor
Arcavex engine 0.1.0
… every row: ok
```

## 1. Render the hello poster

```console
$ arcavex render examples/hello-poster/template.yaml \
    --data examples/hello-poster/data.yaml --format square -o hello.png
Rendered hello.png
```

The `-o` extension chooses the exporter. With no `-o`, Arcavex writes a deterministic default name
and reports it first (on failure too, so you always learn what would have been written):

```console
$ arcavex render examples/hello-poster/template.yaml \
    --data examples/hello-poster/data.yaml --format square
inferred: output=hello-poster.square.png
Rendered hello-poster.square.png
```

## 2. Change the data

Content is separate from the template — edit data, not the node tree. Copy the data file, change the
headline, and re-render:

```console
$ cp examples/hello-poster/data.yaml mydata.yaml
# edit mydata.yaml:  title: "My Event"
$ arcavex render examples/hello-poster/template.yaml \
    --data mydata.yaml --format square -o mine.png
Rendered mine.png
```

To see the contract a template expects before you edit — its variables, formats, node ids, and
functions — ask it:

```console
$ arcavex template inspect examples/hello-poster/template.yaml
variables (2):
  title: string (required) Main headline
  subtitle: string (optional) Supporting line under the title
formats: square, story
nodes:
  root: group
  …
```

## 3. Render a different format

The hello poster declares two canvases. Switch with `--format`:

```console
$ arcavex render examples/hello-poster/template.yaml \
    --data examples/hello-poster/data.yaml --format story -o hello-story.png
Rendered hello-story.png
```

## 4. Apply a locale

The bilingual IPEN example declares `en` and `fa`. Requesting `--locale fa` applies its direction
(RTL), digit policy (Persian digits), font stack, and any locale data overlay — reported as an
inference:

```console
$ arcavex render examples/ipen-bilingual/template.yaml \
    --data examples/ipen-bilingual/data.yaml --format square --locale fa -o ipen-fa.png
inferred: data_overlay=data.fa.yaml
Rendered ipen-fa.png
```

Requesting a locale the template does not declare is a located error, never a silent ignore:

```console
$ arcavex render examples/hello-poster/template.yaml … --locale zz …
ERROR ARC-TPL-100 Template does not declare locale 'zz'
  hint: Declare it under 'locales:', or use one of: (none).
```

## 5. Export to every format

The exporter is chosen by the output extension — `.png`, `.jpg`/`.jpeg`, `.webp`, `.pdf`. `--quality`
sets lossy quality (JPEG, lossy WebP; default 90); `--lossless` selects lossless WebP; PDF is
raster-embedded RGB at the target DPI with correct physical page size and trim/bleed boxes.

```console
$ arcavex render examples/hello-poster/template.yaml -d examples/hello-poster/data.yaml \
    -f square -o out.jpg --quality 85
Rendered out.jpg

$ arcavex render examples/hello-poster/template.yaml -d examples/hello-poster/data.yaml \
    -f square -o out.webp --lossless
Rendered out.webp

$ arcavex render examples/ipen-bilingual/template.yaml -d examples/ipen-bilingual/data.yaml \
    -f a4 --locale fa -o poster.pdf
inferred: data_overlay=data.fa.yaml
Rendered poster.pdf
```

Every format is deterministic: identical inputs produce byte-identical files, with no embedded
timestamps or run ids.

## 6. Ask where a value came from, and what an error means

`template inspect --resolved` reports the resolved direction/digits and each applied patch with its
originating layer — the answer to "why is this value what it is?":

```console
$ arcavex template inspect examples/ipen-bilingual/template.yaml \
    --resolved --format a4 --locale fa
resolved format=a4 locale=fa direction=rtl digits=fa style=-
  nodes.hero.constraints.size.h = 38% <- format:a4 (set)
  nodes.title.style.font_size = 48pt <- format:a4 (set)
  …
  nodes.accent-bar.transform.rotate = 4 <- locale:fa (set)
```

Any diagnostic code the engine emits can be explained on the spot:

```console
$ arcavex explain ARC-TPL-014
ARC-TPL-014 — Required or referenced variable is missing
A variable is required but not provided, or an expression references a variable
that is neither declared nor supplied.
fix: Add the value to your data file, give the variable a default, or guard the
reference with '| default(...)'.
```

## Where to go next

- **Author your own template** → [tutorials/building-a-template.md](tutorials/building-a-template.md)
  (start from `arcavex template new`).
- **Go bilingual** → [tutorials/bilingual-template.md](tutorials/bilingual-template.md), the
  reference poster as a worked example.
- **The full authoring vocabulary** → [template-schema.md](template-schema.md).
- **Every command and flag** → [cli.md](cli.md).
- **The flagship example** → the [reference poster](../examples/reference-poster/README.md),
  5 formats × 2 locales from one node tree.
