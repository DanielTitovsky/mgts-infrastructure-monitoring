from __future__ import annotations

import pickletools
import unittest
import zipfile
from pathlib import Path

from app.services.cv_logic import CLASS_RULES


CHECKPOINT = Path(__file__).resolve().parents[2] / "cv" / "ml" / "yolo-v" / "2-version.pt"
EXPECTED_CLASSES = {
    "Broken",
    "Good",
    "Lose",
    "Uncovered",
    "concrete pole",
    "cutout",
    "double crossarm",
    "insulator",
    "lightning arrester",
    "single crossarm",
    "splice case",
    "steel pole",
    "street light",
    "transformer",
    "wood pole",
}


def checkpoint_class_names(path: Path) -> set[str]:
    """Read checkpoint class metadata without unpickling model data."""
    with zipfile.ZipFile(path) as archive:
        operations = list(pickletools.genops(archive.read("best/data.pkl")))

    for index, (opcode, argument, _) in enumerate(operations):
        if opcode.name not in {"BINUNICODE", "SHORT_BINUNICODE"} or argument != "names":
            continue

        names: dict[int, str] = {}
        for current, (item_opcode, item_argument, _) in enumerate(
            operations[index + 1 :], start=index + 1
        ):
            if item_opcode.name == "SETITEMS":
                return set(names.values())
            if item_opcode.name not in {"BININT", "BININT1", "BININT2", "LONG"}:
                continue
            if current + 1 >= len(operations):
                break
            next_opcode, next_argument, _ = operations[current + 1]
            if next_opcode.name in {"BINUNICODE", "SHORT_BINUNICODE"}:
                names[int(item_argument)] = str(next_argument)

    raise AssertionError("Checkpoint does not contain a readable model.names mapping")


class WorkerCheckpointTests(unittest.TestCase):
    def test_dokploy_checkpoint_classes_match_existing_rules(self) -> None:
        names = checkpoint_class_names(CHECKPOINT)

        self.assertEqual(names, EXPECTED_CLASSES)
        self.assertNotIn("odn_pole", names)
        self.assertTrue(names.issubset(CLASS_RULES))


if __name__ == "__main__":
    unittest.main()
