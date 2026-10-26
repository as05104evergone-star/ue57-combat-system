"""消费侧扫描回归测试；不读取或修改工程资产。"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import verify_mapping as mapping


class ConsumerCoverageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.patch_root = patch.object(mapping, "T3D_DIR", str(self.root))
        self.patch_root.start()
        self.addCleanup(self.patch_root.stop)
        self.patch_csv = patch.object(mapping, "load_csv", return_value={"rows": [
            {"Key": "combat.enemy.hitstun_large"},
            {"Key": "combat.enemy.hitstun_large_threshold"},
            {"Key": "combat.dmg.light1"},
        ]})
        self.patch_csv.start()
        self.addCleanup(self.patch_csv.stop)
        mapping.FAILS.clear()
        self.addCleanup(mapping.FAILS.clear)
        # Explicit expected fixtures prevent the test from hiding a missing scanner entry.
        self.combat = "_Game_Combo_Demo_BP_Components_AC_Combat.t3d"
        self.npc = "_Game_Combo_Demo_BP_Components_AC_NPC.t3d"
        self.actor = "_Game_Combo_Demo_BP_Actors_BP_MasterNPC.t3d"
        for name in (self.combat, self.npc, self.actor):
            (self.root / name).write_text("", encoding="utf-8")

    def test_npc_keys_are_found(self):
        (self.root / self.npc).write_text(
            'PinName="Key",DefaultValue="combat.enemy.hitstun_large"\n'
            'PinName="Key",DefaultValue="combat.enemy.hitstun_large_threshold"\n'
            'PinName="DataTable",DefaultObject="/Game/Combo_Demo/BP/DataTables/DT_Combat.DT_Combat"',
            encoding="utf-8")
        result = mapping.check_consumer_keys()
        self.assertEqual(result["literals"][self.npc], [
            "combat.enemy.hitstun_large", "combat.enemy.hitstun_large_threshold"])
        self.assertIn("/Game/Combo_Demo/BP/DataTables/DT_Combat", result["tables_read"][self.npc])
        self.assertEqual(result["dangling"], [])

    def test_npc_unknown_key_is_reported(self):
        (self.root / self.npc).write_text(
            'DefaultValue="combat.enemy.missing"', encoding="utf-8")
        result = mapping.check_consumer_keys()
        self.assertEqual(result["dangling"], [{"bp": self.npc, "key": "combat.enemy.missing"}])

    def test_missing_npc_cache_cannot_silently_pass(self):
        (self.root / self.npc).unlink()
        mapping.check_consumer_keys()
        self.assertTrue(any(f["check"] == "consumer/T3D" and self.npc in f["detail"]
                            for f in mapping.FAILS))

    def test_existing_dynamic_attack_key_still_works(self):
        (self.root / self.combat).write_text(
            'MemberName="Concat_StrStr"\nPinName="A",DefaultValue="combat.dmg.light"',
            encoding="utf-8")
        result = mapping.check_consumer_keys()
        self.assertEqual(result["dangling"], [])
        self.assertEqual(result["dynamic"][0]["candidates"], ["combat.dmg.light1"])


if __name__ == "__main__":
    unittest.main()
