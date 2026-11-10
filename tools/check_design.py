#!/usr/bin/env python3
"""Check the electrical rules for milsblo that KiCad's ERC cannot see.

ERC proves pin types agree. It cannot know that a resistor must be 24 kOhm or
that a fixed-output regulator's FB pin belongs on the output. These rules come
from the part datasheets:

  AP63205: Diodes Inc. DS41326 Rev. 3-2
  CH224K:  WCH CH224 manual 1, V2.1

Usage: check_design.py [--netlist FILE] [--kicad-cli PATH] [--update-golden]
Exit codes: 0 all rules pass, 1 a rule failed, 2 the check could not run.
"""

import argparse
import dataclasses
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCHEMATIC = ROOT / "elec/kicad/milsblo.kicad_sch"
GOLDEN = ROOT / "elec/kicad/connectivity.golden"
MACOS_KICAD_CLI = "/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli"

V12 = 12.0
CH224K_VDD_SHUNT_V = 3.3
CH224K_VDD_SHUNT_MAX_A = 0.030
V12_CAP_MIN_RATING = 25.0

RESISTORS = {
    "pd.r_cfg1": 24e3,
    "pd.r_led": 470,
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
    "pd.ch224k": {
        "1": "ch224k_vdd", "4": "DP", "5": "DM", "6": "CC2", "7": "CC1",
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
    # EN starts the buck automatically when tied to VIN or left open. CH224K PG
    # is open-drain and active low, so on EN it would hold the buck off.
    en = design.net("buck.buck", "2")
    if not (en == "v12" or is_unconnected(en)):
        return [f"AP63205 EN must connect to v12 or be left open, found {en}"]
    return []


def check_pg_led(design):
    # PG sinks current when power is good, so the LED hangs from VDD into PG.
    out = []
    pg, vdd = design.net("pd.ch224k", "10"), design.net("pd.ch224k", "1")
    if design.net("pd.led_pg", "1") != pg:
        out.append(f"PG LED cathode must be on {pg}, found {design.net('pd.led_pg', '1')}")
    if not design.two_terminal("R", vdd, design.net("pd.led_pg", "2")):
        out.append("PG LED anode needs a series resistor from CH224K VDD")
    return out


def check_ch224k_vdd_feed(design):
    # VDD is an internal 3.3 V shunt regulator that sinks at most 30 mA. The
    # series resistor drops the rest of the rail, so its dissipation does not
    # depend on what VDD's loads draw.
    feeds = design.two_terminal("R", "v12", design.net("pd.ch224k", "1"))
    if len(feeds) != 1:
        return [f"CH224K VDD needs exactly one series resistor from v12, found {len(feeds)}"]
    part, ohms, rated = feeds[0], resistance(feeds[0].value), power_rating(feeds[0].value)
    if ohms is None or rated is None:
        return [f"{part.ref}: cannot read resistance and power rating from {part.value!r}"]
    drop = V12 - CH224K_VDD_SHUNT_V
    out = []
    if drop / ohms > CH224K_VDD_SHUNT_MAX_A:
        out.append(f"{part.ref}: {drop / ohms * 1e3:.1f} mA exceeds the VDD shunt limit of 30 mA")
    if drop**2 / ohms > rated:
        out.append(f"{part.ref}: dissipates {drop**2 / ohms * 1e3:.0f} mW at 12 V, rated {rated * 1e3:.0f} mW")
    return out


def check_ch224k_vbus_sense(design):
    # Pin 8 is a voltage-sense input that needs a series resistor from VBUS.
    sense = design.net("pd.ch224k", "8")
    if sense == "v12":
        return ["CH224K VBUS sense pin is tied directly to v12: it needs a series resistor (10 kOhm in the reference circuit)"]
    series = design.two_terminal("R", sense, "v12")
    if not any(resistance(p.value) == 10e3 for p in series):
        return [f"CH224K VBUS sense pin needs 10 kOhm in series from v12, found {[p.value for p in series]}"]
    return []


def check_ch224k_cc(design):
    # The CH224K reference circuits run CC straight to the connector; the
    # 5.1 kOhm pulldowns appear only in the CH224D and CH221K references.
    out = []
    for role_pin, name in (("6", "CC2"), ("7", "CC1")):
        net = design.net("pd.ch224k", role_pin)
        for part in design.two_terminal("R", net, "gnd"):
            out.append(f"{part.ref} pulls {name} to ground: the CH224K reference circuit has no external CC pulldowns")
    return out


def check_ch224k_config(design):
    out = []
    cfg1 = design.net("pd.ch224k", "9")
    if not any(resistance(p.value) == 24e3 for p in design.two_terminal("R", cfg1, "gnd")):
        out.append("CH224K CFG1 needs 24 kOhm to ground to request 12 V")
    for pin in ("2", "3"):
        net = design.net("pd.ch224k", pin)
        if not (is_unconnected(net) or net == "gnd"):
            out.append(f"CH224K pin {pin} must float or be grounded for single-resistor mode, found {net}")
    return out


def check_support_parts(design):
    out = []
    if not any(p.value.startswith("100nF") for p in design.two_terminal("C", "BST", "SW")):
        out.append("AP63205 needs 100 nF between BST and SW")
    vdd = design.net("pd.ch224k", "1")
    if not any(p.value.startswith("1µF") for p in design.two_terminal("C", vdd, "gnd")):
        out.append("CH224K VDD needs 1 uF to ground")
    return out


RULES = [
    ("pin tables", check_pin_tables),
    ("resistor values", check_values),
    ("12 V capacitor ratings", check_cap_ratings),
    ("AP63205 feedback", check_ap63205_feedback),
    ("AP63205 enable", check_ap63205_enable),
    ("CH224K PG LED", check_pg_led),
    ("CH224K VDD feed", check_ch224k_vdd_feed),
    ("CH224K VBUS sense", check_ch224k_vbus_sense),
    ("CH224K CC pins", check_ch224k_cc),
    ("CH224K voltage selection", check_ch224k_config),
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
            except subprocess.CalledProcessError as error:
                print(f"cannot run: netlist export failed: {error.stderr!r}", file=sys.stderr)
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

    results = [("connectivity golden", check_golden(design, GOLDEN)), *evaluate(design)]
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
