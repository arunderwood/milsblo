#!/usr/bin/env python3
"""Check the electrical rules for milsblo that KiCad's ERC cannot see.

ERC proves pin types agree. It cannot know that a resistor must be 24 kOhm or
that a fixed-output regulator's FB pin belongs on the output. These rules come
from the part datasheets:

  AP63205: Diodes Inc. DS41326 Rev. 3-2
  CH224A:  WCH CH224 manual 1, V2.1

With kicad-cli available it also gates on ERC and schematic-to-board parity, so
this one command is the whole design check, locally and in CI.

Usage: check_design.py [--netlist FILE] [--kicad-cli PATH] [--update-golden]
Exit codes: 0 all rules pass, 1 a rule failed, 2 the check could not run.
"""

import argparse
import dataclasses
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCHEMATIC = ROOT / "elec/kicad/milsblo.kicad_sch"
BOARD = ROOT / "elec/kicad/milsblo.kicad_pcb"
GOLDEN = ROOT / "elec/kicad/connectivity.golden"
MACOS_KICAD_CLI = "/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli"

V12 = 12.0
CH224A_VHV_MAX_V = 32.0
LED_RESISTOR_MIN_OHMS = 2.2e3
V12_CAP_MIN_RATING = 25.0

RESISTORS = {
    "pd.r_cfg1": 24e3,
    "pd.r_led": 4.7e3,
    "fan1.r_pwm": 100,
    "fan1.r_tach": 10e3,
    "fan2.r_pwm": 100,
    "fan2.r_tach": 10e3,
    "sensor.r_scl": 4.7e3,
    "sensor.r_sda": 4.7e3,
}

# J1 pin numbers are the ESP32-S3-DevKitC-1 left header: pin 4 is GPIO4, pin 12
# is GPIO8, pin 15 is GPIO9.
PIN_TABLES = {
    "pd.ch224a": {
        "1": "ch224a_vhv", "4": "DP", "5": "DM", "6": "CC2", "7": "CC1",
        "9": "CFG1", "11": "gnd",
    },
    "buck.buck": {"3": "v12", "4": "gnd", "5": "SW", "6": "BST"},
    "fan1.hdr": {"1": "gnd", "2": "v12", "3": "fan1_tach", "4": "fan1_pwm"},
    "fan2.hdr": {"1": "gnd", "2": "v12", "3": "fan2_tach", "4": "fan2_pwm"},
    "sensor.conn": {"1": "gnd", "2": "v3v3", "3": "sda", "4": "scl"},
    "headers.j1": {
        "1": "v3v3", "2": "v3v3", "4": "fan1_gpio_pwm", "5": "fan2_gpio_pwm",
        "6": "fan1_tach", "7": "fan2_tach", "12": "sda", "15": "scl",
        "21": "v5", "22": "gnd",
    },
    "headers.j3": {"1": "gnd", "22": "gnd"},
}


@dataclasses.dataclass
class Part:
    ref: str
    value: str
    role: str


@dataclasses.dataclass
class Design:
    parts: dict
    pin_net: dict

    def by_role(self, role):
        return next((p for p in self.parts.values() if p.role == role), None)

    def net(self, role, pin):
        part = self.by_role(role)
        return self.pin_net.get((part.ref, pin)) if part else None

    def pins_on(self, net):
        return sorted(k for k, v in self.pin_net.items() if v == net)

    def nets_of(self, ref):
        return {v for (r, _), v in self.pin_net.items() if r == ref}

    def two_terminal(self, prefix, net_a, net_b):
        return [
            p
            for p in self.parts.values()
            if re.fullmatch(prefix + r"\d+", p.ref) and self.nets_of(p.ref) == {net_a, net_b}
        ]


def parse_sexpr(text):
    tokens = re.findall(r'"(?:[^"\\]|\\.)*"|[()]|[^\s()"]+', text)
    stack, current = [], []
    for token in tokens:
        if token == "(":
            stack.append(current)
            current = []
        elif token == ")":
            done, current = current, stack.pop()
            current.append(done)
        else:
            current.append(token)
    return current[0]


def children(node, tag):
    return [x for x in node if isinstance(x, list) and x and x[0] == tag]


def child(node, tag):
    found = children(node, tag)
    return found[0] if found else None


def unquote(token):
    return token[1:-1].replace('\\"', '"') if token.startswith('"') else token


def load_design(path):
    tree = parse_sexpr(pathlib.Path(path).read_text(encoding="utf-8"))
    parts = {}
    for comp in children(child(tree, "components"), "comp"):
        ref = unquote(child(comp, "ref")[1])
        role = ""
        fields = child(comp, "fields")
        for field in children(fields, "field") if fields else []:
            if unquote(child(field, "name")[1]) == "Role" and len(field) > 2:
                role = unquote(field[2])
        parts[ref] = Part(ref, unquote(child(comp, "value")[1]), role)
    pin_net = {}
    for net in children(child(tree, "nets"), "net"):
        name = unquote(child(net, "name")[1]).lstrip("/")
        for node in children(net, "node"):
            pin_net[(unquote(child(node, "ref")[1]), unquote(child(node, "pin")[1]))] = name
    return Design(parts, pin_net)


def export_netlist(kicad_cli, out):
    subprocess.run(
        [kicad_cli, "sch", "export", "netlist", "--format", "kicadsexpr", "-o", str(out), str(SCHEMATIC)],
        check=True,
        capture_output=True,
    )


def run_report(kicad_cli, command, report, source):
    subprocess.run(
        [kicad_cli, *command, "--severity-all", "--format", "json", "-o", str(report), str(source)],
        check=True,
        capture_output=True,
    )
    return json.loads(report.read_text(encoding="utf-8"))


def kicad_checks(kicad_cli, tmp):
    erc = run_report(kicad_cli, ["sch", "erc"], tmp / "erc.json", SCHEMATIC)
    # Only the parity section gates here; layout DRC is judged separately.
    drc = run_report(kicad_cli, ["pcb", "drc", "--schematic-parity"], tmp / "drc.json", BOARD)
    violations = [v for sheet in erc["sheets"] for v in sheet["violations"]]
    return [
        ("ERC", [f"{v['severity']} {v['type']}: {v['description']}" for v in violations]),
        ("schematic parity", [f"{v['type']}: {v['description']}" for v in drc["schematic_parity"]]),
    ]


def find_kicad_cli(explicit):
    if explicit:
        return explicit if pathlib.Path(explicit).exists() else None
    for candidate in (os.environ.get("KICAD_CLI"), shutil.which("kicad-cli"), MACOS_KICAD_CLI):
        if candidate and pathlib.Path(candidate).exists():
            return candidate
    return None


def resistance(value):
    match = re.match(r"([\d.]+)\s*([kM]?)Ω", value)
    if not match:
        return None
    return float(match.group(1)) * {"": 1, "k": 1e3, "M": 1e6}[match.group(2)]


def power_rating(value):
    match = re.search(r"([\d.]+)\s*(m?)W\b", value)
    return float(match.group(1)) * (1e-3 if match.group(2) else 1) if match else None


def voltage_rating(value):
    match = re.search(r"([\d.]+)V\b", value)
    return float(match.group(1)) if match else None


def is_unconnected(net):
    return net is None or net.startswith("unconnected-")


def connectivity_lines(design):
    nets = {}
    for (ref, pin), net in design.pin_net.items():
        nets.setdefault(net, []).append(f"{ref}.{pin}")
    return sorted(f"{net}: {' '.join(sorted(pins))}" for net, pins in nets.items() if len(pins) > 1)


def check_golden(design, golden):
    current, expected = connectivity_lines(design), golden.read_text(encoding="utf-8").splitlines()
    if current == expected:
        return []
    diff = sorted(set(current) ^ set(expected))
    return ["connectivity differs from the reviewed golden: " + "; ".join(diff)]


def check_pin_tables(design):
    out = []
    for role, table in PIN_TABLES.items():
        if design.by_role(role) is None:
            out.append(f"{role}: part is missing")
            continue
        for pin, want in table.items():
            got = design.net(role, pin)
            if got != want:
                out.append(f"{role} pin {pin}: expected net {want}, found {got}")
    return out


def check_values(design):
    out = []
    for role, want in RESISTORS.items():
        part = design.by_role(role)
        if part is None:
            out.append(f"{role}: part is missing")
        elif resistance(part.value) != want:
            out.append(f"{role} ({part.ref}): expected {want:g} ohm, found {part.value!r}")
    return out


def check_cap_ratings(design):
    out = []
    for part in design.parts.values():
        if part.ref.startswith("C") and "v12" in design.nets_of(part.ref):
            rating = voltage_rating(part.value)
            if rating is None or rating < V12_CAP_MIN_RATING:
                out.append(f"{part.ref} on v12 needs at least {V12_CAP_MIN_RATING:g} V: {part.value!r}")
    return out


def check_ap63205_feedback(design):
    # The AP63205 regulates FB itself to 5.00 V, so FB is the output sense. A
    # divider makes FB read low and drives the output toward the input rail.
    fb, output = design.net("buck.buck", "1"), design.net("buck.L1", "2")
    if fb != output:
        return [f"AP63205 FB must connect directly to the output: FB is on {fb}, output is {output}"]
    return []


def check_ap63205_enable(design):
    # EN starts the buck automatically when tied to VIN or left open. CH224A PG
    # is open-drain and active low, so on EN it would hold the buck off.
    en = design.net("buck.buck", "2")
    if not (en == "v12" or is_unconnected(en)):
        return [f"AP63205 EN must connect to v12 or be left open, found {en}"]
    return []


def check_pg_led(design):
    # PG is an open-drain sink, active low. The LED hangs from the supply pin
    # into PG, so its series resistor sets the current and takes the 12 V drop.
    out = []
    pg, vhv = design.net("pd.ch224a", "10"), design.net("pd.ch224a", "1")
    if design.net("pd.led_pg", "1") != pg:
        out.append(f"PG LED cathode must be on {pg}, found {design.net('pd.led_pg', '1')}")
    series = design.two_terminal("R", vhv, design.net("pd.led_pg", "2"))
    if not series:
        out.append("PG LED anode needs a series resistor from the CH224A supply")
    for part in series:
        ohms = resistance(part.value)
        if ohms is None or ohms < LED_RESISTOR_MIN_OHMS:
            out.append(f"{part.ref}: LED series resistor must be at least {LED_RESISTOR_MIN_OHMS:g} ohm on 12 V, found {part.value!r}")
    return out


def check_ch224a_supply(design):
    # The CH224A supply and VBUS sense pins tolerate 32 V, and WCH's CH224K
    # replacement note says both former series resistors are shorted or 0 ohm.
    vhv, sense = design.net("pd.ch224a", "1"), design.net("pd.ch224a", "8")
    out = []
    for role, net, name in (("pd.r_vhv", vhv, "VHV"), ("pd.r_vbus", sense, "VBUS sense")):
        part = design.by_role(role)
        if part is None:
            out.append(f"CH224A {name}: 0 ohm link {role} is missing")
        elif resistance(part.value) != 0 or design.nets_of(part.ref) != {"v12", net}:
            out.append(f"CH224A {name} must link to v12 through 0 ohm, found {part.ref} {part.value!r} on {sorted(design.nets_of(part.ref))}")
    return out


def check_ch224a_cc(design):
    # The CH224A reference circuits run CC straight to the connector; the
    # 5.1 kOhm pulldowns appear only in the CH224D and CH221K references.
    out = []
    for role_pin, name in (("6", "CC2"), ("7", "CC1")):
        net = design.net("pd.ch224a", role_pin)
        for part in design.two_terminal("R", net, "gnd"):
            out.append(f"{part.ref} pulls {name} to ground: the CH224A reference circuit has no external CC pulldowns")
    return out


def check_ch224a_config(design):
    out = []
    cfg1 = design.net("pd.ch224a", "9")
    if not any(resistance(p.value) == 24e3 for p in design.two_terminal("R", cfg1, "gnd")):
        out.append("CH224A CFG1 needs 24 kOhm to ground to request 12 V")
    for pin in ("2", "3"):
        net = design.net("pd.ch224a", pin)
        if not (is_unconnected(net) or net == "gnd"):
            out.append(f"CH224A pin {pin} must float or be grounded for single-resistor mode, found {net}")
    return out


def check_support_parts(design):
    out = []
    if not any(p.value.startswith("100nF") for p in design.two_terminal("C", "BST", "SW")):
        out.append("AP63205 needs 100 nF between BST and SW")
    vhv = design.net("pd.ch224a", "1")
    if not any(p.value.startswith("1µF") for p in design.two_terminal("C", vhv, "gnd")):
        out.append("CH224A VHV needs 1 uF to ground")
    v5_caps = [p for p in design.two_terminal("C", "v5", "gnd") if p.value.startswith("22µF")]
    if len(v5_caps) < 2:
        out.append(f"AP63205 output needs two 22 uF capacitors per the datasheet typical circuit, found {len(v5_caps)}")
    return out


RULES = [
    ("pin tables", check_pin_tables),
    ("resistor values", check_values),
    ("12 V capacitor ratings", check_cap_ratings),
    ("AP63205 feedback", check_ap63205_feedback),
    ("AP63205 enable", check_ap63205_enable),
    ("CH224A PG LED", check_pg_led),
    ("CH224A supply links", check_ch224a_supply),
    ("CH224A CC pins", check_ch224a_cc),
    ("CH224A voltage selection", check_ch224a_config),
    ("support parts", check_support_parts),
]


def evaluate(design):
    return [(name, rule(design)) for name, rule in RULES]


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--netlist", help="use this exported netlist instead of running kicad-cli")
    parser.add_argument("--kicad-cli", help="path to kicad-cli")
    parser.add_argument("--update-golden", action="store_true", help="accept current connectivity as reviewed")
    args = parser.parse_args()

    kicad_results = []
    with tempfile.TemporaryDirectory() as tmp:
        netlist = args.netlist
        if netlist is None:
            kicad_cli = find_kicad_cli(args.kicad_cli)
            if kicad_cli is None:
                print("cannot run: kicad-cli not found", file=sys.stderr)
                return 2
            netlist = pathlib.Path(tmp) / "design.net"
            try:
                export_netlist(kicad_cli, netlist)
                kicad_results = kicad_checks(kicad_cli, pathlib.Path(tmp))
            except subprocess.CalledProcessError as error:
                print(f"cannot run: kicad-cli failed: {error.stderr!r}", file=sys.stderr)
                return 2
            except (ValueError, KeyError) as error:
                print(f"cannot run: unreadable kicad-cli report: {error!r}", file=sys.stderr)
                return 2
        try:
            design = load_design(netlist)
        except (OSError, IndexError, TypeError) as error:
            print(f"cannot run: unreadable netlist: {error}", file=sys.stderr)
            return 2

    if args.update_golden:
        GOLDEN.write_text("\n".join(connectivity_lines(design)) + "\n", encoding="utf-8")
        print(f"wrote {GOLDEN.relative_to(ROOT)}")

    if not GOLDEN.exists():
        print(f"cannot run: {GOLDEN.relative_to(ROOT)} is missing", file=sys.stderr)
        return 2

    results = [*kicad_results, ("connectivity golden", check_golden(design, GOLDEN)), *evaluate(design)]
    failed = 0
    for name, problems in results:
        print(f"{'FAIL' if problems else 'PASS'}  {name}")
        for problem in problems:
            print(f"      {problem}")
        failed += bool(problems)
    print(f"\n{len(results) - failed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
