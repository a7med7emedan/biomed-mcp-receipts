"""Draw the GitHub social preview for biomed-mcp-receipts: grey and white, 1280 x 640.

Needs Pillow and the macOS system fonts. Run: python scripts/social_preview.py docs/social-preview.png
"""

import hashlib
import sys

from PIL import Image, ImageDraw, ImageFilter, ImageFont

S = 2  # draw at twice the size, then downsample for smooth edges
W, H = 1280 * S, 640 * S

BG = "#FAFAF9"
INK = "#1F2328"
GREY = "#57606A"
SOFT = "#8C959F"
LINE = "#D0D7DE"

HN = "/System/Library/Fonts/HelveticaNeue.ttc"
MONO = "/System/Library/Fonts/SFNSMono.ttf"


def font(path, size, index=0):
    return ImageFont.truetype(path, size * S, index=index)


title = font(HN, 58, 10)  # Medium
tagline = font(HN, 32, 7)  # Light
body = font(HN, 22, 7)
foot = font(MONO, 17)
mono = font(MONO, 15)
mono_small = font(MONO, 13)
head = font(HN, 15, 10)

img = Image.new("RGB", (W, H), BG)
d = ImageDraw.Draw(img)

# Left column: name, promise, three plain facts, link.
x = 80 * S
d.text((x, 150 * S), "biomed-mcp-receipts", font=title, fill=INK)
d.text((x, 228 * S), "Receipts for biomedical MCP tools.", font=tagline, fill=GREY)
d.line([(x, 300 * S), (x + 120 * S, 300 * S)], fill=LINE, width=2 * S)
facts = [
    "Checks each answer against PubMed and ClinicalTrials.gov.",
    "Scores seven dimensions, never one number.",
    "Keeps a hash-chained audit trail anyone can verify.",
]
for i, line in enumerate(facts):
    d.text((x, (330 + i * 38) * S), line, font=body, fill=GREY)
d.text((x, 540 * S), "github.com/a7med7emedan/biomed-mcp-receipts", font=foot, fill=SOFT)

# Right column: one receipt, drawn as a paper slip with a torn lower edge.
left, top, right, bottom = 870 * S, 105 * S, 1200 * S, 525 * S
tooth = 10 * S
edge = [(left, top), (right, top), (right, bottom)]
n = (right - left) // tooth
for k in range(n, -1, -1):
    edge.append((left + k * tooth, bottom + (tooth if k % 2 else 0)))
edge.append((left, top))

shadow = Image.new("L", (W, H), 0)
ImageDraw.Draw(shadow).polygon([(px + 4 * S, py + 6 * S) for px, py in edge], fill=60)
shadow = shadow.filter(ImageFilter.GaussianBlur(10 * S))
img.paste(Image.new("RGB", (W, H), "#C9CED4"), (0, 0), shadow)
d = ImageDraw.Draw(img)
d.polygon(edge, fill="#FFFFFF", outline=LINE)

px = left + 26 * S
y = top + 28 * S
d.text((px, y), "R E C E I P T", font=head, fill=INK)
y += 34 * S
rows = [("check", "trial-actt1"), ("capability", "trial.lookup"), ("source", "ClinicalTrials.gov")]
for k, v in rows:
    d.text((px, y), k, font=mono_small, fill=SOFT)
    d.text((px + 110 * S, y), v, font=mono_small, fill=GREY)
    y += 22 * S
y += 8 * S
d.line([(px, y), (right - 26 * S, y)], fill=LINE, width=S)
y += 16 * S
dims = ["conformance", "schema", "correctness", "freshness", "attribution", "robustness", "stability"]
for name in dims:
    d.text((px, y), name, font=mono, fill=GREY)
    w = d.textlength("scored", font=mono)
    d.text((right - 26 * S - w, y), "scored", font=mono, fill=SOFT)
    y += 27 * S
y += 6 * S
d.line([(px, y), (right - 26 * S, y)], fill=LINE, width=S)
y += 16 * S
digest = hashlib.sha256(b"biomed-mcp-receipts").hexdigest()
d.text((px, y), "chain", font=mono_small, fill=SOFT)
d.text((px + 110 * S, y), f"{digest[:8]}...{digest[-8:]}", font=mono_small, fill=GREY)
y += 22 * S
d.text((px, y), "verify", font=mono_small, fill=SOFT)
d.text((px + 110 * S, y), "bmr verify runs/<id>", font=mono_small, fill=GREY)

img = img.resize((W // S, H // S), Image.LANCZOS)
img.save(sys.argv[1], optimize=True)
print("saved", sys.argv[1], img.size)
