#!/usr/bin/env python3
"""lines2ps - a PostScript overlay sheet with the objects found on a PDF's pages.

The input is a lines.json: MathPix-shaped (pdfdrill, inkdrill --glyphs, the
MathPix lane) or GLYPHDRILL's layer projection (layers-contract L6), or boxes
in image pixels with each page's `page_to_image` affine. The output is an
overlay sheet in the shape of ovl.ps: one page per PDF page, an `Overlays`
dictionary that maps a page number to a procedure, each object stroked. The
sheet is stamped with qpdf as in README.md:

    lines2ps.py doc.lines.json doc.pdf -o rects.ps
    gs -q -dBATCH -dNOPAUSE -sDEVICE=pdfwrite -o rects.pdf rects.ps
    qpdf doc.pdf --overlay rects.pdf -- stamped.pdf

Boxes input (JSON):

    {"pages": [{"page": 1, "page_to_image": [a, b, c, d, e, f],
                "boxes": [{"bbox": [x0, y0, x1, y1], "type": "math"}]}]}

`page_to_image` maps PDF default user space (points, y up; the space of the
page's MediaBox) to image pixels (y down): x' = a*x + c*y + e,
y' = b*x + d*y + f. A lines.json page that carries `page_to_image` is drawn
with it. Otherwise its lines are in pixels of the page as shown (CropBox,
/Rotate applied), `page_width` x `page_height`, and the affine is built from
the PDF's boxes and rotation; no dpi has to be known.

A line's shape, first found wins: `region` (MathPix box); `runs`
[[y, x0, x1], ...], half-open pixel rows, drawn as the outline of their
union; `segment` [[x0, y0], [x1, y1]], an open line; `cnt`, corner points,
closed from three points on and open with two. All in image pixels.

qpdf lays each sheet page over the target's TrimBox as shown, so each sheet
page takes that size and the boxes are carried from image to user space to
that frame.

Exit status: 0 every object drawn; 3 partial (a page or object could not be
drawn, listed on stderr after "partial:"); 2 bad input.
"""
import argparse
import json
import os
import re
import subprocess
import sys

# stroke colour per box type; anything else is grey
COLOURS = {
    "math": (0.85, 0.0, 0.0),
    "equation_number": (0.85, 0.0, 0.0),
    "text": (0.0, 0.3, 0.9),
    "section_header": (0.0, 0.3, 0.9),
    "diagram": (0.0, 0.6, 0.2),
    "chart": (0.0, 0.6, 0.2),
    "table": (0.8, 0.0, 0.8),
    "table_row": (0.8, 0.0, 0.8),
    "table_column": (0.8, 0.0, 0.8),
    "simple_cell": (0.8, 0.0, 0.8),
    # GLYPHDRILL layers: by type, then type:status or type:kind from `gd`
    "B": (0.0, 0.3, 0.9),
    "A:white": (0.0, 0.6, 0.2),
    "A:gutter:gutter": (0.8, 0.0, 0.8),
    "A:gutter:short": (1.0, 0.5, 0.0),
    "A:gutter:unsupported": (0.5, 0.5, 0.5),
    "A:baseline": (0.0, 0.6, 0.7),
    "A:gap": (0.7, 0.6, 0.0),
    "G:edge:gap": (0.6, 0.6, 0.6),
    "G:edge:touch": (0.85, 0.0, 0.0),
    "G:edge:side": (0.5, 0.0, 0.8),
}
GREY = (0.5, 0.5, 0.5)
PARTIAL = 3
BAD_INPUT = 2
# gs keeps every token of a procedure on its operand stack while reading
# it, so a page is drawn by a series of procedures of this many tokens at
# most, and a path longer than MAX_POINTS is cut into open pieces
CHUNK_TOKENS = 10000
MAX_POINTS = 3000


class InputError(Exception):
    pass


# --- affines, PDF order (a, b, c, d, e, f) ---------------------------------

def apply(m, x, y):
    a, b, c, d, e, f = m
    return a * x + c * y + e, b * x + d * y + f


def compose(m, n):
    """First m, then n."""
    a, b, c, d, e, f = m
    A, B, C, D, E, F = n
    return (a * A + b * C, a * B + b * D, c * A + d * C, c * B + d * D,
            e * A + f * C + E, e * B + f * D + F)


def invert(m):
    a, b, c, d, e, f = m
    det = a * d - b * c
    if abs(det) < 1e-12:
        raise ValueError("page_to_image is not invertible")
    return (d / det, -b / det, -c / det, a / det,
            (c * f - d * e) / det, (b * e - a * f) / det)


def shown_frame(box, rotate):
    """User space -> the box as shown (/Rotate applied, clockwise), origin
    at its lower left; and the shown width and height."""
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    r = rotate % 360
    if r == 0:
        return (1, 0, 0, 1, -x0, -y0), (w, h)
    if r == 90:
        return (0, -1, 1, 0, -y0, x1), (h, w)
    if r == 180:
        return (-1, 0, 0, -1, x1, y1), (w, h)
    if r == 270:
        return (0, 1, -1, 0, y1, -x0), (h, w)
    raise InputError(f"/Rotate {rotate} is not a multiple of 90")


# --- the PDF's pages ---------------------------------------------------------

def pdf_pages(pdf):
    """[{crop, trim, rotate}] for each page, from pdfinfo -box."""
    try:
        out = subprocess.run(["pdfinfo", "-box", "-f", "1", "-l", "999999", pdf],
                             capture_output=True, text=True, check=True).stdout
    except subprocess.CalledProcessError as err:
        raise InputError(f"pdfinfo failed on {pdf}: {err.stderr.strip()}")
    pages = {}
    num = r"(-?[\d.]+)"
    for n, kind, *box in re.findall(
            rf"^Page\s+(\d+) (CropBox|TrimBox):\s+{num}\s+{num}\s+{num}\s+{num}",
            out, re.M):
        pages.setdefault(int(n), {})[kind] = tuple(map(float, box))
    for n, r in re.findall(r"^Page\s+(\d+) rot:\s+(\d+)", out, re.M):
        pages.setdefault(int(n), {})["rotate"] = int(r)
    return [{"crop": pages[n]["CropBox"], "trim": pages[n]["TrimBox"],
             "rotate": pages[n].get("rotate", 0)} for n in sorted(pages)]


# --- readers: both give {page: (page_to_image, objects, missing)}, an object
#     being [(points, closed, colour)], the pieces of one line or box

def colour(line):
    kind = line.get("type") or ""
    gd = line.get("gd") or {}
    for key in (f"{kind}:{gd.get('status')}", f"{kind}:{gd.get('kind')}",
                kind, kind.split(":")[0]):
        if key in COLOURS:
            return COLOURS[key]
    return GREY


def rect(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def run_outline(runs):
    """The outline of a union of half-open pixel rows [y, x0, x1), as
    closed paths: vertical edges merged down the rows, horizontal edges
    where two rows' cover differs, the pieces chained end to end."""
    rows = {}
    for y, x0, x1 in runs:
        rows.setdefault(y, []).append((x0, x1))
    vertical = set()  # unit edges (x, y): x, from y to y + 1; shared ones cancel
    for y, spans in rows.items():
        for x0, x1 in spans:
            vertical ^= {(x0, y)}
            vertical ^= {(x1, y)}
    by_x = {}
    for x, y in vertical:
        by_x.setdefault(x, []).append(y)
    pieces = []
    for x, ys in by_x.items():
        ys.sort()
        start = prev = ys[0]
        for y in ys[1:] + [None]:
            if y != prev + 1:
                pieces.append(((x, start), (x, prev + 1)))
                start = y
            prev = y
    for y in set(rows) | {r + 1 for r in rows}:
        ends = {}
        for spans in (rows.get(y - 1, ()), rows.get(y, ())):
            for x0, x1 in spans:  # cover parity changes at each end
                ends[x0] = ends.get(x0, 0) + 1
                ends[x1] = ends.get(x1, 0) + 1
        inside = False
        for x in sorted(ends):
            if ends[x] % 2:
                inside = not inside
                if inside:
                    start = x
                else:
                    pieces.append(((start, y), (x, y)))
    at = {}
    for i, (p, q) in enumerate(pieces):
        at.setdefault(p, []).append(i)
        at.setdefault(q, []).append(i)
    used = [False] * len(pieces)
    paths = []
    for i, (p, q) in enumerate(pieces):
        if used[i]:
            continue
        used[i] = True
        path, here = [p, q], q
        while True:
            nxt = next((j for j in at[here] if not used[j]), None)
            if nxt is None:
                break
            used[nxt] = True
            a, b = pieces[nxt]
            here = b if a == here else a
            path.append(here)
        closed = path[-1] == path[0]
        paths.append((path[:-1] if closed else path, closed))
    return paths


def shapes(line):
    """[(points, closed)] of a lines.json line, or [] if it has no shape."""
    if line.get("region"):
        r = line["region"]
        x, y = r["top_left_x"], r["top_left_y"]
        return [(rect(x, y, x + r["width"], y + r["height"]), True)]
    if line.get("runs"):
        return run_outline(line["runs"])
    if line.get("segment"):
        return [([tuple(p) for p in line["segment"]], False)]
    cnt = line.get("cnt") or []
    if len(cnt) >= 2:
        return [([tuple(p) for p in cnt], len(cnt) >= 3)]
    return []


def read_boxes(doc):
    pages = {}
    for p in doc["pages"]:
        pages[p["page"]] = (tuple(p["page_to_image"]),
                            [[(rect(*b["bbox"]), True, colour(b))] for b in p["boxes"]],
                            0)
    return pages


def read_lines_json(doc, geometry):
    """lines.json lines; page_to_image from the page, or from the CropBox
    as shown."""
    pages = {}
    for p in doc["pages"]:
        n = p["page"]
        drawn, missing = [], 0
        for line in p.get("lines", []):
            found = shapes(line)
            missing += not found
            if found:
                drawn.append([(pts, closed, colour(line)) for pts, closed in found])
        if "page_to_image" in p:
            affine = tuple(p["page_to_image"])
            # GLYPHDRILL's frame is undecided where the CropBox does not
            # start at (0, 0): user space or CropBox-relative (T-0066 f)
            if 1 <= n <= len(geometry) and tuple(geometry[n - 1]["crop"][:2]) != (0, 0):
                affine = ("page_to_image frame undecided: CropBox starts at "
                          "({:g}, {:g})".format(*geometry[n - 1]["crop"][:2]))
        elif not 1 <= n <= len(geometry):
            affine = None
        else:
            g = geometry[n - 1]
            to_shown, (w, h) = shown_frame(g["crop"], g["rotate"])
            kx, ky = p["page_width"] / w, p["page_height"] / h
            affine = compose(to_shown, (kx, 0, 0, -ky, 0, h * ky))
        pages[n] = (affine, drawn, missing)
    return pages


def read_input(path, geometry):
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
        first = doc["pages"][0] if doc["pages"] else {}
        if "boxes" in first:
            return read_boxes(doc)
        return read_lines_json(doc, geometry)
    except (OSError, ValueError, KeyError, TypeError, IndexError) as err:
        raise InputError(f"{path}: not a lines.json or boxes file ({err!r})")


# --- the sheet ---------------------------------------------------------------

def split_path(xy, closed):
    """[(points, closed)]: the path whole, or cut into open pieces of at
    most MAX_POINTS that share their ends (a closed path keeps its last
    edge as a piece of its own)."""
    if len(xy) <= MAX_POINTS:
        return [(xy, closed)]
    ring = xy + [xy[0]] if closed else xy
    step = MAX_POINTS - 1
    return [(ring[i:i + MAX_POINTS], False) for i in range(0, len(ring) - 1, step)]


def placed(pages, geometry):
    """{page: (image_to_user, objects)} for the pages that can be drawn, and
    the list of what cannot (shared by lines2ps and lines2pdf)."""
    out, skipped = {}, []
    for n in sorted(pages):
        affine, objects, missing = pages[n]
        if missing:
            skipped.append(f"page {n}: {missing} line(s) without region, cnt, "
                           f"runs or segment")
        if not 1 <= n <= len(geometry):
            skipped.append(f"page {n}: beyond the PDF's {len(geometry)} pages "
                           f"({len(objects)} objects)")
        elif isinstance(affine, str):
            skipped.append(f"page {n}: {affine} ({len(objects)} objects)")
        else:
            try:
                out[n] = (invert(affine), objects)
            except ValueError as err:
                skipped.append(f"page {n}: {err} ({len(objects)} objects)")
    return out, skipped


def sheet(pages, geometry, source):
    """PostScript text, number of objects drawn, list of what was not."""
    out = ["%!PS  overlay sheet: objects on a PDF's pages, one page per PDF page",
           f"% from {source}",
           "/m { moveto } bind def /l { lineto } bind def /h { closepath } bind def",
           "/S { setrgbcolor stroke } bind def   % r g b S",
           f"/Overlays {max(len(geometry), 1)} dict def"]
    drawn = 0
    drawable, skipped = placed(pages, geometry)
    for n, (to_user, objects) in drawable.items():
        g = geometry[n - 1]
        to_sheet = compose(to_user, shown_frame(g["trim"], g["rotate"])[0])
        chunks, chunk, tokens = [], [], 0
        for obj in objects:
            for pts, closed, (r, gr, b) in obj:
                xy = [apply(to_sheet, x, y) for x, y in pts]
                for piece, shut in split_path(xy, closed):
                    text = (f"{piece[0][0]:.2f} {piece[0][1]:.2f} m " +
                            " ".join(f"{x:.2f} {y:.2f} l" for x, y in piece[1:]) +
                            (" h" if shut else "") + f" {r} {gr} {b} S")
                    if chunk and tokens + 3 * len(piece) > CHUNK_TOKENS:
                        chunks.append(chunk)
                        chunk, tokens = [], 0
                    chunk.append("  " + text)
                    tokens += 3 * len(piece) + 5
        if chunk:
            chunks.append(chunk)
        if chunks:
            drawn += len(objects)
            out.append(f"Overlays {n} [")
            for c in chunks:
                out.append(" { 0.5 setlinewidth")
                out.extend(c)
                out.append(" }")
            out.append("] put")
    out.append("% each page has the size of the target's TrimBox as shown;"
               " a page with no entry stays transparent")
    for n, g in enumerate(geometry, 1):
        w, h = shown_frame(g["trim"], g["rotate"])[1]
        out.append(f"<< /PageSize [{w:.4f} {h:.4f}] >> setpagedevice "
                   f"Overlays {n} 2 copy known {{ get {{ gsave exec grestore }} forall }} "
                   f"{{ pop pop }} ifelse showpage")
    return "\n".join(out) + "\n", drawn, skipped


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("boxes", help="lines.json, or boxes with page_to_image")
    ap.add_argument("pdf", help="the PDF the boxes were found on")
    ap.add_argument("-o", "--output", required=True, help="overlay sheet (.ps)")
    args = ap.parse_args(argv)

    try:
        geometry = pdf_pages(args.pdf)
        pages = read_input(args.boxes, geometry)
    except InputError as err:
        print(f"error: {err}", file=sys.stderr)
        return BAD_INPUT
    text, drawn, skipped = sheet(pages, geometry, os.path.basename(args.boxes))
    with open(args.output, "w", encoding="ascii", errors="replace") as fh:
        fh.write(text)

    total = sum(len(objects) + missing for _, objects, missing in pages.values())
    print(f"{args.output}: {len(geometry)} pages, {drawn} of {total} objects drawn")
    if skipped:
        print("partial: " + "; ".join(skipped), file=sys.stderr)
        return PARTIAL
    return 0


if __name__ == "__main__":
    sys.exit(main())
