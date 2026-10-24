#!/usr/bin/env python3
"""lines2pdf - the objects found on a PDF's pages, stroked into the PDF itself.

The same input as lines2ps.py (a lines.json, or boxes with `page_to_image`),
the other route: no overlay sheet and no qpdf. Each page's content is wrapped
in q ... Q and a content stream with the strokes, in PDF default user space,
is appended after it. The page's own content is never re-interpreted or
moved, so it renders as before even where the CropBox is off-centre (where
qpdf --overlay moves it). Needs pikepdf.

    lines2pdf.py doc.lines.json doc.pdf -o stamped.pdf

Exit status as lines2ps: 0 every object drawn; 3 partial (listed on stderr
after "partial:", the PDF still written); 2 bad input (nothing written).
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lines2ps import (BAD_INPUT, PARTIAL, InputError, apply, pdf_pages,  # noqa: E402
                      placed, read_input)


def strokes(to_user, objects):
    """Content stream text: every object stroked in default user space."""
    out = ["q 0.5 w [] 0 d 0 J 0 j"]
    for obj in objects:
        for pts, closed, (r, g, b) in obj:
            xy = [apply(to_user, x, y) for x, y in pts]
            out.append(f"{r} {g} {b} RG {xy[0][0]:.3f} {xy[0][1]:.3f} m " +
                       " ".join(f"{x:.3f} {y:.3f} l" for x, y in xy[1:]) +
                       (" h S" if closed else " S"))
    out.append("Q")
    return out


def depth(pikepdf, page):
    """(lowest, final) save depth of a page's content, relative to its start."""
    level = low = 0
    for _, op in pikepdf.parse_content_stream(page):
        if op == pikepdf.Operator("q"):
            level += 1
        elif op == pikepdf.Operator("Q"):
            level -= 1
            low = min(low, level)
    return low, level


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("boxes", help="lines.json, or boxes with page_to_image")
    ap.add_argument("pdf", help="the PDF the boxes were found on")
    ap.add_argument("-o", "--output", required=True, help="stamped PDF")
    args = ap.parse_args(argv)

    try:
        import pikepdf
    except ImportError:
        print("error: lines2pdf needs pikepdf (pip install pikepdf)", file=sys.stderr)
        return BAD_INPUT
    try:
        geometry = pdf_pages(args.pdf)
        pages = read_input(args.boxes, geometry)
    except InputError as err:
        print(f"error: {err}", file=sys.stderr)
        return BAD_INPUT
    drawable, skipped = placed(pages, geometry)

    pdf = pikepdf.open(args.pdf)
    drawn = 0
    for n, page in enumerate(pdf.pages, 1):
        low, final = depth(pikepdf, page)
        # enough q in front that the content never pops below them, and the
        # matching Q after it: the strokes start in the page's default state
        opens = 1 - low
        ops = ["Q"] * (opens + final)
        if n in drawable:
            ops += strokes(*drawable[n])
            drawn += len(drawable[n][1])
        if isinstance(page.obj.get("/Contents"), pikepdf.Array):
            page.obj.Contents = pikepdf.Array(list(page.obj.Contents))  # unshare
        page.contents_add(pikepdf.Stream(pdf, b"q\n" * opens), prepend=True)
        page.contents_add(pikepdf.Stream(pdf, ("\n" + "\n".join(ops) + "\n").encode()),
                          prepend=False)
    pdf.save(args.output)

    total = sum(len(objects) + missing for _, objects, missing in pages.values())
    print(f"{args.output}: {len(pdf.pages)} pages, {drawn} of {total} objects drawn")
    if skipped:
        print("partial: " + "; ".join(skipped), file=sys.stderr)
        return PARTIAL
    return 0


if __name__ == "__main__":
    sys.exit(main())
