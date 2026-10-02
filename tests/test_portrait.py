"""The portrait comes from the player's name tag found in the pixels, not from the AI's rough box alone."""
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from maplehelper.portrait import find_name_tags, portrait_rect


def _scene() -> np.ndarray:
    """A grassy scene with a translucent name tag (the plate darkens what's behind it) and white letters."""
    w, h = 1200, 700
    x = np.linspace(0, 1, w)[None, :, None]
    y = np.linspace(0, 1, h)[:, None, None]
    img = (np.concatenate([150 + 60 * x + 0 * y, 200 + 40 * y + 0 * x, 100 + 30 * x * y], axis=2)).astype(np.uint8)
    img[600:700] = (120, 120, 120)                       # stone ground
    img[300:340, 690:740] = (200, 40, 40)                 # the character's cap...
    img[340:398, 690:740] = (60, 60, 160)                 # ...and body, standing on the tag
    plate = (slice(400, 426), slice(650, 770))
    img[plate] = (img[plate] * 0.42).astype(np.uint8)
    pil = Image.fromarray(img)
    ImageDraw.Draw(pil).text((658, 402), "KalimeroZz", fill=(255, 255, 255), font=ImageFont.load_default(size=20))
    return np.asarray(pil)


def test_finds_the_translucent_name_tag():
    tags = find_name_tags(_scene())
    assert len(tags) == 1
    x, y, w, h = tags[0]
    assert abs(x - 650) <= 3 and abs(y - 400) <= 2 and abs(w - 120) <= 6 and abs(h - 26) <= 2


def test_portrait_sits_on_the_tag_even_with_an_off_box():
    img = _scene()
    H, W = img.shape[:2]
    off_box = [600 / W, 250 / H, 60 / W, 90 / H]          # the AI pointed next to the character
    left, top, right, bottom = portrait_rect(img, off_box)
    assert left < 690 and right > 740 and top < 300 and 398 <= bottom <= 410
    assert portrait_rect(img, None) == (left, top, right, bottom)    # one tag in sight: no box needed


def test_no_tag_no_guess():
    img = np.full((500, 800, 3), 180, np.uint8)
    assert portrait_rect(img, [0.4, 0.4, 0.05, 0.1]) is None and portrait_rect(img, None) is None
