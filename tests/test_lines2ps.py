"""lines2ps: boxes land on the ink they were found on, through gs and qpdf.

Each target page carries a black rectangle in its own content. Its pixel box
is found by rendering the page as shown (as MathPix sees it), written into a
lines.json, stamped back, and the red stroke must lie on the black edges.
The expected position comes from poppler's rendering, not from lines2ps's
own arithmetic.

    python3 -m unittest discover -s tests
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(__file__))
import pdfgen  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
LINES2PS = os.path.join(HERE, "..", "psoverlay", "lines2ps.py")
DPI = 100
TOL = 2  # pixels: the 0.5 pt stroke is centred on the edge

# page boxes and rotations a born-digital PDF can carry
CASES = [
    {"MediaBox": [0, 0, 600, 800]},
    {"MediaBox": [100, 200, 700, 1000]},
    {"MediaBox": [0, 0, 600, 800], "CropBox": [50, 60, 550, 760]},
    {"MediaBox": [0, 0, 600, 800], "Rotate": 90},
    {"MediaBox": [100, 200, 700, 1000], "CropBox": [150, 260, 650, 960], "Rotate": 270},
    {"MediaBox": [0, 0, 600, 800], "CropBox": [40, 30, 560, 780], "Rotate": 180},
    {"MediaBox": [0, 0, 600, 800], "CropBox": [50, 60, 550, 760],
     "TrimBox": [70, 80, 530, 740]},
    # a lines.json goes image -> page by the CropBox and page -> sheet by the
    # TrimBox; with the two equal an error in either cancels, so these differ
    {"MediaBox": [0, 0, 600, 800], "CropBox": [30, 40, 570, 780],
     "TrimBox": [60, 90, 520, 740], "Rotate": 90},
    {"MediaBox": [100, 200, 700, 1000], "CropBox": [110, 220, 690, 980],
     "TrimBox": [150, 260, 650, 900], "Rotate": 270},
    {"MediaBox": [0, 0, 600, 800], "CropBox": [20, 30, 580, 790],
     "TrimBox": [80, 70, 540, 700], "Rotate": 180},
]


def ink_rect(case):
    """An off-centre, non-square rectangle inside the page's TrimBox."""
    box = case.get("TrimBox") or case.get("CropBox") or case["MediaBox"]
    return box[0] + 120, box[1] + 150, box[0] + 200, box[1] + 260


def run(*args):
    return subprocess.run([sys.executable, LINES2PS, *args],
                          capture_output=True, text=True)


def stamp(tmp, boxes_json, pdf):
    sheet_ps = os.path.join(tmp, "sheet.ps")
    sheet_pdf = os.path.join(tmp, "sheet.pdf")
    stamped = os.path.join(tmp, "stamped.pdf")
    res = run(boxes_json, pdf, "-o", sheet_ps)
    subprocess.run(["gs", "-q", "-dBATCH", "-dNOPAUSE", "-sDEVICE=pdfwrite",
                    "-o", sheet_pdf, sheet_ps], check=True)
    subprocess.run(["qpdf", pdf, "--overlay", sheet_pdf, "--", stamped], check=True)
    return res, stamped


def off_by(a, b):
    return max(abs(p - q) for p, q in zip(a, b))


class Placement(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="lines2ps-test-")
        cls.pdf = os.path.join(cls.tmp, "target.pdf")
        pages = []
        for case in CASES:
            x0, y0, x1, y1 = ink_rect(case)
            fill = b"0 g %d %d %d %d re f" % (x0, y0, x1 - x0, y1 - y0)
            pages.append(dict(case, content=fill))
        pdfgen.write_pdf(cls.pdf, pages)
        # what an OCR reading of the page would report: the ink, in pixels
        cls.found = []
        for n in range(1, len(CASES) + 1):
            img = pdfgen.render(cls.pdf, n, DPI, os.path.join(cls.tmp, f"t{n}"))
            cls.found.append((img[0], img[1], pdfgen.bbox_where(img, pdfgen.is_black)))

    def lines_json(self, name, shift=0):
        pages = [{"page": n, "page_width": w, "page_height": h,
                  "lines": [{"type": "math", "region": {
                      "top_left_x": b[0] + shift, "top_left_y": b[1],
                      "width": b[2] - b[0], "height": b[3] - b[1]}}]}
                 for n, (w, h, b) in enumerate(self.found, 1)]
        path = os.path.join(self.tmp, name)
        with open(path, "w") as fh:
            json.dump({"pages": pages}, fh)
        return path

    def red_boxes(self, stamped):
        return [pdfgen.bbox_where(
                    pdfgen.render(stamped, n, DPI, os.path.join(self.tmp, f"s{n}")),
                    pdfgen.is_red)
                for n in range(1, len(CASES) + 1)]

    def test_every_page_box_lands_on_its_ink(self):
        res, stamped = stamp(self.tmp, self.lines_json("lines.json"), self.pdf)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn(f"{len(CASES)} of {len(CASES)} objects drawn", res.stdout)
        for n, ((_, _, black), red) in enumerate(
                zip(self.found, self.red_boxes(stamped)), 1):
            with self.subTest(page=n, case=CASES[n - 1]):
                self.assertIsNotNone(red, "no red stroke on the page")
                self.assertLessEqual(off_by(red, black), TOL, f"red {red} black {black}")

    def test_built_to_fail_shifted_boxes_are_seen_as_off(self):
        """The check itself must catch a misplaced box: shift by 15 px."""
        _, stamped = stamp(self.tmp, self.lines_json("shifted.json", shift=15), self.pdf)
        for n, ((_, _, black), red) in enumerate(
                zip(self.found, self.red_boxes(stamped)), 1):
            with self.subTest(page=n):
                self.assertGreater(off_by(red, black), TOL)

    @unittest.expectedFailure
    def test_qpdf_overlay_leaves_the_page_in_place(self):
        """qpdf 12.3.2 wraps the original page in a form and centres its
        CropBox in the MediaBox, so a page whose CropBox is off-centre
        moves (10 pt on page 3 here; 276 pt on a real library PDF), even
        under a blank sheet. Not lines2ps's arithmetic: its boxes land on
        the ink of the original (the test above). Expected to fail until
        the stamping route changes or qpdf stops moving the page."""
        _, stamped = stamp(self.tmp, self.lines_json("lines.json"), self.pdf)
        for n, (_, _, black) in enumerate(self.found, 1):
            with self.subTest(page=n, case=CASES[n - 1]):
                after = pdfgen.bbox_where(
                    pdfgen.render(stamped, n, DPI, os.path.join(self.tmp, f"k{n}")),
                    pdfgen.is_black)
                self.assertEqual(after, black)

    def test_boxes_with_page_to_image(self):
        """GLYPHDRILL's form: bbox in image pixels plus the page affine."""
        n = 2  # MediaBox at (100, 200)
        w, h, black = self.found[n - 1]
        k = DPI / 72
        x0, y0 = CASES[n - 1]["MediaBox"][:2]
        y1 = CASES[n - 1]["MediaBox"][3]
        doc = {"pages": [{"page": n, "page_to_image": [k, 0, 0, -k, -x0 * k, y1 * k],
                          "boxes": [{"bbox": black, "type": "math"}]}]}
        path = os.path.join(self.tmp, "boxes.json")
        with open(path, "w") as fh:
            json.dump(doc, fh)
        res, stamped = stamp(self.tmp, path, self.pdf)
        self.assertEqual(res.returncode, 0, res.stderr)
        red = pdfgen.bbox_where(
            pdfgen.render(stamped, n, DPI, os.path.join(self.tmp, "b")), pdfgen.is_red)
        self.assertLessEqual(off_by(red, black), TOL, f"red {red} black {black}")


class GlyphdrillShapes(unittest.TestCase):
    """GLYPHDRILL's layer lines (layers-contract L6 amendment): `cnt`
    corners, `runs` [[y, x0, x1), ...], `segment`, and the page's own
    `page_to_image`, all in image pixels."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="lines2ps-gd-")
        cls.pdf = os.path.join(cls.tmp, "page.pdf")
        # an L of ink (a white region's shape), and a thin bar (a segment)
        ink = (b"0 g 100 500 200 40 re f 100 400 40 140 re f "
               b"350 300 150 3 re f")
        pdfgen.write_pdf(cls.pdf, [{"MediaBox": [0, 0, 600, 800], "content": ink}])
        cls.img = pdfgen.render(cls.pdf, 1, DPI, os.path.join(cls.tmp, "p"))
        w, h, rgb = cls.img
        cls.black = {(x, y) for y in range(h) for x in range(w)
                     if pdfgen.is_black(*rgb[3 * (w * y + x):3 * (w * y + x) + 3])}
        cls.ell = {(x, y) for x, y in cls.black if x < 450}  # L ends 417 px
        cls.bar = {(x, y) for x, y in cls.black if x >= 450}  # bar from 486 px
        k = DPI / 72
        cls.affine = [k, 0, 0, -k, 0, 800 * k]

    def page(self, lines):
        # page_width/page_height deliberately wrong: page_to_image must win
        return {"pages": [{"page": 1, "page_width": 10, "page_height": 10,
                           "page_to_image": self.affine, "lines": lines}]}

    def stamp_red(self, doc, name):
        path = os.path.join(self.tmp, name)
        with open(path, "w") as fh:
            json.dump(doc, fh)
        res, stamped = stamp(self.tmp, path, self.pdf)
        w, h, rgb = pdfgen.render(stamped, 1, DPI, os.path.join(self.tmp, "r" + name))
        red = {(x, y) for y in range(h) for x in range(w)
               if pdfgen.is_red(*rgb[3 * (w * y + x):3 * (w * y + x) + 3])}
        return res, red

    @staticmethod
    def bbox(pixels):
        xs, ys = [p[0] for p in pixels], [p[1] for p in pixels]
        return [min(xs), min(ys), max(xs) + 1, max(ys) + 1]

    @staticmethod
    def far(red, ink):
        """Red pixels farther than TOL from every ink pixel."""
        return [p for p in red
                if not any((p[0] + dx, p[1] + dy) in ink
                           for dx in range(-TOL, TOL + 1) for dy in range(-TOL, TOL + 1))]

    def test_runs_draw_the_shape_not_its_box(self):
        rows = {}
        for x, y in self.ell:
            rows.setdefault(y, []).append(x)
        runs = []
        for y, xs in sorted(rows.items()):
            xs.sort()
            start = xs[0]
            for a, b in zip(xs, xs[1:] + [None]):
                if b != a + 1:
                    runs.append([y, start, a + 1])
                    start = b
        box = self.bbox(self.ell)
        res, red = self.stamp_red(self.page([{"type": "math", "runs": runs,
                                              "cnt": [[box[0], box[1]], [box[2], box[1]],
                                                      [box[2], box[3]], [box[0], box[3]]]}]),
                                  "runs.json")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertLessEqual(off_by(self.bbox(red), box), TOL)
        # the box's outline would cross the L's open corner, far from ink
        self.assertEqual(self.far(red, self.ell), [])

    def test_built_to_fail_cnt_box_crosses_the_open_corner(self):
        """Drawn as its box, the same L leaves red far from the ink."""
        box = self.bbox(self.ell)
        _, red = self.stamp_red(self.page([{"type": "math", "cnt": [
            [box[0], box[1]], [box[2], box[1]], [box[2], box[3]], [box[0], box[3]]]}]),
            "box.json")
        self.assertGreater(len(self.far(red, self.ell)), 100)

    def test_segment_lies_on_the_bar(self):
        x0, y0, x1, y1 = self.bbox(self.bar)
        mid = (y0 + y1) / 2
        res, red = self.stamp_red(self.page([{"type": "math",
                                              "segment": [[x0, mid], [x1, mid]],
                                              "cnt": [[x0, mid], [x1, mid]]}]), "seg.json")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertTrue(red)
        self.assertLessEqual(off_by(self.bbox(red), [x0, y0, x1, y1]), TOL)

    def test_a_page_of_large_ragged_shapes_goes_through_gs(self):
        """300 whites of 1000 ragged rows each (an A layer at 400 dpi is
        of this size): the sheet must build in gs, whole, and quickly."""
        lines = []
        for i in range(300):
            x = 10 + (i % 30) * 25
            y = 10 + (i // 30) * 100
            runs = [[y + r, x, x + 5 + (r * 7919) % 400] for r in range(1000)]
            lines.append({"type": "math", "runs": runs})
        path = os.path.join(self.tmp, "big.json")
        with open(path, "w") as fh:
            json.dump(self.page(lines), fh)
        sheet_ps, sheet_pdf = (os.path.join(self.tmp, f) for f in ("big.ps", "big.pdf"))
        import time
        t = time.monotonic()
        res = run(path, self.pdf, "-o", sheet_ps)
        self.assertLess(time.monotonic() - t, 10)  # quadratic outlines took 16 s
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("300 of 300 objects drawn", res.stdout)
        gs = subprocess.run(["gs", "-q", "-dBATCH", "-dNOPAUSE", "-sDEVICE=pdfwrite",
                             "-o", sheet_pdf, sheet_ps], capture_output=True, text=True)
        self.assertEqual(gs.returncode, 0, gs.stdout[-500:] + gs.stderr[-500:])

    def test_line_without_geometry_is_partial(self):
        res, _ = self.stamp_red(self.page([{"type": "math", "text": "no shape"}]),
                                "none.json")
        self.assertEqual(res.returncode, 3)
        self.assertIn("partial: page 1: 1 line(s) without region, cnt, runs or segment",
                      res.stderr)


class Status(unittest.TestCase):
    """A partial sheet must say so in its exit status."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="lines2ps-status-")
        self.pdf = os.path.join(self.tmp, "one.pdf")
        pdfgen.write_pdf(self.pdf, [{"MediaBox": [0, 0, 600, 800]}])
        self.out = os.path.join(self.tmp, "o.ps")

    def write(self, doc, name="in.json"):
        path = os.path.join(self.tmp, name)
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
        self.assertTrue(os.path.exists(self.out))

    def test_singular_affine_is_partial(self):
        doc = {"pages": [{"page": 1, "page_to_image": [0, 0, 0, 0, 0, 0],
                          "boxes": [{"bbox": [1, 1, 5, 5]}]}]}
        res = run(self.write(doc), self.pdf, "-o", self.out)
        self.assertEqual(res.returncode, 3)
        self.assertIn("not invertible", res.stderr)

    def test_lines_page_to_image_on_offset_cropbox_is_partial(self):
        # GLYPHDRILL's page_to_image frame is undecided there (T-0066 f)
        pdf = os.path.join(self.tmp, "crop.pdf")
        pdfgen.write_pdf(pdf, [{"MediaBox": [0, 0, 600, 800],
                                "CropBox": [50, 60, 550, 760]}])
        doc = {"pages": [{"page": 1, "page_width": 500, "page_height": 700,
                          "page_to_image": [1, 0, 0, -1, 0, 700],
                          "lines": [{"type": "B", "cnt": [[1, 1], [9, 1], [9, 9]]}]}]}
        res = run(self.write(doc), pdf, "-o", self.out)
        self.assertEqual(res.returncode, 3)
        self.assertIn("frame undecided: CropBox starts at (50, 60)", res.stderr)
        self.assertIn("0 of 1 objects drawn", res.stdout)

    def test_lines_page_to_image_on_rotated_page_is_partial(self):
        # GLYPHDRILL's boxes are in the turned image, its page_to_image is
        # not turned (T-0066 f): the page must not be drawn
        pdf = os.path.join(self.tmp, "rot.pdf")
        pdfgen.write_pdf(pdf, [{"MediaBox": [0, 0, 600, 800], "Rotate": 90}])
        doc = {"pages": [{"page": 1, "page_width": 800, "page_height": 600,
                          "page_to_image": [1, 0, 0, -1, 0, 800],
                          "lines": [{"type": "B", "cnt": [[1, 1], [9, 1], [9, 9]]}]}]}
        res = run(self.write(doc), pdf, "-o", self.out)
        self.assertEqual(res.returncode, 3)
        self.assertIn("partial: page 1: page_to_image without the /Rotate 90 turn",
                      res.stderr)
        self.assertIn("0 of 1 objects drawn", res.stdout)

    def test_complete_sheet_exits_zero(self):
        res = run(self.write({"pages": [self.page(1)]}), self.pdf, "-o", self.out)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(res.stderr, "")

    def test_not_json_is_bad_input(self):
        res = run(self.write("{not json"), self.pdf, "-o", self.out)
        self.assertEqual(res.returncode, 2)

    def test_missing_page_size_is_bad_input(self):
        doc = {"pages": [{"page": 1, "lines": []}]}
        res = run(self.write(doc), self.pdf, "-o", self.out)
        self.assertEqual(res.returncode, 2)

    def test_missing_pdf_is_bad_input(self):
        res = run(self.write({"pages": [self.page(1)]}),
                  os.path.join(self.tmp, "nope.pdf"), "-o", self.out)
        self.assertEqual(res.returncode, 2)


if __name__ == "__main__":
    unittest.main()
