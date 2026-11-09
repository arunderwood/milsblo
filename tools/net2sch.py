"""Generate milsblo.kicad_sch from the preserved netlist and the project library.

The output is a single label-only sheet: connected pins carry a net label and
unused pins a no-connect flag, so connectivity reads as a text diff. Pins connect
by exact coordinate, so a label must sit on the pin end to join the net.

Usage: net2sch.py <netlist.net> <board.kicad_pcb> <project_dir>
"""

import json
import pathlib
import re
import sys
import uuid

LIB = "milsblo"
NS = uuid.UUID("6f2b7a52-5a0e-4c7e-9a43-0d3f0c4e1b11")
MAX_WIDTH = 500.0
MARGIN = 25.4
PAPER = "A2"

# Readable names for nets the atopile compiler named after internal nodes.
NET_NAMES = {
    "A": "led_anode",
    "B": "pg_npn_base",
    "c_vdd-C": "ch224k_vdd",
    "fan1-_4": "fan1_pwm",
    "fan1-gpio_pwm": "fan1_gpio_pwm",
    "fan1-gpio_tach": "fan1_tach",
    "fan2-_4": "fan2_pwm",
    "fan2-gpio_pwm": "fan2_gpio_pwm",
    "fan2-gpio_tach": "fan2_tach",
    "footprint-C": "led_cathode",
}

GROUPS = {
    "pd": "USB-C PD sink (12 V)",
    "buck": "5 V buck",
    "c_bulk": "12 V bulk",
    "fan1": "Fan 1",
    "fan2": "Fan 2",
    "sensor": "BME280 port",
    "headers": "ESP32-S3-DevKitC-1 headers",
}
REF_ORDER = ["USB", "U", "J", "CN", "H", "L", "Q", "D", "LED", "R", "C"]


def parse(text):
    tokens = re.findall(r'"(?:[^"\\]|\\.)*"|[()]|[^\s()"]+', text)
    stack, cur = [], []
    for tok in tokens:
        if tok == "(":
            stack.append(cur)
            cur = []
        elif tok == ")":
            done, cur = cur, stack.pop()
            cur.append(done)
        else:
            cur.append(tok)
    return cur[0]


def unq(s):
    return s[1:-1].replace('\\"', '"').replace("\\\\", "\\") if s.startswith('"') else s


def q(s):
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def dump(node):
    if isinstance(node, list):
        return "(" + " ".join(dump(x) for x in node) + ")"
    return node


def kids(node, tag):
    return [x for x in node if isinstance(x, list) and x and x[0] == tag]


def first(node, tag):
    found = kids(node, tag)
    return found[0] if found else None


def uid(*key):
    return str(uuid.uuid5(NS, ":".join(key)))


def fmt(v):
    return f"{v:.4f}".rstrip("0").rstrip(".")


def snap(v, grid=2.54):
    return round(v / grid) * grid


def sym_props(sym):
    return {unq(p[1]): p for p in kids(sym, "property")}


def sym_pins(sym):
    out = []
    for sub in kids(sym, "symbol"):
        for pin in kids(sub, "pin"):
            at = first(pin, "at")
            out.append(
                (unq(first(pin, "number")[1]), float(at[1]), float(at[2]), int(float(at[3])))
            )
    return out


def body_y_range(sym):
    ys = []
    for sub in kids(sym, "symbol"):
        for rect in kids(sub, "rectangle"):
            ys += [float(first(rect, "start")[2]), float(first(rect, "end")[2])]
    return ys


def ref_key(ref):
    prefix, num = re.match(r"([A-Z]+)(\d+)", ref).groups()
    return (REF_ORDER.index(prefix), int(num))


def board_datasheets(path):
    text = pathlib.Path(path).read_text(encoding="utf-8")
    out = {}
    for fp in kids(parse(text), "footprint"):
        props = {unq(p[1]): unq(p[2]) for p in kids(fp, "property")}
        if props.get("Datasheet"):
            out[props["Reference"]] = props["Datasheet"]
    return out


net_path, board_path, project = sys.argv[1:4]
project = pathlib.Path(project)
net = parse(pathlib.Path(net_path).read_text(encoding="utf-8"))
library = parse((project / "library/milsblo.kicad_sym").read_text(encoding="utf-8"))
datasheets = board_datasheets(board_path)

by_lcsc, by_footprint = {}, {}
for sym in kids(library, "symbol"):
    props = sym_props(sym)
    if "LCSC Part" in props:
        by_lcsc[unq(props["LCSC Part"][2])] = sym
    else:
        by_footprint[unq(props["Footprint"][2]).split(":")[1]] = sym

pin_net = {}
for n in kids(first(net, "nets"), "net"):
    name = unq(first(n, "name")[1])
    nodes = kids(n, "node")
    for node in nodes:
        key = (unq(first(node, "ref")[1]), unq(first(node, "pin")[1]))
        pin_net[key] = NET_NAMES.get(name, name) if len(nodes) > 1 else None

groups = {key: [] for key in GROUPS}
for comp in kids(first(net, "components"), "comp"):
    fields = {unq(first(p, "name")[1]): unq(first(p, "value")[1]) for p in kids(comp, "property")}
    ref = unq(first(comp, "ref")[1])
    fp_name = unq(first(comp, "footprint")[1]).split(":")[1]
    sym = by_lcsc[fields["LCSC"]] if "LCSC" in fields else by_footprint[fp_name]
    groups[fields["atopile_address"].split(".")[0]].append((ref, comp, fields, fp_name, sym))

used_syms, placed, labels, flags, texts = {}, [], [], [], []
root = uid("root")
cursor_y = MARGIN

for key, title in GROUPS.items():
    texts.append(
        f"(text {q(title)} (exclude_from_sim no) (at {fmt(MARGIN)} {fmt(snap(cursor_y))} 0) "
        f"(effects (font (size 3.81 3.81) (bold yes)) (justify left bottom)) (uuid {q(uid('text', key))}))"
    )
    cursor_x, row_y, row_h = MARGIN, cursor_y + 7.62, 0.0
    for ref, comp, fields, fp_name, sym in sorted(groups[key], key=lambda c: ref_key(c[0])):
        pins = sym_pins(sym)
        xs, ys = [p[1] for p in pins], [p[2] for p in pins]
        margin = {0: 2.54, 180: 2.54, 90: 2.54, 270: 2.54}
        for number, _x, _y, ang in pins:
            net_name = pin_net.get((ref, number))
            if net_name:
                margin[ang] = max(margin[ang], len(net_name) * 1.15 + 2.54)
        width = max(xs) - min(xs) + margin[0] + margin[180] + 10.16
        height = max(ys) - min(ys) + margin[90] + margin[270] + 15.24
        if cursor_x + width > MAX_WIDTH and cursor_x > MARGIN:
            cursor_x, row_y, row_h = MARGIN, row_y + row_h, 0.0
        ox = snap(cursor_x + margin[0] - min(xs))
        oy = snap(row_y + margin[270] + 7.62 + max(ys))
        cursor_x += width
        row_h = max(row_h, height)

        name = unq(sym[1])
        lib_id = f"{LIB}:{name}"
        if lib_id not in used_syms:
            copy = list(sym)
            copy[1] = q(lib_id)
            used_syms[lib_id] = copy

        pin_text = []
        for number, px, py, ang in pins:
            pin_text.append(f"(pin {q(number)} (uuid {q(uid('pin', ref, number))}))")
            x, y = ox + px, oy - py
            net_name = pin_net.get((ref, number))
            if net_name:
                angle, justify = {
                    0: (180, "right bottom"),
                    180: (0, "left bottom"),
                    90: (270, "right bottom"),
                    270: (90, "left bottom"),
                }[ang]
                labels.append(
                    f"(label {q(net_name)} (at {fmt(x)} {fmt(y)} {angle}) "
                    f"(effects (font (size 1.27 1.27)) (justify {justify})) "
                    f"(uuid {q(uid('label', ref, number))}))"
                )
            else:
                flags.append(f"(no_connect (at {fmt(x)} {fmt(y)}) (uuid {q(uid('nc', ref, number))}))")

        value = unq(first(comp, "value")[1])
        lib_props = sym_props(sym)
        if value.endswith("_package"):
            value = fields.get("Partnumber") or "1x22 socket"

        extent = ys + body_y_range(sym)
        ref_y = oy - max(max(extent), float(first(lib_props["Reference"], "at")[2]))
        val_y = oy - min(min(extent), float(first(lib_props["Value"], "at")[2]))
        cx = ox + (max(xs) + min(xs)) / 2
        visible = [("Reference", ref, ref_y - 1.27), ("Value", value, val_y + 2.54)]
        hidden = [
            ("Footprint", f"{LIB}:{fp_name}"),
            ("Datasheet", datasheets.get(ref, "")),
            ("Description", ""),
            ("LCSC Part", fields.get("LCSC", "")),
            ("Manufacturer", fields.get("Manufacturer", "")),
            ("Partnumber", fields.get("Partnumber", "")),
            ("Role", fields["atopile_address"]),
        ]
        prop_text = [
            f"(property {q(k)} {q(v)} (at {fmt(cx)} {fmt(y)} 0) (effects (font (size 1.27 1.27))))"
            for k, v, y in visible
        ]
        prop_text += [
            f"(property {q(k)} {q(v)} (at {fmt(ox)} {fmt(oy)} 0) (effects (font (size 1.27 1.27)) (hide yes)))"
            for k, v in hidden
            if v or k in ("Footprint", "Datasheet", "Description")
        ]
        placed.append(
            f"(symbol (lib_id {q(lib_id)}) (at {fmt(ox)} {fmt(oy)} 0) (unit 1) "
            f"(exclude_from_sim no) (in_bom yes) (on_board yes) (dnp no) "
            f"(uuid {q(uid('sym', ref))}) {' '.join(prop_text)} {' '.join(pin_text)} "
            f"(instances (project {q(LIB)} (path {q('/' + root)} (reference {q(ref)}) (unit 1)))))"
        )
    cursor_y = row_y + row_h + 7.62

sheet = "\n".join(
    [
        f'(kicad_sch (version 20250114) (generator "net2sch") (generator_version "10.0") (uuid {q(root)}) (paper "{PAPER}")',
        '(title_block (title "milsblo") (comment 1 "USB-C PD ESP32-S3 backpack: two 4-pin PWM fans and a BME280 port"))',
        "(lib_symbols " + " ".join(dump(s) for s in used_syms.values()) + ")",
        *texts,
        *flags,
        *labels,
        *placed,
        '(sheet_instances (path "/" (page "1"))) (embedded_fonts no))',
    ]
)
(project / "milsblo.kicad_sch").write_text(sheet + "\n", encoding="utf-8")
(project / "milsblo.kicad_pro").write_text(
    json.dumps({"meta": {"filename": "milsblo.kicad_pro", "version": 3}}, indent=2) + "\n",
    encoding="utf-8",
)
print(
    f"symbols {len(placed)} lib_symbols {len(used_syms)} labels {len(labels)} "
    f"no_connect {len(flags)} datasheets {len(datasheets)} height {cursor_y:.0f}mm"
)
