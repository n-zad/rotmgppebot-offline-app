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
from app.core_adapter.loot_catalog import (
    has_shiny_variant,
    is_equipment,
    is_shiny_only_item,
    normalize_item_name,
    required_rarity,
    supports_rarity_tiers,
)
from app.core_adapter.loot_service import add_loot, create_ppe, delete_ppe, remove_all_loot, remove_loot
from app.core_adapter.loot_renderer import SpriteCell, build_sprite_hit_index, entry_sprite_lookup_key
from app.ui.loot_table_hover import build_tooltip_text, compute_tooltip_position
from app.ui.main_window import _prepare_loot_table_image, prepare_loot_table_image
from app.storage.models import LocalLootEntry, LocalPPE, LocalPlayerData
from PIL import Image
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

    def test_loot_table_hover_enabled_load(self) -> None:
        config = _config_from_raw({"loot_table_hover_enabled": False})
        self.assertFalse(config.loot_table_hover_enabled)
        default = _config_from_raw({})
        self.assertTrue(default.loot_table_hover_enabled)

    def test_loot_table_hover_condensed_load(self) -> None:
        config = _config_from_raw({"loot_table_hover_condensed": True})
        self.assertTrue(config.loot_table_hover_condensed)
        default = _config_from_raw({})
        self.assertFalse(default.loot_table_hover_condensed)


class CatalogTests(unittest.TestCase):
    def test_normalize_item_name(self) -> None:
        self.assertEqual(normalize_item_name("  Foo  Bar  "), "Foo Bar")

    def test_equipment_detection(self) -> None:
        self.assertTrue(is_equipment("Dagger of Dire Hatred"))
        self.assertTrue(is_equipment("Demon Blade"))
        self.assertTrue(is_equipment("Arcane Rapier"))
        self.assertTrue(is_equipment("Predator Bow"))
        self.assertTrue(is_equipment("Aegis Armor"))
        self.assertTrue(is_equipment("Mayhem Medallion"))
        self.assertTrue(is_equipment("Kendo Stick"))
        self.assertFalse(is_equipment("Golden Nut"))
        self.assertFalse(is_equipment("Potion of Attack"))
        self.assertFalse(is_equipment("Bunny Trickster Skin"))
        self.assertFalse(is_equipment("Moon Bunny Pet Skin"))
        self.assertFalse(is_equipment("Kogbold Enhancement Core"))
        self.assertFalse(is_equipment("Master Fishing Rod"))

    def test_edge_case_rarity_rules(self) -> None:
        self.assertFalse(supports_rarity_tiers("Kogbold Enhancement Core"))
        self.assertFalse(supports_rarity_tiers("Master Fishing Rod"))
        self.assertTrue(supports_rarity_tiers("Kendo Stick"))
        self.assertEqual(required_rarity("Nightmatter Circlet", shiny=False), "divine")
        self.assertEqual(required_rarity("Kendo Stick", shiny=True), "divine")
        self.assertEqual(required_rarity("Jewel Eye Katana", shiny=True), "divine")
        self.assertIsNone(required_rarity("Kendo Stick", shiny=False))

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

    def test_duplicate_items_use_reduced_points(self) -> None:
        ppe = create_ppe(self.player, class_name="Wizard")
        add_loot(
            self.player,
            ppe_id=ppe.id,
            item_name="Dagger of Dire Hatred",
            shiny=False,
            rarity="common",
            config=self.config,
        )
        first_total = ppe.points
        self.assertGreater(first_total, 0)

        add_loot(
            self.player,
            ppe_id=ppe.id,
            item_name="Dagger of Dire Hatred",
            shiny=False,
            rarity="common",
            config=self.config,
        )
        duplicate_total = ppe.points
        self.assertGreater(duplicate_total, first_total)
        self.assertLess(duplicate_total, first_total * 2)

    def test_kendo_stick_accepts_rarity(self) -> None:
        ppe = create_ppe(self.player, class_name="Samurai")
        result = add_loot(
            self.player,
            ppe_id=ppe.id,
            item_name="Kendo Stick",
            shiny=False,
            rarity="rare",
            config=self.config,
        )
        self.assertEqual(result.rarity, "rare")

    def test_kendo_stick_shiny_requires_divine(self) -> None:
        ppe = create_ppe(self.player, class_name="Samurai")
        with self.assertRaises(ValueError):
            add_loot(
                self.player,
                ppe_id=ppe.id,
                item_name="Kendo Stick",
                shiny=True,
                rarity="rare",
                config=self.config,
            )
        result = add_loot(
            self.player,
            ppe_id=ppe.id,
            item_name="Kendo Stick",
            shiny=True,
            rarity="divine",
            config=self.config,
        )
        self.assertEqual(result.rarity, "divine")

    def test_jewel_eye_katana_shiny_only_divine(self) -> None:
        ppe = create_ppe(self.player, class_name="Samurai")
        result = add_loot(
            self.player,
            ppe_id=ppe.id,
            item_name="Jewel Eye Katana",
            shiny=True,
            rarity="divine",
            config=self.config,
        )
        self.assertEqual(result.rarity, "divine")

    def test_kogbold_core_common_only_even_shiny(self) -> None:
        ppe = create_ppe(self.player, class_name="Wizard")
        with self.assertRaises(ValueError):
            add_loot(
                self.player,
                ppe_id=ppe.id,
                item_name="Kogbold Enhancement Core",
                shiny=True,
                rarity="rare",
                config=self.config,
            )

    def test_limited_equipment_accepts_rarity(self) -> None:
        ppe = create_ppe(self.player, class_name="Archer")
        result = add_loot(
            self.player,
            ppe_id=ppe.id,
            item_name="Predator Bow",
            shiny=False,
            rarity="legendary",
            config=self.config,
        )
        self.assertEqual(result.rarity, "legendary")
        self.assertEqual(ppe.loot[0].item_name, "Predator Bow")

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

    def test_prepare_loot_table_image_tracks_crop_offset(self) -> None:
        img = Image.new("RGBA", (120, 120), (0, 0, 0, 0))
        for x in range(40):
            for y in range(40):
                img.putpixel((x + 20, y + 20), (200, 50, 50, 255))
        prepared, offset = prepare_loot_table_image(img)
        self.assertGreater(offset[0], 0)
        self.assertGreater(offset[1], 0)
        self.assertLess(prepared.width, img.width)


class LootTableHoverTests(unittest.TestCase):
    def test_sprite_hit_index_lookup(self) -> None:
        index = build_sprite_hit_index()
        cell = index.lookup(5, 5, crop_offset=(0, 0))
        self.assertIsNotNone(cell)
        assert cell is not None
        self.assertEqual(cell.pixel_x, 0)
        self.assertEqual(cell.pixel_y, 0)
        self.assertIn("Dagger", cell.item_name)

    def test_sprite_hit_index_respects_crop_offset(self) -> None:
        index = build_sprite_hit_index()
        at_origin = index.lookup(5, 5, crop_offset=(0, 0))
        shifted = index.lookup(5, 5, crop_offset=(40, 40))
        self.assertIsNotNone(at_origin)
        self.assertIsNotNone(shifted)
        assert at_origin is not None and shifted is not None
        self.assertEqual(at_origin.pixel_x, 0)
        self.assertEqual(shifted.pixel_x, 40)

    def test_entry_sprite_lookup_key(self) -> None:
        self.assertEqual(
            entry_sprite_lookup_key("Demon Blade", shiny=True),
            entry_sprite_lookup_key("Demon Blade", shiny=False) + " (shiny)",
        )

    def test_compute_tooltip_position_flips_near_bottom(self) -> None:
        bounds = (0, 0, 1920, 1080)
        width, height = 280, 200
        x, y = compute_tooltip_position(
            x_root=500,
            y_root=1000,
            width=width,
            height=height,
            bounds=bounds,
        )
        self.assertLess(y + height, bounds[3])
        self.assertGreaterEqual(y, bounds[1])

    def test_compute_tooltip_position_clamps_oversized_height(self) -> None:
        bounds = (0, 0, 800, 600)
        x, y = compute_tooltip_position(
            x_root=100,
            y_root=550,
            width=200,
            height=500,
            bounds=bounds,
        )
        self.assertGreaterEqual(y, bounds[1])
        self.assertLessEqual(y + 500, bounds[3])

    def test_build_tooltip_text_logged_and_unlogged(self) -> None:
        config = AppConfig()
        cell = SpriteCell(
            item_name="Dagger of Dire Hatred",
            lookup_key=entry_sprite_lookup_key("Dagger of Dire Hatred", shiny=False),
            pixel_x=0,
            pixel_y=0,
        )
        _, unlogged = build_tooltip_text(cell, [], config=config)
        self.assertIn("Not logged", "\n".join(unlogged))

        entry = LocalLootEntry(
            item_name="Dagger of Dire Hatred",
            quantity=2,
            shiny=False,
            rarity="divine",
            logged_times=[1_700_000_000, 1_700_000_100],
        )
        ppe = LocalPPE(id=1, class_name="Wizard", loot=[entry])
        title, logged = build_tooltip_text(cell, [entry], config=config, ppe=ppe)
        self.assertEqual(title, "Dagger of Dire Hatred")
        body = "\n".join(logged)
        self.assertIn("#1:", body)
        self.assertIn("#2:", body)
        self.assertIn("Subtotal:", body)

    def test_build_tooltip_text_condensed(self) -> None:
        config = AppConfig()
        cell = SpriteCell(
            item_name="Dagger of Dire Hatred",
            lookup_key=entry_sprite_lookup_key("Dagger of Dire Hatred", shiny=False),
            pixel_x=0,
            pixel_y=0,
        )
        entry = LocalLootEntry(
            item_name="Dagger of Dire Hatred",
            quantity=2,
            shiny=False,
            rarity="divine",
            logged_times=[1_700_000_000, 1_700_000_100],
        )
        ppe = LocalPPE(id=1, class_name="Wizard", loot=[entry])
        _, condensed = build_tooltip_text(cell, [entry], config=config, condensed=True, ppe=ppe)
        body = "\n".join(condensed)
        self.assertIn("(+", body)
        self.assertNotIn("#1:", body)
        self.assertNotIn("Subtotal:", body)


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

    def test_active_ppe_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "player.json"
            store = PlayerStore(path)
            player = LocalPlayerData.empty("Tester")
            first = create_ppe(player, class_name="Wizard")
            second = create_ppe(player, class_name="Archer")
            player.active_ppe_id = first.id
            store.save(player)

            loaded = store.load(default_name="Tester")
            self.assertEqual(loaded.active_ppe_id, first.id)
            self.assertEqual(loaded.active_ppe().id, first.id)

            player.active_ppe_id = second.id
            store.save(player)
            reloaded = store.load(default_name="Tester")
            self.assertEqual(reloaded.active_ppe_id, second.id)
            self.assertEqual(reloaded.active_ppe().class_name, "Archer")

    def test_corrupt_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "player.json"
            path.write_text("{not json", encoding="utf-8")
            store = PlayerStore(path)
            with self.assertRaises(ValueError):
                store.load()


if __name__ == "__main__":
    unittest.main()
