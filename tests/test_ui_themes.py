import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import ui_themes as themes


def luminance(hex_color):
    rgb = [int(hex_color[i:i+2],16)/255 for i in (1,3,5)]
    rgb = [c/12.92 if c <= .04045 else ((c+.055)/1.055)**2.4 for c in rgb]
    return sum(c*w for c,w in zip(rgb,(.2126,.7152,.0722)))


class UIThemeTests(unittest.TestCase):
    def test_text_and_buttons_remain_legible_in_every_theme(self):
        for key, p in themes.THEMES.items():
            for foreground, background in [('fg','card'),('muted','card'),('fg','input'),
                                           ('fg','prompt'),('on_accent','accent'),('on_accent','active')]:
                values = sorted([luminance(p[foreground]),luminance(p[background])])
                self.assertGreaterEqual((values[1]+.05)/(values[0]+.05),4.5,(key,foreground,background))

    def test_persistence_contains_only_appearance_and_round_trips(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'ui.json'
            for key in themes.THEMES:
                self.assertTrue(themes.save_theme(key,path))
                self.assertEqual(themes.load_theme(path),key)
                self.assertEqual(json.loads(path.read_text(encoding='utf-8')),{'theme':key})
            self.assertEqual(list(Path(folder).glob('.ui_theme_*')),[])

    def test_missing_corrupt_or_unknown_preference_uses_light(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'ui.json'
            self.assertEqual(themes.load_theme(path),'light')
            for content in ['{broken','[]','null','{"theme":"unknown"}','{"theme":[]}']:
                path.write_text(content,encoding='utf-8')
                self.assertEqual(themes.load_theme(path),'light')

    def test_write_failure_preserves_previous_preference(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'ui.json'
            themes.save_theme('warm',path)
            with patch.object(themes.os,'replace',side_effect=PermissionError('read only')):
                self.assertFalse(themes.save_theme('dark',path))
            self.assertEqual(themes.load_theme(path),'warm')
            self.assertEqual(list(Path(folder).glob('.ui_theme_*')),[])

    def test_unknown_theme_does_not_write_preferences(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'ui.json'
            with self.assertRaises(ValueError):
                themes.save_theme('missing',path)
            self.assertFalse(path.exists())
