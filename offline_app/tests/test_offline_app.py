"""Basic tests for offline loot tracking."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from app.config.settings import AppConfig, _config_from_raw, normalize_loot_table_display_scale
from app.paths import app_dir, repo_root, validate_repo_layout
from app.core_adapter.loot_catalog import has_shiny_variant, is_equipment, normalize_item_name
from app.core_adapter.loot_service import add_loot, create_ppe, delete_ppe, remove_all_loot, remove_loot
from app.ui.main_window import _prepare_loot_table_image
from PIL import Image
from app.storage.models import LocalPlayerData
from app.storage.player_store import PlayerStore


class PathTests(unittest.TestCase):
    def test_app_dir_from_source(self) -> None:
        self.assertEqual(app_dir(), APP_ROOT)

    def test_repo_root_from_source(self) -> None:
        self.assertEqual(repo_root(), APP_ROOT.parent)

    def test_validate_repo_layout_in_checkout(self) -> None:
        self.assertEqual(validate_repo_layout(), [])

    def test_app_dir_when_frozen(self) -> None:
        exe_dir = APP_ROOT
        fake_exe = exe_dir / "RotMG-PPE-Offline.exe"
        original_frozen = getattr(sys, "frozen", None)
        original_executable = sys.executable
        try:
            sys.frozen = True  # type: ignore[attr-defined]
            sys.executable = str(fake_exe)
            self.assertEqual(app_dir(), exe_dir.resolve())
            self.assertEqual(repo_root(), exe_dir.resolve().parent)
        finally:
            if original_frozen is None:
                delattr(sys, "frozen")
            else:
                sys.frozen = original_frozen  # type: ignore[attr-defined]
            sys.executable = original_executable


class ConfigTests(unittest.TestCase):
    def test_loot_table_display_scale_default(self) -> None:
        config = _config_from_raw({})
        self.assertAlmostEqual(config.loot_table_display_scale, 0.75)

    def test_loot_table_display_scale_load(self) -> None:
        config = _config_from_raw({"loot_table_display_scale": 0.9})
        self.assertAlmostEqual(config.loot_table_display_scale, 0.9)

    def test_normalize_loot_table_display_scale(self) -> None:
        self.assertAlmostEqual(normalize_loot_table_display_scale(0.7), 0.7)
        self.assertAlmostEqual(normalize_loot_table_display_scale(2.0), 1.0)
        self.assertAlmostEqual(normalize_loot_table_display_scale(0.01), 0.05)


class CatalogTests(unittest.TestCase):
    def test_normalize_item_name(self) -> None:
        self.assertEqual(normalize_item_name("  Foo  Bar  "), "Foo Bar")

    def test_equipment_detection(self) -> None:
        self.assertTrue(is_equipment("Dagger of Dire Hatred"))
        self.assertTrue(is_equipment("Demon Blade"))
        self.assertTrue(is_equipment("Arcane Rapier"))
        self.assertFalse(is_equipment("Golden Nut"))
        self.assertFalse(is_equipment("Potion of Attack"))

    def test_shiny_variant_detection(self) -> None:
        self.assertTrue(has_shiny_variant("Demon Blade"))
        self.assertFalse(has_shiny_variant("Golden Nut"))

    def test_loot_label_display(self) -> None:
        from app.core_adapter.loot_service import format_loot_label, loot_label_display
        from app.storage.models import LocalLootEntry

        entry = LocalLootEntry(
            item_name="Demon Blade",
            quantity=2,
            shiny=True,
            rarity="rare",
            logged_times=[],
        )
        display = loot_label_display(entry)
        self.assertEqual(display.prefix, "Rare Shiny ")
        self.assertEqual(display.item_first, "D")
        self.assertEqual(display.item_rest, "emon Blade x2")
        self.assertEqual(format_loot_label(entry), "Rare Shiny Demon Blade x2")


class LootServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = AppConfig()
        self.player = LocalPlayerData.empty("Tester")

    def test_add_and_remove_loot(self) -> None:
        ppe = create_ppe(self.player, class_name="Wizard")
        add_loot(
            self.player,
            ppe_id=ppe.id,
            item_name="Dagger of Dire Hatred",
            shiny=False,
            rarity="divine",
            config=self.config,
        )
        self.assertEqual(len(ppe.loot), 1)
        self.assertEqual(ppe.loot[0].quantity, 1)
        self.assertGreater(ppe.points, 0)

        remove_loot(
            self.player,
            ppe_id=ppe.id,
            item_name="Dagger of Dire Hatred",
            shiny=False,
            rarity="divine",
            config=self.config,
        )
        self.assertEqual(len(ppe.loot), 0)
        self.assertEqual(ppe.points, 0.0)

    def test_remove_all_loot(self) -> None:
        ppe = create_ppe(self.player, class_name="Wizard")
        for _ in range(3):
            add_loot(
                self.player,
                ppe_id=ppe.id,
                item_name="Dagger of Dire Hatred",
                shiny=False,
                rarity="common",
                config=self.config,
            )
        self.assertEqual(ppe.loot[0].quantity, 3)

        result = remove_all_loot(
            self.player,
            ppe_id=ppe.id,
            item_name="Dagger of Dire Hatred",
            shiny=False,
            rarity="common",
            config=self.config,
        )
        self.assertEqual(result.removed_count, 3)
        self.assertEqual(len(ppe.loot), 0)

    def test_shiny_equipment_requires_rare_or_higher(self) -> None:
        ppe = create_ppe(self.player, class_name="Wizard")
        with self.assertRaises(ValueError):
            add_loot(
                self.player,
                ppe_id=ppe.id,
                item_name="Demon Blade",
                shiny=True,
                rarity="common",
                config=self.config,
            )

    def test_delete_ppe(self) -> None:
        first = create_ppe(self.player, class_name="Wizard")
        second = create_ppe(self.player, class_name="Archer")
        add_loot(
            self.player,
            ppe_id=first.id,
            item_name="Golden Nut",
            shiny=False,
            rarity="common",
            config=self.config,
        )

        deleted = delete_ppe(self.player, ppe_id=first.id)
        self.assertIsNotNone(deleted)
        assert deleted is not None
        self.assertEqual(deleted.id, first.id)
        self.assertEqual(len(self.player.ppes), 1)
        self.assertEqual(self.player.active_ppe_id, second.id)

        delete_ppe(self.player, ppe_id=second.id)
        self.assertEqual(len(self.player.ppes), 0)
        self.assertIsNone(self.player.active_ppe_id)


class LootTableImagePrepTests(unittest.TestCase):
    def test_shrinks_vertical_gray_margins(self) -> None:
        # Tall image: gray slab, colored band, gray slab (simulates empty grid rows).
        img = Image.new("RGBA", (100, 200), (43, 43, 43, 255))
        for x in range(100):
            for y in range(80, 120):
                img.putpixel((x, y), (200, 50, 50, 255))
        prepared = _prepare_loot_table_image(img)
        self.assertLess(prepared.height, 200)
        self.assertGreater(prepared.height, 40)


class PlayerStoreTests(unittest.TestCase):
    def test_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "player.json"
            store = PlayerStore(path)
            player = LocalPlayerData.empty("Tester")
            create_ppe(player, class_name="Archer")
            store.save(player)

            loaded = store.load(default_name="Tester")
            self.assertEqual(loaded.player_name, "Tester")
            self.assertEqual(len(loaded.ppes), 1)
            self.assertEqual(loaded.ppes[0].class_name, "Archer")

    def test_corrupt_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "player.json"
            path.write_text("{not json", encoding="utf-8")
            store = PlayerStore(path)
            with self.assertRaises(ValueError):
                store.load()


if __name__ == "__main__":
    unittest.main()
