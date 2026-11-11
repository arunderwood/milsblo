"""Prove each rule in check_design.py fails on a deliberate error.

Needs kicad-cli. A check that cannot fail proves nothing, so a missing kicad-cli
is an error here, not a skip.

Usage: python3 -m unittest discover -s tools
"""

import copy
import pathlib
import re
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


def add_load_before_q1(design):
    design.parts["C98"] = cd.Part("C98", "100nF ±10% 50V X7R", "test.c_vin")
    design.pin_net[("C98", "1")] = "vin"
    design.pin_net[("C98", "2")] = "gnd"


def remove(role):
    def apply(design):
        ref = design.by_role(role).ref
        del design.parts[ref]
        design.pin_net = {k: v for k, v in design.pin_net.items() if k[0] != ref}

    return apply


MUTATIONS = [
    ("tach pullup wrong", "resistor values", set_value("fan1.r_tach", "330Ω ±1% 100mW")),
    ("LED resistor wrong", "resistor values", set_value("pwr.r_led", "10kΩ ±1% 100mW")),
    ("12 V capacitor under-rated", "12 V capacitor ratings", set_value("buck.c_in", "22µF ±10% 6.3V X5R")),
    ("fan on the wrong rail", "pin tables", set_pin("fan1.hdr", "2", "v5")),
    ("GPIO moved", "pin tables", set_pin("headers.j1", "4", "fan2_gpio_pwm")),
    ("FB off the output", "AP63205 feedback", set_pin("buck.buck", "1", "FB")),
    ("EN on PG", "AP63205 enable", set_pin("buck.buck", "2", "pg")),
    ("BST capacitor wrong", "support parts", set_value("buck.c_bst", "22µF ±10% 25V X5R")),
    ("12 V bypass missing", "support parts", remove("pwr.c_bypass")),
    ("second output capacitor missing", "support parts", remove("buck.c_out2")),
    ("jack wired straight to the rail", {"pin tables", "reverse-polarity protection"}, set_pin("pwr.jack", "2", "v12")),
    ("load ahead of Q1", "reverse-polarity protection", add_load_before_q1),
    ("Q1 source and drain swapped", {"pin tables", "reverse-polarity protection"}, lambda d: (set_pin("pwr.q_rev", "2", "vin")(d), set_pin("pwr.q_rev", "3", "v12")(d))),
    ("Q1 gate floating", "pin tables", set_pin("pwr.q_rev", "1", "unconnected-(Q1-G-Pad1)")),
    ("jack sleeve off ground", "pin tables", set_pin("pwr.jack", "4", "v12")),
    ("LED cathode off ground", "power LED", set_pin("pwr.led", "1", "v5")),
    ("LED anode off its resistor", "power LED", set_pin("pwr.led", "2", "v3v3")),
    ("LED resistor too small", {"power LED", "resistor values"}, set_value("pwr.r_led", "470Ω ±1% 100mW")),
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
                self.assertEqual(failing(design), rule if isinstance(rule, set) else {rule})

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


def move(ref, dx, dy):
    def apply(layout):
        footprint = layout.footprints[ref]
        footprint.at = (footprint.at[0] + dx, footprint.at[1] + dy)
        footprint.pads = {n: (x + dx, y + dy) for n, (x, y) in footprint.pads.items()}

    return apply


def thin_track(net):
    def apply(layout):
        next(t for t in layout.tracks if t.net == net).width = 0.2

    return apply


def pour_into_keepout(layout):
    layout.zones[0].filled.append((layout.edge[0] + 1.0, layout.edge[1] + 1.0))


def track_in_keepout(layout):
    layout.tracks[0].start = (layout.edge[0] + 12.0, layout.edge[1] + 1.0)


def via_in_keepout(layout):
    layout.vias[0].at = (layout.edge[0] + 12.0, layout.edge[1] + 1.0)


def extend_under_antenna(layout):
    x0, y0, x1, y1 = layout.edge
    layout.edge = (x0, y0 - 2.0, x1, y1)


def add_v12_zone(layout):
    layout.zones.append(cd.Zone("v12", "F.Cu", "extra", []))


def jack_on_top(layout):
    layout.footprints["DC1"].layer = "F.Cu"


def remove_ground_pour(layer):
    def apply(layout):
        layout.zones = [z for z in layout.zones if not (z.net == "gnd" and z.layer == layer)]

    return apply


def strip_ground_vias(layout):
    layout.vias = [v for v in layout.vias if v.net != "gnd"]


LAYOUT_MUTATIONS = [
    ("12 V track too thin", "rail track widths", thin_track("v12")),
    ("5 V track too thin", "rail track widths", thin_track("v5")),
    ("12 V in a zone", "rail zones", add_v12_zone),
    ("jack track too thin", "rail track widths", thin_track("vin")),
    ("jack on the top side", "jack on the back", jack_on_top),
    ("pour under the antenna", "antenna keepout", pour_into_keepout),
    ("signal under the antenna", "antenna keepout", track_in_keepout),
    ("via under the antenna", "antenna keepout", via_in_keepout),
    ("board under the antenna", "antenna keepout", extend_under_antenna),
    ("jack off the edge", "connectors on edges", move("DC1", 0.0, -2.0)),
    ("sensor connector off the edge", "connectors on edges", move("CN1", 0.0, -1.0)),
    ("fan 1 off the edge", "connectors on edges", move("H1", 2.0, 0.0)),
    ("fan 2 off the edge", "connectors on edges", move("H2", -1.0, 0.0)),
    ("header row moved", "DevKit header geometry", move("J2", 0.2, 0.0)),
    ("header row offset", "DevKit header geometry", move("J2", 0.0, 0.2)),
    ("regulator bypass moved away", "decoupling distance", move("C2", 6.0, 0.0)),
    ("no top pour", "ground pours and stitching", remove_ground_pour("F.Cu")),
    ("no bottom pour", "ground pours and stitching", remove_ground_pour("B.Cu")),
    ("no stitching vias", "ground pours and stitching", strip_ground_vias),
]


class LayoutRules(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.layout = cd.load_layout(cd.BOARD)

    def failing(self, layout):
        return {name for name, problems in cd.evaluate_layout(layout) if problems}

    def test_committed_layout_passes(self):
        self.assertEqual(self.failing(self.layout), set())

    def test_each_rule_catches_its_error(self):
        for label, rule, mutate in LAYOUT_MUTATIONS:
            with self.subTest(label):
                layout = copy.deepcopy(self.layout)
                mutate(layout)
                self.assertEqual(self.failing(layout), {rule})


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
        self.assertIn("schematic parity", self.failures())

    def test_drc_catches_a_missing_track(self):
        text = self.board.read_text(encoding="utf-8")
        # fan1_pwm is a single run of track, so losing any piece opens the net.
        start = re.search(r'\(segment(?:\s+\((?:start|end|width|layer) [^)]*\))+\s+\(net "/fan1_pwm"\)', text).start()
        depth, end = 0, start
        while True:
            depth += (text[end] == "(") - (text[end] == ")")
            end += 1
            if depth == 0:
                break
        self.board.write_text(text[:start] + text[end:], encoding="utf-8")
        self.assertEqual(self.failures(), {"board DRC"})

    def test_drc_catches_a_thin_rail(self):
        text = self.board.read_text(encoding="utf-8")
        self.board.write_text(text.replace("(width 1.016)", "(width 0.3)", 1), encoding="utf-8")
        self.assertIn("board DRC", self.failures())

    def test_erc_catches_a_missing_label(self):
        text = self.schematic.read_text(encoding="utf-8")
        start = text.index('(label "vin"')
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
