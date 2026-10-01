"""Site screenshots, step 2: raw PNGs from tools/site_shots.py -> site/assets/shots/[en/]<name>-<mode>.webp.

Run: python tools/site_shots_webp.py <raw_dir>     (needs Pillow)
"""
import os
import sys

from PIL import Image, ImageChops, ImageDraw

RAW = sys.argv[1]
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "site", "assets", "shots")
M, R = 30, 55
for base in ['mano', 'hp', 'wishlist', 'settings', 'guide']:
    for mode in ['light', 'dark']:
        for lang in ['he', 'en']:
            src = f'{RAW}/{base}-{mode}{"" if lang == "he" else "-en"}.png'
            dst = f'{OUT}/{"" if lang == "he" else "en/"}{base}-{mode}.webp'
            im = Image.open(src).convert('RGBA')
            w, h = im.size
            im = im.crop((M, M, w - M, h - M))
            mask = Image.new('L', im.size, 0)
            ImageDraw.Draw(mask).rounded_rectangle((0, 0, im.size[0] - 1, im.size[1] - 1), radius=R, fill=255)
            im.putalpha(ImageChops.multiply(im.split()[3], mask))
            im.save(dst, 'WEBP', quality=84, method=6)
            print(dst.split('shots/')[1], im.size, os.path.getsize(dst) // 1024, 'KB')
