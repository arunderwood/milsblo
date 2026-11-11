#!/usr/bin/env python3
"""Check the electrical rules for milsblo that KiCad's ERC cannot see.

ERC proves pin types agree. It cannot know that a resistor must be 24 kOhm or
that a fixed-output regulator's FB pin belongs on the output. These rules come
from the part datasheets:

  AP63205: Diodes Inc. DS41326 Rev. 3-2
  AO3407A: Alpha & Omega AO3407A datasheet
  DC050-T: SHOU HAN DC050-T drawing

With kicad-cli available it also gates on ERC, schematic-to-board parity and
board DRC, and it enforces the layout rules DRC cannot express: rail widths,
the antenna keepout, connectors on board edges and the DevKit header geometry.
This one command is the whole design check, locally and in CI.

Usage: check_design.py [--netlist FILE] [--kicad-cli PATH] [--update-golden]
Exit codes: 0 all rules pass, 1 a rule failed, 2 the check could not run.
"""

import argparse
import dataclasses
import json
import math
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

LED_RESISTOR_MIN_OHMS = 2.2e3
V12_CAP_MIN_RATING = 25.0

V12_MIN_TRACK_MM = 1.016
# The jack's centre pin carries the whole board current before Q1.
RAIL_MIN_TRACK_MM = {"v12": V12_MIN_TRACK_MM, "vin": V12_MIN_TRACK_MM, "v5": 0.508}

# DevKitC-1 v1.1 drawing: 2.54 mm pitch, rows 22.86 mm apart, pin 1 at the
# antenna end. The module antenna begins 1.54 mm past the pin 1 row.
HEADER_ROW_MM = 22.86
HEADER_SPAN_MM = 21 * 2.54
BOARD_MARGIN_PAST_PIN1_MM = 2.0
# With the DevKit plugged in, the antenna sits at least 13.4 mm above this board
# (socket and header stack, DevKit PCB, module), so 15 mm of clearance needs
# about 6 mm of horizontal distance from where the antenna starts.
ANTENNA_POUR_START_MM = 6.0

# reference: (edge, nearest allowed, furthest allowed), anchor-to-edge distance
EDGE_CONNECTORS = {
    "DC1": ("bottom", 0.0, 0.5),
    "CN1": ("bottom", 2.8, 3.8),
    "H1": ("left", 2.0, 3.0),
    "H2": ("right", 2.0, 3.0),
}

# (part pad, the pad it decouples, allowed centre distance in mm)
DECOUPLING = [
    (("C2", "1"), ("U1", "3"), 5.0),
    (("C2", "2"), ("U1", "4"), 5.0),
    (("C1", "1"), ("U1", "6"), 5.0),
    (("C3", "1"), ("L1", "2"), 5.0),
    (("C8", "1"), ("L1", "2"), 5.0),
    (("C7", "1"), ("Q1", "2"), 5.0),
    (("C6", "1"), ("CN1", "2"), 5.0),
]

MIN_GROUND_VIAS = 25

RESISTORS = {
    "pwr.r_led": 4.7e3,
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
    # DC050-T: pad 2 is the centre pin, 4 the sleeve spring, 3 the switch
    # contact that rests on the sleeve spring until a plug is inserted.
    "pwr.jack": {"2": "vin", "3": "gnd", "4": "gnd"},
    # AO3407A in SOT-23: 1 gate, 2 source, 3 drain.
    "pwr.q_rev": {"1": "gnd", "2": "v12", "3": "vin"},
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


@dataclasses.dataclass
class Track:
    net: str
    layer: str
    width: float
    start: tuple
    end: tuple


@dataclasses.dataclass
class Via:
    net: str
    at: tuple


@dataclasses.dataclass
class Zone:
    net: str
    layer: str
    name: str
    filled: list


@dataclasses.dataclass
class Footprint:
    ref: str
    at: tuple
    rotation: float
    layer: str
    pads: dict


@dataclasses.dataclass
class Layout:
    footprints: dict
    tracks: list
    vias: list
    zones: list
    edge: tuple


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


def point(node):
    return (float(node[1]), float(node[2]))


def net_name(node):
    found = child(node, "net")
    return unquote(found[1]).lstrip("/") if found else ""


def load_layout(path):
    tree = parse_sexpr(pathlib.Path(path).read_text(encoding="utf-8"))
    footprints = {}
    for fp in children(tree, "footprint"):
        properties = {unquote(p[1]): unquote(p[2]) for p in children(fp, "property")}
        at = child(fp, "at")
        x, y, rotation = float(at[1]), float(at[2]), float(at[3]) if len(at) > 3 else 0.0
        radians = math.radians(rotation)
        cos, sin = math.cos(radians), math.sin(radians)
        pads = {}
        for pad in children(fp, "pad"):
            px, py = float(child(pad, "at")[1]), float(child(pad, "at")[2])
            pads.setdefault(unquote(pad[1]), (x + px * cos + py * sin, y - px * sin + py * cos))
        footprints[properties["Reference"]] = Footprint(
            properties["Reference"], (x, y), rotation, unquote(child(fp, "layer")[1]), pads
        )
    tracks = [
        Track(net_name(n), unquote(child(n, "layer")[1]), float(child(n, "width")[1]), point(child(n, "start")), point(child(n, "end")))
        for n in children(tree, "segment")
    ]
    vias = [Via(net_name(n), point(child(n, "at"))) for n in children(tree, "via")]
    zones = []
    for n in children(tree, "zone"):
        name = child(n, "name")
        filled = [point(xy) for poly in children(n, "filled_polygon") for xy in children(child(poly, "pts"), "xy")]
        zones.append(Zone(net_name(n), unquote(child(n, "layer")[1]), unquote(name[1]) if name else "", filled))
    edges = [
        point(node)
        for tag in ("gr_line", "gr_rect")
        for item in children(tree, tag)
        if unquote(child(item, "layer")[1]) == "Edge.Cuts"
        for node in (child(item, "start"), child(item, "end"))
    ]
    xs, ys = [p[0] for p in edges] or [0.0], [p[1] for p in edges] or [0.0]
    return Layout(footprints, tracks, vias, zones, (min(xs), min(ys), max(xs), max(ys)))


def check_rail_widths(layout):
    out = []
    for track in layout.tracks:
        minimum = RAIL_MIN_TRACK_MM.get(track.net)
        if minimum and track.width < minimum:
            out.append(f"{track.net} track at {track.start}: {track.width} mm is under {minimum} mm")
    return out


def check_rail_zones(layout):
    # Supply current runs in tracks, which the width rule sizes. A zone can
    # neck down between pads without any rule noticing.
    return [
        f"zone {z.name!r} on {z.net}: supply rails must be routed as tracks"
        for z in layout.zones
        if z.net in RAIL_MIN_TRACK_MM
    ]


def check_jack_side(layout):
    # The jack is 11 mm tall and the DevKit sits about 11 mm above the top
    # side, so the jack only fits on the back.
    jack = layout.footprints["DC1"]
    return [] if jack.layer == "B.Cu" else [f"DC1 must be on the back of the board, found {jack.layer}"]


def check_antenna_keepout(layout):
    j1, j2 = layout.footprints["J1"], layout.footprints["J2"]
    pin1_y = j1.pads["1"][1]
    boundary = pin1_y + ANTENNA_POUR_START_MM
    out = []
    if layout.edge[1] < pin1_y - BOARD_MARGIN_PAST_PIN1_MM:
        out.append(f"board extends {pin1_y - layout.edge[1]:.2f} mm past pin 1, under the DevKit antenna")
    for zone in layout.zones:
        highest = min((p[1] for p in zone.filled), default=boundary)
        if highest < boundary - 0.01:
            out.append(f"zone {zone.name!r} fills {boundary - highest:.2f} mm into the antenna keepout")
    columns = (j1.pads["1"][0] + 1.6, j2.pads["1"][0] - 1.6)
    for track in layout.tracks:
        for x, y in (track.start, track.end):
            stub = track.net in ("v3v3", "gnd") and (x <= columns[0] or x >= columns[1])
            if y < boundary - 0.01 and not stub:
                out.append(f"{track.net} track at {(x, y)} is inside the antenna keepout")
    out += [f"{via.net} via at {via.at} is inside the antenna keepout" for via in layout.vias if via.at[1] < boundary - 0.01]
    return out


def check_connector_edges(layout):
    xmin, ymin, xmax, ymax = layout.edge
    out = []
    for ref, (edge, near, far) in EDGE_CONNECTORS.items():
        x, y = layout.footprints[ref].at
        distance = {"left": x - xmin, "right": xmax - x, "top": y - ymin, "bottom": ymax - y}[edge]
        if not near <= distance <= far:
            out.append(f"{ref}: {distance:.2f} mm from the {edge} edge, expected {near} to {far} mm")
    return out


def check_header_geometry(layout):
    j1, j2 = layout.footprints["J1"], layout.footprints["J2"]
    out = []
    for fp in (j1, j2):
        span = fp.pads["22"][1] - fp.pads["1"][1]
        if abs(span - HEADER_SPAN_MM) > 0.02:
            out.append(f"{fp.ref}: pin 1 to pin 22 is {span:.2f} mm, expected {HEADER_SPAN_MM:.2f} mm toward the USB end")
        if fp.layer != "F.Cu":
            out.append(f"{fp.ref}: sockets must be on the top side, found {fp.layer}")
    spacing = j2.pads["1"][0] - j1.pads["1"][0]
    if abs(spacing - HEADER_ROW_MM) > 0.02:
        out.append(f"header rows are {spacing:.2f} mm apart, the DevKit has {HEADER_ROW_MM} mm")
    if abs(j2.pads["1"][1] - j1.pads["1"][1]) > 0.02:
        out.append("J1 and J2 pin 1 are not level")
    return out


def check_decoupling_distance(layout):
    out = []
    for (cap, cap_pad), (part, part_pad), limit in DECOUPLING:
        ax, ay = layout.footprints[cap].pads[cap_pad]
        bx, by = layout.footprints[part].pads[part_pad]
        distance = math.hypot(ax - bx, ay - by)
        if distance > limit:
            out.append(f"{cap}.{cap_pad} is {distance:.2f} mm from {part}.{part_pad}, limit {limit} mm")
    return out


def check_ground_stitching(layout):
    out = []
    for layer in ("F.Cu", "B.Cu"):
        if not any(z.net == "gnd" and z.layer == layer and z.filled for z in layout.zones):
            out.append(f"no filled ground pour on {layer}")
    vias = sum(v.net == "gnd" for v in layout.vias)
    if vias < MIN_GROUND_VIAS:
        out.append(f"{vias} ground vias, expected at least {MIN_GROUND_VIAS}")
    return out


LAYOUT_RULES = [
    ("rail track widths", check_rail_widths),
    ("rail zones", check_rail_zones),
    ("antenna keepout", check_antenna_keepout),
    ("connectors on edges", check_connector_edges),
    ("jack on the back", check_jack_side),
    ("DevKit header geometry", check_header_geometry),
    ("decoupling distance", check_decoupling_distance),
    ("ground pours and stitching", check_ground_stitching),
]


def evaluate_layout(layout):
    return [(name, rule(layout)) for name, rule in LAYOUT_RULES]


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
    drc = run_report(kicad_cli, ["pcb", "drc", "--schematic-parity"], tmp / "drc.json", BOARD)
    violations = [v for sheet in erc["sheets"] for v in sheet["violations"]]
    board = [*drc["violations"], *drc["unconnected_items"]]
    return [
        ("ERC", [f"{v['severity']} {v['type']}: {v['description']}" for v in violations]),
        ("schematic parity", [f"{v['type']}: {v['description']}" for v in drc["schematic_parity"]]),
        ("board DRC", [f"{v['severity']} {v['type']}: {v['description']}" for v in board]),
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
    # EN starts the buck automatically when tied to VIN or left open.
    en = design.net("buck.buck", "2")
    if not (en == "v12" or is_unconnected(en)):
        return [f"AP63205 EN must connect to v12 or be left open, found {en}"]
    return []


def check_power_led(design):
    # The LED runs from the 12 V rail, so its series resistor sets the current
    # and takes most of the 12 V.
    out = []
    if design.net("pwr.led", "1") != "gnd":
        out.append(f"power LED cathode must be on gnd, found {design.net('pwr.led', '1')}")
    series = design.two_terminal("R", "v12", design.net("pwr.led", "2"))
    if not series:
        out.append("power LED anode needs a series resistor from v12")
    for part in series:
        ohms = resistance(part.value)
        if ohms is None or ohms < LED_RESISTOR_MIN_OHMS:
            out.append(f"{part.ref}: LED series resistor must be at least {LED_RESISTOR_MIN_OHMS:g} ohm on 12 V, found {part.value!r}")
    return out


def check_reverse_protection(design):
    # Q1 is a P-channel MOSFET in the positive lead: drain to the jack, source
    # to the rail, gate to ground. A centre-negative supply leaves the gate at
    # the source potential and the body diode reverse biased, so nothing after
    # Q1 sees it. That only holds if Q1's drain is the sole load on the jack.
    jack, fet = design.by_role("pwr.jack"), design.by_role("pwr.q_rev")
    if jack is None or fet is None:
        return ["reverse-polarity protection needs both pwr.jack and pwr.q_rev"]
    out = []
    tip = design.net("pwr.jack", "2")
    if tip == "v12":
        out.append("jack centre pin connects straight to v12, bypassing Q1")
    others = [f"{ref}.{pin}" for ref, pin in design.pins_on(tip) if (ref, pin) not in ((jack.ref, "2"), (fet.ref, "3"))]
    if others:
        out.append(f"only Q1's drain may share the jack centre pin net, found {' '.join(others)}")
    return out


def check_support_parts(design):
    out = []
    if not any(p.value.startswith("100nF") for p in design.two_terminal("C", "BST", "SW")):
        out.append("AP63205 needs 100 nF between BST and SW")
    if not any(p.value.startswith("100nF") for p in design.two_terminal("C", "v12", "gnd")):
        out.append("12 V rail needs a 100 nF bypass to ground")
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
    ("power LED", check_power_led),
    ("reverse-polarity protection", check_reverse_protection),
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

    try:
        layout = load_layout(BOARD)
    except (OSError, IndexError, TypeError, KeyError, ValueError) as error:
        print(f"cannot run: unreadable board: {error}", file=sys.stderr)
        return 2

    results = [
        *kicad_results,
        ("connectivity golden", check_golden(design, GOLDEN)),
        *evaluate(design),
        *evaluate_layout(layout),
    ]
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
