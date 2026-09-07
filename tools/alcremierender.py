# -*- coding: utf-8 -*-
"""Render all 63 Alcremie forms and emit them as base64 for the wiki.

Replaces the earlier stand-in, which showed a motif cropped from the decoration atlas over a
colour sampled from the cream atlas. That conveyed colour and topping but was not a picture
of the Pokemon. These are real renders of the actual model.

Run locally (needs Pillow); paste the printed literal into build3.py, which builds on the
server where Pillow is not installed.

    python tools/alcremierender.py <cobblemon jar> [size]
"""
import base64
import importlib.util
import io
import os
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("mr", os.path.join(HERE, "mcrender.py"))
mr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mr)

JAR = sys.argv[1] if len(sys.argv) > 1 else "X:/claude-tmp/cm.jar"
SIZE = int(sys.argv[2]) if len(sys.argv) > 2 else 104
CREAMS = ["vanilla", "ruby", "ruby_swirl", "caramel_swirl", "matcha", "mint",
          "lemon", "salted", "rainbow_swirl"]
DECOS = ["strawberry", "berry", "love", "star", "clover", "flower", "ribbon"]

z = zipfile.ZipFile(JAR)
total = 0
print("_ALC_ART = {")
for d in DECOS:
    for c in CREAMS:
        im, _, _ = mr.draw(z, "alcremie", ["decoration-%s" % d, "cream-%s" % c],
                           size=SIZE, ss=2)
        im = im.crop(im.getbbox() or (0, 0, SIZE, SIZE))
        # Palette PNG with one reserved transparent index. The renders are flat-shaded
        # texels, so 255 colours is visually lossless and cuts the page weight by ~3x
        # against RGBA - worth it across 63 tiles.
        from PIL import Image as _I
        alpha = im.getchannel("A")
        q = im.convert("RGB").convert("P", palette=_I.ADAPTIVE, colors=255)
        # ADAPTIVE fills indices 0..254, so index 255 is not in the palette at all and
        # renders black rather than transparent. Extend it before using it as the key.
        pal = q.getpalette() or []
        pal = pal + [0] * (768 - len(pal))
        q.putpalette(pal)
        q.paste(255, mask=alpha.point(lambda a: 255 if a < 128 else 0))
        q.info["transparency"] = 255
        buf = io.BytesIO()
        q.save(buf, "PNG", optimize=True, transparency=255)
        b = base64.b64encode(buf.getvalue()).decode()
        total += len(b)
        print("    '%s|%s': '%s'," % (d, c, b))
        print("  %-11s %-14s %5d B" % (d, c, len(b)), file=sys.stderr)
print("}")
print("TOTAL %d tiles, %.0f KB of base64" % (len(DECOS) * len(CREAMS), total / 1024.0),
      file=sys.stderr)
