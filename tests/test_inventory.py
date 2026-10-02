"""The inventory is read from the pixels: slots found on a grid, icons matched to the database's pictures."""
import numpy as np
from PIL import Image, ImageDraw

from maplehelper import inventory


class _KB:
    """Two item pictures on disk, like the knowledge base's."""
    def __init__(self, tmp_path):
        self.root = tmp_path
        self.entities, self._paths = {}, {}
        for i, color in enumerate([(200, 40, 40), (40, 160, 60)]):
            im = Image.new("RGBA", (30, 29), (0, 0, 0, 0))
            d = ImageDraw.Draw(im)
            d.ellipse((4, 3, 26, 25), fill=color + (255,), outline=(0, 0, 0, 255))
            d.rectangle((12, 10, 18 + 4 * i, 14 + 6 * i), fill=(250, 250, 250, 255))
            p = tmp_path / f"{i}.png"
            im.save(p)
            k = f"item/{i}"
            self.entities[k] = {"category": "item", "name": f"Thing {i}"}
            self._paths[k] = p

    def image_path(self, k):
        return self._paths.get(k)

    def get(self, k):
        return self.entities.get(k)


def test_slots_and_the_icon_are_found(tmp_path):
    kb = _KB(tmp_path)
    icon = Image.open(kb.image_path("item/1")).convert("RGBA")
    img = Image.new("RGB", (600, 400), (40, 90, 160))
    for r in range(3):
        for c in range(4):
            x, y = 50 + c * 96, 40 + r * 96
            img.paste((224, 222, 212), (x, y, x + 83, y + 83))
    big = icon.resize((60, 58), Image.NEAREST)
    img.paste(big, (50 + 96 + 11, 40 + 12), big)
    assert len(inventory.find_slots(np.asarray(img))) == 12
    slots = inventory.read(img, kb)
    assert [s.index for s in slots] == [2] and slots[0].matches[0][0] == "item/1"
    assert "Thing 1" in inventory.describe(slots, kb)
