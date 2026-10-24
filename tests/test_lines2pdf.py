"""lines2pdf: the append route. The page's own content must render exactly
as before, the boxes must land on the ink, and the same checks must fail on
the qpdf route where it moves the page.

    python3 -m unittest discover -s tests

The library tests run on two real PDFs when they are present under
$PDF_OVERLAY_LIBRARY (default ~/pdfdrill-library) and are skipped otherwise;
the PDFs are third-party papers and are not in this repository.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(__file__))
import pdfgen  # noqa: E402
import test_lines2ps as base  # noqa: E402  (CASES, ink_rect, the qpdf route)

HERE = os.path.dirname(os.path.abspath(__file__))
LINES2PDF = os.path.join(HERE, "..", "psoverlay", "lines2pdf.py")
DPI = base.DPI
TOL = base.TOL
LIBRARY = os.environ.get("PDF_OVERLAY_LIBRARY",
                         os.path.expanduser("~/pdfdrill-library"))
# (PDF, pages to render): the CropBox is off-centre in both; qpdf 12.3.2
# moves the first by 23.6 pt and the second by 276 pt
LIBRARY_PDFS = [
    ("1-s2.0-S0010448509000463-main/1-s2.0-S0010448509000463-main.pdf", 18),
    ("1002445/1002445.pdf", 20),
]


def run(*args):
    return subprocess.run([sys.executable, LINES2PDF, *args],
                          capture_output=True, text=True)


def empty_lines(path, pages):
    """A lines.json with every page and no lines: the wrapper alone."""
    with open(path, "w") as fh:
        json.dump({"pages": [{"page": n, "page_width": 1, "page_height": 1,
                              "lines": []} for n in range(1, pages + 1)]}, fh)
    return path


def renders_differ(a, b, pages, tmp, dpi=DPI):
    """Page numbers whose rendering as shown differs between two PDFs."""
    out = []
    for n in range(1, pages + 1):
        ra = pdfgen.render(a, n, dpi, os.path.join(tmp, "ra"))
        rb = pdfgen.render(b, n, dpi, os.path.join(tmp, "rb"))
        if ra != rb:
            out.append(n)
    return out


def qpdf_route(tmp, lines, pdf):
    """lines2ps sheet stamped with qpdf --overlay."""
    sheet_ps, sheet_pdf = os.path.join(tmp, "q.ps"), os.path.join(tmp, "q.pdf")
    stamped = os.path.join(tmp, "qstamped.pdf")
    subprocess.run([sys.executable, base.LINES2PS, lines, pdf, "-o", sheet_ps],
                   check=True, capture_output=True)
    subprocess.run(["gs", "-q", "-dBATCH", "-dNOPAUSE", "-sDEVICE=pdfwrite",
                    "-o", sheet_pdf, sheet_ps], check=True)
    subprocess.run(["qpdf", pdf, "--overlay", sheet_pdf, "--", stamped], check=True)
    return stamped


class Append(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="lines2pdf-test-")
        cls.pdf = os.path.join(cls.tmp, "target.pdf")
        pages = []
        for case in base.CASES:
            x0, y0, x1, y1 = base.ink_rect(case)
            pages.append(dict(case, content=b"0 g %d %d %d %d re f"
                              % (x0, y0, x1 - x0, y1 - y0)))
        # content that pops below its start, changes the CTM down there and
        # leaves two q open: the boxes must still go to default user space
        pages.append({"MediaBox": [0, 0, 600, 800], "CropBox": [50, 60, 550, 760],
                      "content": b"Q 2 0 0 2 0 0 cm 0 g 60 75 40 55 re f "
                                 b"q q 3 0 0 3 0 0 cm"})
        pdfgen.write_pdf(cls.pdf, pages)
        cls.n = len(pages)
        cls.found = []
        for n in range(1, cls.n + 1):
            img = pdfgen.render(cls.pdf, n, DPI, os.path.join(cls.tmp, f"t{n}"))
            cls.found.append((img[0], img[1], pdfgen.bbox_where(img, pdfgen.is_black)))

    def lines_json(self, name):
        pages = [{"page": n, "page_width": w, "page_height": h,
                  "lines": [{"type": "math", "region": {
                      "top_left_x": b[0], "top_left_y": b[1],
                      "width": b[2] - b[0], "height": b[3] - b[1]}}]}
                 for n, (w, h, b) in enumerate(self.found, 1)]
        path = os.path.join(self.tmp, name)
        with open(path, "w") as fh:
            json.dump({"pages": pages}, fh)
        return path

    def test_wrapper_alone_leaves_every_page_pixel_identical(self):
        lines = empty_lines(os.path.join(self.tmp, "empty.json"), self.n)
        out = os.path.join(self.tmp, "wrap.pdf")
        res = run(lines, self.pdf, "-o", out)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(renders_differ(self.pdf, out, self.n, self.tmp), [])

    def test_built_to_fail_qpdf_route_moves_off_centre_pages(self):
        """The same pixel-identity check, on the qpdf route: it must see
        the pages whose CropBox is off-centre move."""
        lines = empty_lines(os.path.join(self.tmp, "empty.json"), self.n)
        stamped = qpdf_route(self.tmp, lines, self.pdf)
        self.assertNotEqual(renders_differ(self.pdf, stamped, self.n, self.tmp), [])

    def test_boxes_land_on_the_ink_and_only_stroke_pixels_change(self):
        out = os.path.join(self.tmp, "boxes.pdf")
        res = run(self.lines_json("lines.json"), self.pdf, "-o", out)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn(f"{self.n} of {self.n} objects drawn", res.stdout)
        for n, (_, _, black) in enumerate(self.found, 1):
            with self.subTest(page=n):
                before = pdfgen.render(self.pdf, n, DPI, os.path.join(self.tmp, "b"))
                after = pdfgen.render(out, n, DPI, os.path.join(self.tmp, "a"))
                red = pdfgen.bbox_where(after, pdfgen.is_red)
                self.assertIsNotNone(red, "no red stroke on the page")
                self.assertLessEqual(base.off_by(red, black), TOL,
                                     f"red {red} black {black}")
                rgb0, rgb1 = before[2], after[2]
                other = sum(1 for i in range(0, len(rgb0), 3)
                            if rgb0[i:i + 3] != rgb1[i:i + 3]
                            and not pdfgen.is_red(*rgb1[i:i + 3]))
                self.assertEqual(other, 0, "pixels changed that are not the stroke")

    def test_built_to_fail_shifted_boxes_are_seen_as_off(self):
        path = self.lines_json("lines.json")
        with open(path) as fh:
            doc = json.load(fh)
        for p in doc["pages"]:
            p["lines"][0]["region"]["top_left_x"] += 15
        with open(path + ".shifted", "w") as fh:
            json.dump(doc, fh)
        out = os.path.join(self.tmp, "shifted.pdf")
        run(path + ".shifted", self.pdf, "-o", out)
        for n, (_, _, black) in enumerate(self.found, 1):
            with self.subTest(page=n):
                red = pdfgen.bbox_where(
                    pdfgen.render(out, n, DPI, os.path.join(self.tmp, "s")),
                    pdfgen.is_red)
                self.assertGreater(base.off_by(red, black), TOL)


class Status(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="lines2pdf-status-")
        self.pdf = os.path.join(self.tmp, "one.pdf")
        pdfgen.write_pdf(self.pdf, [{"MediaBox": [0, 0, 600, 800]}])
        self.out = os.path.join(self.tmp, "o.pdf")

    def write(self, doc):
        path = os.path.join(self.tmp, "in.json")
        with open(path, "w") as fh:
            fh.write(doc if isinstance(doc, str) else json.dumps(doc))
        return path

    def page(self, n):
        return {"page": n, "page_width": 600, "page_height": 800,
                "lines": [{"type": "text", "region": {
                    "top_left_x": 10, "top_left_y": 10, "width": 50, "height": 20}}]}

    def test_page_beyond_the_pdf_is_partial(self):
        res = run(self.write({"pages": [self.page(1), self.page(2)]}), self.pdf,
                  "-o", self.out)
        self.assertEqual(res.returncode, 3)
        self.assertIn("partial: page 2", res.stderr)
        self.assertIn("1 of 2 objects drawn", res.stdout)
        self.assertEqual(subprocess.run(["qpdf", "--check", self.out],
                                        capture_output=True).returncode, 0)

    def test_complete_exits_zero(self):
        res = run(self.write({"pages": [self.page(1)]}), self.pdf, "-o", self.out)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(res.stderr, "")

    def test_not_json_is_bad_input(self):
        res = run(self.write("{not json"), self.pdf, "-o", self.out)
        self.assertEqual(res.returncode, 2)
        self.assertFalse(os.path.exists(self.out))

    def test_missing_pdf_is_bad_input(self):
        res = run(self.write({"pages": [self.page(1)]}),
                  os.path.join(self.tmp, "nope.pdf"), "-o", self.out)
        self.assertEqual(res.returncode, 2)


class Library(unittest.TestCase):
    """The two real PDFs of the measurement, where qpdf moves the page."""

    def check(self, rel, pages):
        pdf = os.path.join(LIBRARY, rel)
        if not os.path.exists(pdf):
            self.skipTest(f"not present: {pdf}")
        tmp = tempfile.mkdtemp(prefix="lines2pdf-lib-")
        total = int(subprocess.run(["pdfinfo", pdf], capture_output=True, text=True)
                    .stdout.split("Pages:")[1].split()[0])
        lines = empty_lines(os.path.join(tmp, "empty.json"), total)
        out = os.path.join(tmp, "wrap.pdf")
        res = run(lines, pdf, "-o", out)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(renders_differ(pdf, out, pages, tmp, dpi=72), [])
        # built to fail: the qpdf route under the same check
        stamped = qpdf_route(tmp, lines, pdf)
        self.assertNotEqual(renders_differ(pdf, stamped, pages, tmp, dpi=72), [])

    def test_S0010448509000463(self):
        self.check(*LIBRARY_PDFS[0])

    def test_1002445(self):
        self.check(*LIBRARY_PDFS[1])


if __name__ == "__main__":
    unittest.main()
