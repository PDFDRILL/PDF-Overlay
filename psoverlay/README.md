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

## The mechanisms

A and B share one contract: a dictionary `Overlays` maps a page number to a
procedure, and that procedure runs in PDF user space (points, origin at the
lower left). A page with no entry is left alone.

**A — `EndPage` hook** (`h1.ps`, `c4.ps`). Ghostscript interprets the PDF and
calls the hook after each page. One pass, but `pdfwrite` rewrites the whole
file.

**B — overlay sheet + `qpdf --overlay`** (`ovl.ps`). PostScript emits an
N-page transparent sheet; qpdf stamps it onto the original, whose content
streams are never re-interpreted. Pages without an overlay come out
pixel-identical to the source, as long as each page's CropBox is centred in
its MediaBox. qpdf 12.3.2 wraps the original
page in a form and centres its CropBox in the MediaBox, so an off-centre
CropBox moves the page's own content, blank sheet or not (10 pt on a test
page; 23.6 pt and 276 pt on two library PDFs). Not in the release notes;
`tests/` holds it as an expected failure.

**C — append** (`lines2pdf.py`, boxes and lines only). Each page's content is
wrapped in `q … Q` and a content stream with the strokes, in default user
space, is appended. Nothing is re-interpreted or moved: the page renders as
before whatever its CropBox (measured on the two library PDFs B moves, and
on a page that pops below its start). Needs pikepdf.

B and C are both kept; which one stays is decided once more functions are
defined. What each changes: B moves the content of pages with an off-centre
CropBox; C needs pikepdf and rewrites the file (pikepdf save), with the page
content streams untouched apart from the added `q`/`Q` and strokes.

## Files

| file | what it is |
|---|---|
| `curvebase.ps` | the curve basis extracted verbatim from `e12s41.ps` |
| `plot.ps` | `HPLOT` / `VPLOT`, two classes derived from `CURVE` |
| `h1.ps` | smallest hook example — two lines on page 3 |
| `c4.ps` | both curves on page 3 via the hook (mechanism A) |
| `ovl.ps` | the same curves as an overlay sheet (mechanism B) |
| `lines2ps.py` | an overlay sheet of the boxes in a `lines.json` or a boxes file (mechanism B) |
| `lines2pdf.py` | the same boxes stroked into the PDF itself (mechanism C) |

## Requirements

Ghostscript 10, qpdf, poppler-utils (`pdfinfo`, `pdftoppm`); pikepdf for
`lines2pdf.py` (mechanism C) only.

## Usage

Run from this directory. Mechanism B:

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

## Objects from a lines.json, or boxes with the page affine

`lines2ps.py` writes an overlay sheet with every object stroked, one sheet
page per PDF page, in the same `Overlays` contract. The input is a
lines.json, MathPix-shaped (pdfdrill, inkdrill `--glyphs`, the MathPix
lane) or GLYPHDRILL's layer projection (`*.overlay.lines.json`, its
layers-contract L6 amendment), or boxes in image pixels with each page's
`page_to_image`:

```json
{"pages": [{"page": 1, "page_to_image": [a, b, c, d, e, f],
            "boxes": [{"bbox": [x0, y0, x1, y1], "type": "math"}]}]}
```

`page_to_image` maps PDF default user space (points, y up, the space of the
MediaBox) to image pixels (y down): `x' = a*x + c*y + e`, `y' = b*x + d*y + f`.
A lines.json page that carries `page_to_image` is drawn with it, except
where the PDF page's CropBox does not start at (0, 0) or the page has a
`/Rotate`. There GLYPHDRILL writes `page_to_image` from the CropBox's
corner and without the turn today (T-0066 f), while its pixels are of the
page as shown; the
coordinator has ruled (2026-10-23) that it moves to default user space, so
the contract above stays. Until GLYPHDRILL's files are in that frame such a
page is skipped and the run is partial. Otherwise its lines are in pixels of the page as shown (CropBox, `/Rotate` applied),
`page_width` x `page_height`, and the affine is built from the PDF's CropBox
and rotation (`pdfinfo -box`), so no dpi has to be known.

A line's shape, first found wins, all in image pixels: `region` (MathPix
box); `runs` `[[y, x0, x1], ...]`, half-open pixel rows, drawn as the outline
of their union (a GLYPHDRILL `A:white`); `segment` `[[x0, y0], [x1, y1]]`, an
open line (gutters, baselines, `G:edge`); `cnt`, corner points, closed from
three on and open with two. A line with none of them is not drawn and makes
the run partial.

```sh
./lines2ps.py doc.lines.json doc.pdf -o rects.ps
gs -q -dBATCH -dNOPAUSE -sDEVICE=pdfwrite -o rects.pdf rects.ps
pdfinfo rects.pdf | grep Pages        # must equal the PDF's page count
qpdf doc.pdf --overlay rects.pdf -- stamped.pdf
```

Mechanism C, the same input, in one step and without qpdf:

```sh
./lines2pdf.py doc.lines.json doc.pdf -o stamped.pdf
```

It puts enough `q` before each page's content that the content never pops
below them, and the matching `Q` after it, so the strokes start in the
page's default graphics state. Exit status as below; on bad input nothing
is written.

qpdf lays each sheet page over the target's TrimBox as shown (measured: it
translates to the box origin, turns with `/Rotate`, and scales a sheet page
of another size to fit). So each sheet page takes that size, and each box's
points go image -> user space -> that frame; a skewed affine gives a
quadrilateral. Colour by `type`: maths red, text blue, diagram/chart green,
table magenta; GLYPHDRILL `B` blue, `A:white` green, `A:gutter` by status
(gutter magenta, short orange, unsupported grey), `A:baseline` cyan, `A:gap`
olive, `G:edge` by kind (gap light grey, touch red, side violet); everything
else grey. The sheet is self-contained, so `gs` needs no permit. gs keeps a
procedure's tokens on its operand stack while it reads it, so each page is
drawn by an array of procedures of at most 10,000 tokens, and a path of
more than 3,000 points is cut into open pieces (an A layer at 400 dpi
overflowed a single procedure).

Exit status: `0` every object drawn; `3` partial (a page beyond the PDF, a
`page_to_image` on a page whose CropBox does not start at (0, 0) or
that has a `/Rotate`, an
affine that cannot be inverted, a line without a shape), each listed on
stderr after `partial:`,
the sheet still written; `2` bad input (not JSON, no page size, no PDF).

Tests: `python3 -m unittest discover -s tests` (from the repository root).
Mechanism C (`tests/test_lines2pdf.py`): with no boxes every page renders
pixel-identical to the source, over the same page boxes and a page whose
content pops below its start and changes the CTM there; with boxes the red
stroke lies on the ink and no other pixel changes. Built to fail: the same
pixel-identity check on the qpdf route must see pages move. On the two
library PDFs (`$PDF_OVERLAY_LIBRARY`, default `~/pdfdrill-library`; skipped
when absent) C must leave the rendered pages identical and B must not.
Mechanism B:
Each test page carries black ink; its pixel box is found by rendering the
page as shown, stamped back, and the red stroke must lie on the black edges,
over offset MediaBox and CropBox, TrimBox inside CropBox, and `/Rotate` 90,
180, 270. GLYPHDRILL shapes: `runs` of an L of ink must outline the L, not
its box; a `segment` must lie on a bar of ink; a page of 300 ragged shapes
of 1000 rows must build in gs within 10 s. Built to fail: boxes shifted by
15 px must be seen as off; the L drawn as its box must leave red far from
the ink; a page beyond the PDF, a singular affine and a line without a
shape must exit 3.

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
- **C** — `lines2pdf.py` on 0008113v1's lines.json: 294 of 294 objects,
  294 strokes in the file; against the source, every differing pixel on
  pages 1–8 is a stroke colour. With no boxes, both library PDFs render
  pixel-identical (all 18 pages; pages 1–20), where B moves them.
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
- Pages with non-zero `/Rotate` for the curve examples (`ovl.ps`, `c4.ps`);
  `lines2ps.py` sheets are tested at 90, 180 and 270.
- Styling: grey, dash and a legend are not built.
- Placement: the examples plot into the page's own margins. The DocEng figure
  shrinks the page and puts the profiles outside it, which needs a scaled
  output page rather than a plain stamp.

## Credit

`e12s41.ps` © 1995 W. Kolbe and R. Fette. The sample PDF used in the tests is
Wang & Liu, *PDF2LaTeX* (DocEng '20), used only as a page to draw on.
