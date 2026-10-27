"""Small PDFs with chosen page boxes and rotation, and PPM reading, for tests."""
import datetime
import os
import subprocess
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def workdir(suite, what):
    """A new directory for one test's files, kept for inspection under
    <repo>/work/tests/<suite>-<date>/ (ENGINEERING 2c). $PDF_OVERLAY_WORK
    replaces <repo>/work/tests; set it to /tmp only for a throwaway run."""
    root = os.environ.get("PDF_OVERLAY_WORK") or os.path.join(REPO, "work", "tests")
    run = os.path.join(root, f"{suite}-{datetime.date.today():%Y-%m-%d}")
    os.makedirs(run, exist_ok=True)
    return tempfile.mkdtemp(prefix=what + "-", dir=run)


def write_pdf(path, pages):
    """pages: dicts with MediaBox and optionally CropBox, TrimBox, Rotate
    and content (bytes of a content stream)."""
    objs = []

    def add(body):
        objs.append(body)
        return len(objs)

    catalog, tree = add(None), add(None)
    kids = []
    for p in pages:
        c = p.get("content", b"")
        stream = add(b"<< /Length %d >>\nstream\n" % len(c) + c + b"\nendstream")
        extra = b"".join(b" /%s [%s]" % (k.encode(), " ".join(map(str, p[k])).encode())
                         for k in ("MediaBox", "CropBox", "TrimBox") if k in p)
        if p.get("Rotate"):
            extra += b" /Rotate %d" % p["Rotate"]
        kids.append(add(b"<< /Type /Page /Parent %d 0 R /Resources << >>%s "
                        b"/Contents %d 0 R >>" % (tree, extra, stream)))
    objs[catalog - 1] = b"<< /Type /Catalog /Pages %d 0 R >>" % tree
    objs[tree - 1] = b"<< /Type /Pages /Kids [%s] /Count %d >>" % (
        b" ".join(b"%d 0 R" % k for k in kids), len(kids))
    out, offsets = b"%PDF-1.4\n", []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objs) + 1, xref)
    with open(path, "wb") as fh:
        fh.write(out)


def render(pdf, page, dpi, out_stem):
    """One page as shown (CropBox, /Rotate) through pdftoppm, no
    anti-aliasing; returns (width, height, rgb bytes)."""
    subprocess.run(["pdftoppm", "-cropbox", "-f", str(page), "-l", str(page),
                    "-r", str(dpi),
                    "-aa", "no", "-aaVector", "no", "-singlefile",
                    pdf, out_stem], check=True)
    with open(out_stem + ".ppm", "rb") as fh:
        data = fh.read()
    fields, pos = [], 0
    while len(fields) < 4:  # P6 width height maxval, whitespace separated
        while data[pos:pos + 1].isspace():
            pos += 1
        start = pos
        while not data[pos:pos + 1].isspace():
            pos += 1
        fields.append(data[start:pos])
    w, h = int(fields[1]), int(fields[2])
    return w, h, data[pos + 1:]


def bbox_where(img, test):
    """[x0, y0, x1, y1) of the pixels whose (r, g, b) passes test, or None."""
    w, h, rgb = img
    xs, ys = [], []
    for y in range(h):
        row = rgb[3 * w * y:3 * w * (y + 1)]
        for x in range(w):
            if test(row[3 * x], row[3 * x + 1], row[3 * x + 2]):
                xs.append(x)
                ys.append(y)
    if not xs:
        return None
    return [min(xs), min(ys), max(xs) + 1, max(ys) + 1]


def is_black(r, g, b):
    return r < 60 and g < 60 and b < 60


def is_red(r, g, b):
    return r > 150 and g < 100 and b < 100
