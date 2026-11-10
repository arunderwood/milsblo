"""Prove each rule in check_design.py fails on a deliberate error.

Needs kicad-cli. A check that cannot fail proves nothing, so a missing kicad-cli
is an error here, not a skip.

Usage: python3 -m unittest discover -s tools
"""

import copy
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import check_design as cd

SCRIPT = pathlib.Path(cd.__file__).resolve()


def set_value(role, value):
    return lambda design: setattr(design.by_role(role), "value", value)


def set_pin(role, number, net):
    return lambda design: design.pin_net.__setitem__((design.by_role(role).ref, number), net)


def add_cc_pulldown(design):
    design.parts["R98"] = cd.Part("R98", "5.1kΩ ±1% 100mW", "test.r_cc")
    design.pin_net[("R98", "1")] = "CC1"
    design.pin_net[("R98", "2")] = "gnd"


def remove(role):
    def apply(design):
        ref = design.by_role(role).ref
        del design.parts[ref]
        design.pin_net = {k: v for k, v in design.pin_net.items() if k[0] != ref}

    return apply


MUTATIONS = [
    ("tach pullup wrong", "resistor values", set_value("fan1.r_tach", "330Ω ±1% 100mW")),
    ("LED resistor wrong", "resistor values", set_value("pd.r_led", "47Ω ±1% 100mW")),
    ("12 V capacitor under-rated", "12 V capacitor ratings", set_value("buck.c_in", "22µF ±10% 6.3V X5R")),
    ("fan on the wrong rail", "pin tables", set_pin("fan1.hdr", "2", "v5")),
    ("GPIO moved", "pin tables", set_pin("headers.j1", "4", "fan2_gpio_pwm")),
    ("FB off the output", "AP63205 feedback", set_pin("buck.buck", "1", "FB")),
    ("EN on PG", "AP63205 enable", set_pin("buck.buck", "2", "pg")),
    ("VBUS sense direct", "CH224K VBUS sense", set_pin("pd.ch224k", "8", "v12")),
    ("VBUS sense resistor wrong", "CH224K VBUS sense", set_value("pd.r_vbus", "100Ω ±1% 100mW")),
    ("BST capacitor wrong", "support parts", set_value("buck.c_bst", "22µF ±10% 25V X5R")),
    ("VDD bypass missing", "support parts", remove("pd.c_vdd")),
    ("VDD resistor overloaded", "CH224K VDD feed", set_value("pd.r_vdd", "470Ω ±1% 100mW")),
    ("VDD shunt overcurrent", "CH224K VDD feed", set_value("pd.r_vdd", "220Ω ±1% 1W")),
    ("CC pulldown added", "CH224K CC pins", add_cc_pulldown),
    ("CFG2 driven", "CH224K voltage selection", set_pin("pd.ch224k", "2", "v3v3")),
    ("LED cathode off PG", "CH224K PG LED", set_pin("pd.led_pg", "1", "gnd")),
    ("LED anode off its resistor", "CH224K PG LED", set_pin("pd.led_pg", "2", "v3v3")),
]


def failing(design):
    return {name for name, problems in cd.evaluate(design) if problems}


class DesignRules(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.kicad_cli = cd.find_kicad_cli(None)
        if cls.kicad_cli is None:
            raise RuntimeError("kicad-cli not found")
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        netlist = pathlib.Path(cls.tmp.name) / "design.net"
        cd.export_netlist(cls.kicad_cli, netlist)
        cls.netlist = netlist
        cls.design = cd.load_design(netlist)

    def test_committed_design_passes(self):
        self.assertEqual(failing(self.design), set())

    def test_each_rule_catches_its_error(self):
        for label, rule, mutate in MUTATIONS:
            with self.subTest(label):
                design = copy.deepcopy(self.design)
                mutate(design)
                self.assertEqual(failing(design), {rule})

    def test_left_open_enable_is_allowed(self):
        design = copy.deepcopy(self.design)
        set_pin("buck.buck", "2", "unconnected-(U1-EN-Pad2)")(design)
        self.assertEqual(failing(design), set())

    def test_golden_catches_swapped_nets(self):
        design = copy.deepcopy(self.design)
        design.pin_net[("R3", "2")], design.pin_net[("R5", "2")] = (
            design.pin_net[("R5", "2")],
            design.pin_net[("R3", "2")],
        )
        self.assertEqual(cd.check_golden(self.design, cd.GOLDEN), [])
        self.assertTrue(cd.check_golden(design, cd.GOLDEN))


class KicadChecks(unittest.TestCase):
    def setUp(self):
        self.kicad_cli = cd.find_kicad_cli(None)
        self.assertIsNotNone(self.kicad_cli, "kicad-cli not found")
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = pathlib.Path(tmp.name)
        self.project = self.tmp / "kicad"
        shutil.copytree(cd.SCHEMATIC.parent, self.project, ignore=shutil.ignore_patterns(".history", "~*"))
        self.schematic = self.project / cd.SCHEMATIC.name
        self.board = self.project / cd.BOARD.name

    def failures(self):
        with mock.patch.object(cd, "SCHEMATIC", self.schematic), mock.patch.object(cd, "BOARD", self.board):
            return {name for name, problems in cd.kicad_checks(self.kicad_cli, self.tmp) if problems}

    def test_clean_copy_passes(self):
        self.assertEqual(self.failures(), set())

    def test_parity_catches_a_wrong_pad_net(self):
        text = self.board.read_text(encoding="utf-8")
        self.assertIn('(net "/sda")', text)
        self.board.write_text(text.replace('(net "/sda")', '(net "/scl")', 1), encoding="utf-8")
        self.assertEqual(self.failures(), {"schematic parity"})

    def test_erc_catches_a_missing_label(self):
        text = self.schematic.read_text(encoding="utf-8")
        start = text.index('(label "CFG1"')
        depth, end = 0, start
        while True:
            depth += (text[end] == "(") - (text[end] == ")")
            end += 1
            if depth == 0:
                break
        self.schematic.write_text(text[:start] + text[end:], encoding="utf-8")
        self.assertIn("ERC", self.failures())


class ExitCodes(unittest.TestCase):
    def run_script(self, *args):
        return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True).returncode

    def test_missing_kicad_cli_is_not_a_rule_failure(self):
        self.assertEqual(self.run_script("--kicad-cli", "/nonexistent"), 2)

    def test_truncated_netlist_is_not_a_rule_failure(self):
        with tempfile.NamedTemporaryFile("w", suffix=".net", encoding="utf-8") as bad:
            bad.write("(export (version")
            bad.flush()
            self.assertEqual(self.run_script("--netlist", bad.name), 2)


if __name__ == "__main__":
    unittest.main()
