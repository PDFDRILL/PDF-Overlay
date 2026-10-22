# PDF-Overlay

Small marks (an underscore, a point) placed into the open cells of large
matrices in a PDF, so that a mathematical OCR (MathPix) reads the matrix
whole: every cell has ink, and rows and columns keep their alignment. The
marks are known placeholders and are taken out of the returned LaTeX by
position afterwards.

## Approach

- The overlay is applied to the PDF itself through Ghostscript. It does
  not depend on the document's LaTeX source; a source, where one exists,
  may check a result but is never the input.
- First slice: born-digital PDFs, where the glyph positions are read from
  the PDF's own content stream.
- Later: scans, where the cells are found from the page's ink and white
  space.

## Part of the drill group

PDF-Overlay works with the group's readers and ink tools:
[inkdrill](https://github.com/PDFDRILL/inkdrill) (ink blobs, and the
comparison of a rendered reading against the page),
[GLYPHDRILL](https://github.com/PDFDRILL/GLYPHDRILL) (white space and
column gaps, including open white space inside a matrix), and pdfdrill
(the MathPix lane and the stream reader). The aim behind it: close the
loop between OCR and LaTeX mathematics, checked on the page's ink.

## State

New (2026-10-22). No code yet; the design is being brought in from a
chat. Licence: MIT (LICENSE).
