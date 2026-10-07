"""Draw the README figures for biomed-mcp-receipts: grey and white PNGs in docs/figures.

The receipt chain and the self-test matrix are drawn from a real offline self-test run, so make
one first. Needs Pillow and the macOS system fonts.

Run:
    bmr demo --out /tmp/demo
    python scripts/figures.py /tmp/demo docs/figures
"""

import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = 2  # pixels per layout unit in the saved file, sharp on high-density screens
K = 4  # pixels per layout unit while drawing; downsampled to OUT for smooth edges

BG = "#FAFAF9"
PAPER = "#FFFFFF"
INK = "#1F2328"
GREY = "#57606A"
SOFT = "#8C959F"
LINE = "#D0D7DE"
FAINT = "#EEF0F2"

HN = "/System/Library/Fonts/HelveticaNeue.ttc"
MONO = "/System/Library/Fonts/SFNSMono.ttf"

DIMS = ["conformance", "schema", "correctness", "freshness", "attribution", "robustness", "stability"]
FAULTS = [
    ("none", None),
    ("wrong_status", "correctness"),
    ("stale", "freshness"),
    ("no_source", "attribution"),
    ("fabricate", "robustness"),
    ("flaky", "stability"),
    ("bad_schema", "schema"),
    ("injection", "conformance"),
]


def font(path, size, index=0):
    return ImageFont.truetype(path, round(size * K), index=index)


TITLE = font(HN, 14, 10)  # Medium
LIGHT = font(HN, 12, 7)  # Light
NOTE = font(HN, 12.5, 7)
MONO_S = font(MONO, 10.5)
MONO_M = font(MONO, 11.5)
HEAD = font(HN, 11.5, 10)


class Canvas:
    """A drawing surface in layout units, saved at OUT pixels per unit."""

    def __init__(self, w, h):
        self.w, self.h = w, h
        self.img = Image.new("RGB", (w * K, h * K), BG)
        self.d = ImageDraw.Draw(self.img)

    @staticmethod
    def p(*vals):
        return [round(v * K) for v in vals]

    def box(self, x0, y0, x1, y1, fill=PAPER, outline=LINE, r=8, width=1.0):
        xy = self.p(x0, y0, x1, y1)
        self.d.rounded_rectangle(xy, r * K, fill=fill, outline=outline, width=round(width * K))

    def text(self, x, y, s, f, fill=INK, anchor="la"):
        self.d.text(self.p(x, y), s, font=f, fill=fill, anchor=anchor)

    def width(self, s, f):
        return self.d.textlength(s, font=f) / K

    def line(self, pts, fill=SOFT, width=1.2):
        self.d.line([tuple(self.p(x, y)) for x, y in pts], fill=fill, width=round(width * K), joint="curve")

    def arrow(self, pts, fill=SOFT, width=1.2, head=6):
        """A polyline ending in a filled arrowhead; the last segment must be horizontal or vertical."""
        (xa, ya), (xb, yb) = pts[-2], pts[-1]
        dx, dy = (xb > xa) - (xb < xa), (yb > ya) - (yb < ya)
        base = (xb - dx * head, yb - dy * head)
        self.line([*pts[:-1], base], fill, width)
        wing = head * 0.55
        bx, by = base
        tri = [(xb, yb), (bx - dy * wing, by - dx * wing), (bx + dy * wing, by + dx * wing)]
        self.d.polygon([tuple(self.p(x, y)) for x, y in tri], fill=fill)

    def node(self, x0, y0, x1, y1, lines, dark=False):
        """A rounded box with a title line and up to two lighter lines, centred."""
        self.box(x0, y0, x1, y1, fill=INK if dark else PAPER, outline=INK if dark else LINE)
        fonts = [TITLE, LIGHT, MONO_S]
        colours = [PAPER, "#D8DEE4", "#AFB8C1"] if dark else [INK, GREY, SOFT]
        heights = [17, 16, 15][: len(lines)]
        y = (y0 + y1) / 2 - sum(heights) / 2
        for s, f, c, h in zip(lines, fonts, colours, heights, strict=False):
            self.text((x0 + x1) / 2, y + h / 2, s, f, c, anchor="mm")
            y += h

    def save(self, path):
        self.img.resize((self.w * OUT, self.h * OUT), Image.LANCZOS).save(path, optimize=True)
        print("saved", path, (self.w * OUT, self.h * OUT))


def how_it_works(path):
    c = Canvas(960, 300)
    mid = 150
    c.node(20, mid - 40, 170, mid + 40, ["Task", "one capability", "NCT04280705"])
    c.node(205, mid - 40, 375, mid + 40, ["biomed-mcp-receipts", "asks both sides", "bmr run"], dark=True)
    c.node(425, 35, 615, 115, ["Server under test", "answers by MCP tool call", "pinned version"])
    c.node(425, 185, 615, 265, ["Primary source", "answers the same question", "ClinicalTrials.gov, PubMed"])
    c.node(660, mid - 40, 790, mid + 40, ["Seven scores", "side by side", "0 to 1 each"])

    # Receipts drawn as a short stack of slips.
    for k in (2, 1):
        c.box(825 + 5 * k, mid - 40 - 5 * k, 940 + 5 * k, mid + 40 - 5 * k, fill=FAINT)
    c.node(825, mid - 40, 940, mid + 40, ["Receipts", "hash chain", "RO-Crate"])

    c.arrow([(170, mid), (205, mid)])
    c.arrow([(375, mid - 12), (398, mid - 12), (398, 75), (425, 75)])
    c.arrow([(375, mid + 12), (398, mid + 12), (398, 225), (425, 225)])
    c.arrow([(615, 75), (637, 75), (637, mid - 12), (660, mid - 12)])
    c.arrow([(615, 225), (637, 225), (637, mid + 12), (660, mid + 12)])
    c.arrow([(790, mid), (825, mid)])
    c.save(path)


def short(h):
    return f"{h[:8]}…{h[-4:]}"


def receipt_chain(demo, path):
    rows = [json.loads(line) for line in (demo / "demo-none" / "receipts.jsonl").read_text().splitlines()]
    c = Canvas(960, 360)
    w, h, gap, top = 262, 232, 38, 30
    xs = [24 + i * (w + gap) for i in range(3)]
    chain_y = prev_y = 0.0
    for i, (x, r) in enumerate(zip(xs, rows[:3], strict=True)):
        c.box(x + 3, top + 4, x + w + 3, top + h + 4, fill=FAINT, outline=FAINT, r=6)
        c.box(x, top, x + w, top + h, r=6)
        px, vx = x + 18, x + 104
        c.text(px, top + 18, f"RECEIPT {i + 1} OF {len(rows)}", HEAD, INK)
        scored = [s["value"] for s in r["scores"] if s["value"] is not None]
        if len(scored) == 1:
            score_txt = f"{r['scores'][0]['dimension']} {scored[0]:.2f}"
        else:
            low = "all" if min(scored) == 1 else "lowest"
            score_txt = f"{len(scored)} scored, {low} {min(scored):.2f}"
        fields = [
            ("task", r["task_id"].replace("trial-synthetic-", "trial-")),
            ("capability", r["capability"]),
            ("scores", score_txt),
            ("request", short(r["request_sha256"]) if r.get("request_sha256") else "tools/list"),
            ("response", short(r["response_sha256"])),
        ]
        y = top + 48
        for k, v in fields:
            c.text(px, y, k, MONO_S, SOFT)
            c.text(vx, y, v, MONO_S, GREY)
            y += 22
        c.line([(px, y + 2), (x + w - 18, y + 2)], LINE, 1)
        y += 14
        prev_y = y + 7
        c.text(px, y, "prev_chain", MONO_S, SOFT)
        c.text(vx, y, short(r["prev_chain"]), MONO_S, GREY)
        y += 24
        chain_y = y + 7
        c.text(px, y, "chain", MONO_S, INK)
        c.text(vx, y, short(r["chain"]), MONO_M, INK)
        if i < 2:
            elbow = x + w + gap / 2
            c.arrow([(x + w, chain_y), (elbow, chain_y), (elbow, prev_y), (xs[i + 1], prev_y)], INK)
    c.text(xs[2] + w + 22, top + h / 2, "···", TITLE, SOFT, anchor="mm")

    notes = [
        "Each chain value hashes the previous chain value together with this line. "
        "results.json keeps the last one and the count.",
        "bmr verify recomputes every hash, so an edited, reordered, added or deleted line breaks the chain.",
    ]
    for k, s in enumerate(notes):
        c.text(480, top + h + 40 + k * 22, s, NOTE, GREY, anchor="mm")
    c.save(path)


def self_test(demo, path):
    means = {}
    for fault, _ in FAULTS:
        run = json.loads((demo / f"demo-{fault}" / "results.json").read_text())
        (server,) = run["servers"].values()
        means[fault] = {d: v["mean"] for d, v in server["dimensions"].items()}

    c = Canvas(960, 440)
    x0, y0, cw, ch = 180, 62, 108, 36
    c.text(24, y0 - 20, "planted fault", HEAD, SOFT, anchor="lm")
    for j, dim in enumerate(DIMS):
        c.text(x0 + j * cw + cw / 2, y0 - 20, dim, HEAD, INK, anchor="mm")
    for i, (fault, target) in enumerate(FAULTS):
        y = y0 + i * ch
        c.text(24, y + ch / 2, fault, MONO_M, INK if target else SOFT, anchor="lm")
        for j, dim in enumerate(DIMS):
            v = means[fault][dim]
            x = x0 + j * cw
            shade = round(255 - (1 - v) * (255 - 0x2D))
            fill = "#FFFFFF" if v >= 1 else f"#{shade:02X}{shade:02X}{min(shade + 4, 255):02X}"
            hit = dim == target
            c.box(
                x + 3, y + 3, x + cw - 3, y + ch - 3, fill, INK if hit else LINE, r=5, width=1.6 if hit else 1
            )
            colour = PAPER if v < 0.55 else (INK if v < 1 else SOFT)
            c.text(x + cw / 2, y + ch / 2, f"{v:.2f}", MONO_M, colour, anchor="mm")

    y = y0 + len(FAULTS) * ch + 34
    notes = [
        "Mean score per dimension from bmr demo, run offline against the synthetic world.",
        "Each planted fault lowers its own dimension, outlined, and leaves the other six at 1.00.",
    ]
    for k, s in enumerate(notes):
        c.text(480, y + k * 22, s, NOTE, GREY, anchor="mm")
    c.save(path)


def publishing(path):
    c = Canvas(960, 250)
    mid = 95
    w, gap = 104, 28
    xs = [32 + i * (w + gap) for i in range(7)]
    labels = [
        ["CI gate", "all faults caught"],
        ["Weekly", "live run"],
        ["Finding", "with its receipt"],
        None,
        ["Issue to the", "maintainer"],
        ["14 days", "to reply"],
        ["Publish", "scores, RO-Crate"],
    ]
    for i, (x, lab) in enumerate(zip(xs, labels, strict=True)):
        if lab is None:
            cx = x + w / 2
            dia = [(cx, mid - 42), (x + w + 6, mid), (cx, mid + 42), (x - 6, mid)]
            c.d.polygon([tuple(c.p(px, py)) for px, py in dia], fill=PAPER, outline=LINE, width=K)
            c.text(cx, mid - 8, "Confirmed", TITLE, INK, anchor="mm")
            c.text(cx, mid + 9, "by a person?", LIGHT, GREY, anchor="mm")
        else:
            c.node(x, mid - 34, x + w, mid + 34, lab, dark=i == 6)
        if i:
            left = xs[i - 1] + w + (6 if i == 4 else 0)
            c.arrow([(left, mid), (x - (6 if i == 3 else 0), mid)])
    c.text((xs[3] + w + 6 + xs[4]) / 2, mid - 6, "yes", LIGHT, GREY, anchor="md")

    # The loop back: an unconfirmed finding sends the task back for a fix.
    cx, back = xs[3] + w / 2, xs[1] + w / 2
    c.arrow([(cx, mid + 42), (cx, 175), (back, 175), (back, mid + 34)])
    c.text((cx + back) / 2, 175 + 16, "no: fix the task, run again", LIGHT, GREY, anchor="mm")
    c.save(path)


def main():
    demo, out = Path(sys.argv[1]), Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    how_it_works(out / "how-it-works.png")
    receipt_chain(demo, out / "receipt-chain.png")
    self_test(demo, out / "self-test.png")
    publishing(out / "publishing.png")


if __name__ == "__main__":
    main()
