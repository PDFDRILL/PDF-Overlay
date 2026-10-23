# PostScript overlays over PDF pages

Draw measurement curves over an existing PDF page — a projection profile along
the bottom, another down the right-hand side — in the style of the figure in
*PDF2LaTeX: A Deep Learning System to Convert Mathematical Documents from PDF to
LaTeX* (DocEng '20).

The page is not re-typeset. The original PDF stays as it is and the curves are
stamped on top of it, so the text layer and every other page are untouched.

## Status

Early. What is here is a working surface for the two mechanisms and a minimal
curve basis, each with the test that was actually run (see **Measured** below).
Styling, axes and the data path are not built yet.

## Inputs this is built for

| source | gives |
|---|---|
| [inkdrill](https://github.com/PDFDRILL/inkdrill) | per-glyph ink boxes on a rendered page (`--glyphs` → MathPix-shaped `lines.json`) |
| a page histogram program | the profile values themselves |
| `e12s41.ps` | the curve library — object-oriented PostScript that draws x,y curves |

`e12s41.ps` (gewässerkundliche Elbe tables, © W. Kolbe and R. Fette, 1995) is a
concatenation of several files, each with its own header. Only its **curve
basis** is used here: `cm`, `strcat`, `curvemake` and the `CURVE` class, lifted
into `curvebase.ps` unchanged. No page preparation, no `Chapter`, no slot
layout — an overlay needs none of it.

## The two mechanisms

Both share one contract: a dictionary `Overlays` maps a page number to a
procedure, and that procedure runs in PDF user space (points, origin at the
lower left). A page with no entry is left alone.

**A — `EndPage` hook** (`h1.ps`, `c4.ps`). Ghostscript interprets the PDF and
calls the hook after each page. One pass, but `pdfwrite` rewrites the whole
file.

**B — overlay sheet + `qpdf --overlay`** (`ovl.ps`). PostScript emits an
N-page transparent sheet; qpdf stamps it onto the original, whose content
streams are never re-interpreted. **This is the recommended route**: pages
without an overlay come out pixel-identical to the source.

## Files

| file | what it is |
|---|---|
| `curvebase.ps` | the curve basis extracted verbatim from `e12s41.ps` |
| `plot.ps` | `HPLOT` / `VPLOT`, two classes derived from `CURVE` |
| `h1.ps` | smallest hook example — two lines on page 3 |
| `c4.ps` | both curves on page 3 via the hook (mechanism A) |
| `ovl.ps` | the same curves as an overlay sheet (mechanism B) |

## Requirements

Ghostscript 10, qpdf, poppler-utils (`pdfinfo`, `pdftoppm`). Nothing else.

## Usage

Run from this directory. Mechanism B, the recommended one:

```sh
gs -q -dBATCH -dNOPAUSE \
   --permit-file-read=curvebase.ps --permit-file-read=plot.ps \
   -sDEVICE=pdfwrite -o ovl.pdf ovl.ps
pdfinfo ovl.pdf | grep Pages        # must be 10
qpdf input.pdf --overlay ovl.pdf -- stamped.pdf
```

Mechanism A, in one pass:

```sh
gs -q -dBATCH -dNOPAUSE \
   --permit-file-read=curvebase.ps --permit-file-read=plot.ps \
   -sDEVICE=pdfwrite -o out.pdf c4.ps input.pdf
```

`--permit-file-read` is needed because the overlay `run`s the two library
files; the path inside the `.ps` must then match the permitted path literally.
`ovl.ps` and `c4.ps` load them by the relative names `curvebase.ps` and
`plot.ps` (the chat's copies had sandbox paths), so the permits name exactly
those; `--permit-file-read=$PWD/` does not cover a relative name.
`h1.ps` is self-contained and needs no permit.

`c4_page3.pdf` is the chat's result of C4 on page 3 of the PDF2LaTeX paper.
It stays local (`.gitignore`): the page is a third-party paper and this
repository is public.

**Always check the page count of the overlay sheet before stamping.** A
PostScript error leaves a short sheet, and qpdf will happily stamp it — the
result then looks plausible and is wrong.

## The curve classes

```postscript
HPLOT   % index → PostScript horizontal, data → PostScript vertical  (bottom profile)
VPLOT   % index → PostScript vertical,   data → PostScript horizontal (right profile)
```

```postscript
HPLOT /frame.x 54 def /frame.y 8 def /frame.w 505 def /frame.h 42 def
      /data.low 0 def /data.high 100 def oclose
Yd HPLOT plot
```

Both are made with the library's own `curvemake` and stroke through its
`strokecurve`. They differ only in `pt` (`{}` against `{exch}`) and in
`scalexy`. A message send leaves both stacks as it found them.

## Entering data: an array built by a loop

A long series cannot be pushed through the operand stack — classic
interpreters cap it at 500 operands — so the library's own main program
allocates and fills instead, and the curve takes the **reference**:

```postscript
/Y 744 array def              % allocate
0 1 743 {Y exch 0 put} for    % zero-fill
 Y 0 5.3 put  Y 1 6.3 put …   % one value per put, stack depth never exceeds 3
 Y WG                         % one operand; WG does /Y exch def
```

Short series still use a `[ … ]` literal. The examples here build 1650 values
with `0 1 N 1 sub { Yd exch <f(i)> put } for`.

## Working with `e12s41.ps`

Four things that each broke something before they were found:

1. **Drop line 4.** `[-1 0 0 1 21 cm 0] concat` mirrors the whole page.
2. **Keep the original bytes; strip only CR.** Strings use the `foreignvec`
   encoding (`\204` = ä). Re-encoding the file to UTF-8 breaks the umlauts.
3. **Derived classes need `/oclose {end oclose} def`.** After
   `(NAME) curvemake`, without it every message send leaks one dictionary.
4. **Line widths ignore the plot scale.** `strokecurve` calls `initmatrix`
   before `stroke`, so widths are in default space. Fine as long as the overlay
   is composed in PDF user space; it breaks under an extra transform.

Using the full library (not just the basis) additionally needs `Chapter begin`,
because the curve types read `Margins.left` from a dictionary the main program
opens and never closes.

## Measured

Each line is a command run on the command line, not an estimate.

- **H1** — hook draws lines on page 3 at the expected pixels; page 2 untouched.
- **C1** — the basis loads standalone; stacks invariant (op=0, dict=3) over
  four message sends; an override stays in the derived class.
- **C2** — `HPLOT` maximum, midpoint and minimum land at y = 60/40/20, residual
  0.00 pt at 288 dpi; all ink inside the frame.
- **C3** — `VPLOT` at x = 600/580/560, residual 0.00; all ink inside the frame.
- **C4** — 10 pages out; `HPLOT` maximum at y = 50.00, `VPLOT` maximum at
  x = 606.00 on a real paper page.
- **B** — after `qpdf --overlay`, every page except the overlaid one is
  pixel-identical to the source; the overlaid page gains ink.
- **inkdrill join** — 99.98 % of the page's ink pixels fall inside the reported
  glyph boxes, against 77.31 % for boxes shifted by 3 pt.

Note for mechanism A: `pdfwrite` shifts anti-aliasing by a few pixels on every
page, so "unchanged" must be measured against the same hook *without* curves,
never against the original file.

## Not yet verified

- `VPLOT` runs i = 0 at the bottom; an image profile starts at the top row, so
  either the data is reversed or the class needs a flip.
- The library's rotated axes (`axis.matrix`, `label.matrix`).
- Whether `qpdf --overlay` preserves links and annotations.
- Pages with non-zero `/Rotate`.
- Styling: grey, dash and a legend are not built.
- Placement: the examples plot into the page's own margins. The DocEng figure
  shrinks the page and puts the profiles outside it, which needs a scaled
  output page rather than a plain stamp.

## Credit

`e12s41.ps` © 1995 W. Kolbe and R. Fette. The sample PDF used in the tests is
Wang & Liu, *PDF2LaTeX* (DocEng '20), used only as a page to draw on.
