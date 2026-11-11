#!/usr/bin/env python3
"""Regenerate the milsblo board layout: outline, placement, routing and pours.

Rewrites elec/kicad/milsblo.kicad_pcb in place. Placement and every copper path
are explicit so a layout change reads as a reviewable diff of this file.

Run with the Python that ships inside KiCad, because it needs pcbnew:
  /Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3 tools/layout_board.py

Coordinates are millimetres from the top-left board corner, x right and y down,
viewed from the top side. The antenna end of the DevKit is y = 0.
"""

import pathlib
import re

import pcbnew as pn

BOARD = pathlib.Path(__file__).resolve().parent.parent / "elec/kicad/milsblo.kicad_pcb"

ORIGIN = (100.0, 50.0)
WIDTH, HEIGHT = 26.66, 68.5
J1_X, J2_X, PIN1_Y = 1.9, 24.76, 1.9
PITCH = 2.54
# Pours and routing stay below this line so the module antenna, which starts
# 1.54 mm past the pin 1 row, sees no ground plane under it.
ANTENNA_KEEPOUT_Y = 7.9

V12_W, V5_W, SIG_W = 1.016, 0.508, 0.25
VIA_D, VIA_DRILL = 0.7, 0.3


def pin_y(n):
    return PIN1_Y + (n - 1) * PITCH


# reference: (x, y, rotation in degrees)
PLACEMENT = {
    "J1": (J1_X, PIN1_Y, 0),
    "J2": (J2_X, PIN1_Y, 0),
    "H1": (2.54, 62.6, 90),
    "H2": (24.12, 62.6, 270),
    "DC1": (13.33, HEIGHT, 180),
    "CN1": (7.3, 65.16, 0),
    "Q1": (20.0, 57.0, 270),
    "C7": (20.9, 60.3, 180),
    "R13": (14.0, 53.3, 0),
    "LED1": (17.0, 53.3, 180),
    "C4": (16.2, 46.0, 180),
    "U1": (17.0, 38.0, 0),
    "C2": (19.6, 38.0, 90),
    "C1": (15.3, 35.0, 0),
    "L1": (17.0, 31.5, 270),
    "C3": (12.6, 29.72, 180),
    "C8": (17.0, 26.0, 90),
    "R3": (4.6, 56.6, 270),
    "R5": (22.0, 65.0, 270),
    "R4": (7.35, pin_y(6), 0),
    "R6": (7.35, pin_y(7), 0),
    "R12": (8.6, 29.4, 270),
    "R11": (8.6, 35.6, 90),
    "C6": (6.8, 61.0, 90),
}

# The jack is 11 mm tall and the DevKit sits about 11 mm above this board, so
# it mounts on the back with its plug mouth at the bottom edge.
BACK_SIDE = {"DC1"}

# Each path is (net, layer, width, points). A via is (net, x, y).
F, B = "F.Cu", "B.Cu"


def path(net, layer, width, *points):
    return (net, layer, width, points)


TRACKS = [
    # Jack centre pin: both back pads join, then two vias lift it to Q1's drain.
    path("/vin", B, V12_W, (19.08, 63.4), (19.08, 54.9), (18.2, 54.9)),
    path("/vin", F, V12_W, (20.0, 55.76), (20.0, 54.9), (18.2, 54.9)),
    # 12 V from Q1's source: a trunk up to the buck, branches to each fan header.
    path("/v12", F, V12_W, (20.95, 58.24), (22.2, 58.24)),
    path("/v12", F, V12_W, (22.2, 61.33), (22.2, 39.5), (19.6, 39.5)),
    path("/v12", F, V12_W, (19.6, 39.59), (19.6, 39.5), (17.1, 39.2)),
    path("/v12", F, V12_W, (22.2, 61.33), (23.22, 61.33)),
    path("/v12", F, V12_W, (20.0, 46.0), (22.2, 46.0)),
    path("/v12", F, V12_W, (22.2, 60.3), (21.6, 60.3)),
    path("/v12", F, V12_W, (22.2, 52.0), (10.2, 52.0), (10.2, 60.9)),
    path("/v12", F, V12_W, (13.25, 52.0), (13.25, 53.3)),
    path("/v12", B, V12_W, (10.2, 60.9), (4.6, 60.9), (4.6, 63.87), (2.54, 63.87)),
    # Switching node, kept to the shortest path from pin 5 into L1.
    path("/gnd", F, 0.6, (17.95, 37.0), (18.55, 37.35)),
    path("/gnd", F, 0.6, (18.55, 37.35), (19.6, 36.5)),
    path("/SW", F, 0.8, (17.0, 37.0), (17.0, 35.8), (17.0, 34.1)),
    path("/SW", F, 0.5, (16.0, 35.0), (17.0, 35.0)),
    path("/BST", F, SIG_W, (16.05, 36.8), (16.05, 35.85), (14.6, 35.85), (14.6, 35.0)),
    # 5 V: output capacitors at L1, then the bottom layer to the DevKit 5V pin.
    path("/v5", F, 0.8, (15.1, 29.72), (17.0, 29.72)),
    path("/v5", F, 0.8, (14.19, 29.72), (15.1, 29.72)),
    path("/v5", F, 0.8, (17.0, 28.66), (17.0, 27.59)),
    path("/v5", F, V5_W, (14.19, 29.72), (14.19, 30.5), (13.6, 31.1), (13.6, 40.45), (16.05, 40.45), (16.05, 39.2)),
    path("/v5", F, V5_W, (14.19, 30.5), (13.6, 31.1)),
    path("/v5", B, V5_W, (13.6, 31.1), (9.7, 31.1), (9.7, 50.0), (3.6, 50.0), (3.6, pin_y(21)), (J1_X, pin_y(21))),
    # Power LED and the ground returns around Q1.
    path("/led_anode", F, SIG_W, (14.75, 53.3), (16.25, 53.3)),
    path("/gnd", F, SIG_W, (17.75, 53.3), (18.7, 53.3)),
    path("/gnd", F, SIG_W, (19.05, 58.24), (19.05, 60.3)),
    path("/gnd", F, SIG_W, (20.2, 60.3), (17.2, 60.3)),
    # 3.3 V from the top of J1 to the pullups and the sensor connector.
    path("/v3v3", F, SIG_W, (J1_X, pin_y(1)), (J1_X, pin_y(2))),
    path("/v3v3", F, SIG_W, (J1_X, pin_y(2)), (3.4, pin_y(2)), (3.4, 8.0), (9.25, 8.0), (9.25, 61.4), (9.5, 62.0), (9.5, 64.6), (6.8, 64.6), (6.8, 63.5)),
    path("/v3v3", F, SIG_W, (9.25, pin_y(6)), (8.1, pin_y(6))),
    path("/v3v3", F, SIG_W, (9.25, pin_y(7)), (8.1, pin_y(7))),
    path("/v3v3", F, SIG_W, (9.25, 29.83), (8.6, 29.83)),
    path("/v3v3", F, SIG_W, (9.25, 35.17), (8.6, 35.17)),
    path("/v3v3", F, SIG_W, (6.8, 61.7), (6.8, 62.8)),
    path("/gnd", F, SIG_W, (6.8, 60.3), (6.8, 59.5)),
    # Fan 1
    path("/fan1_gpio_pwm", F, SIG_W, (J1_X, pin_y(4)), (4.4, pin_y(4)), (4.4, 55.0), (4.6, 55.0), (4.6, 55.85)),
    path("/fan1_pwm", F, SIG_W, (4.6, 57.35), (4.6, 58.79), (3.44, 58.79)),
    path("/fan1_tach", F, SIG_W, (J1_X, pin_y(6)), (3.2, pin_y(6)), (3.2, 57.0)),
    path("/fan1_tach", B, SIG_W, (3.2, 57.0), (3.75, 57.0), (3.75, 61.33), (3.2, 61.33)),
    path("/fan1_tach", B, SIG_W, (J1_X, pin_y(6)), (5.5, pin_y(6))),
    path("/fan1_tach", F, SIG_W, (5.5, pin_y(6)), (6.6, pin_y(6))),
    # Fan 2 crosses on the bottom layer, under the fan 1 and I2C verticals.
    path("/fan2_gpio_pwm", B, SIG_W, (J1_X, pin_y(5)), (22.85, pin_y(5)), (22.85, 63.0)),
    path("/fan2_gpio_pwm", F, SIG_W, (22.85, 63.0), (22.0, 63.75), (22.0, 64.25)),
    path("/fan2_pwm", F, SIG_W, (22.0, 65.75), (22.0, 66.41), (23.22, 66.41)),
    path("/fan2_tach", B, SIG_W, (J1_X, pin_y(7)), (21.7, pin_y(7)), (21.7, 63.87), (23.22, 63.87)),
    path("/fan2_tach", F, SIG_W, (5.5, pin_y(7)), (6.6, pin_y(7))),
    # I2C
    path("/sda", B, SIG_W, (J1_X, pin_y(12)), (7.8, pin_y(12))),
    path("/sda", F, SIG_W, (7.8, pin_y(12)), (7.8, 62.45)),
    path("/sda", F, SIG_W, (7.8, pin_y(12)), (7.8, 28.97), (8.6, 28.97)),
    path("/scl", B, SIG_W, (J1_X, pin_y(15)), (8.55, pin_y(15))),
    path("/scl", F, SIG_W, (8.55, pin_y(15)), (8.8, 38.0), (8.8, 62.45)),
    path("/scl", F, SIG_W, (8.55, pin_y(15)), (8.6, 36.03)),
    # Ground stubs that cannot reach a pour: J2 pin 1 sits inside the keepout.
    path("/gnd", F, SIG_W, (J2_X, pin_y(1)), (23.6, pin_y(1) + 1.0), (23.6, 8.4)),
]

VIAS = [
    ("/v12", 10.2, 60.9),
    ("/v5", 13.6, 31.1),
    ("/vin", 18.2, 54.9),
    ("/vin", 19.2, 54.9),
    ("/fan1_tach", 3.2, 57.0),
    ("/fan1_tach", 5.5, pin_y(6)),
    ("/fan2_tach", 5.5, pin_y(7)),
    ("/fan2_gpio_pwm", 22.85, 63.0),
    ("/sda", 7.8, pin_y(12)),
    ("/scl", 8.55, pin_y(15)),
    # Ground: regulator return, capacitor returns and pad tie-downs.
    ("/gnd", 18.6, 35.7),
    ("/gnd", 19.6, 35.2),
    ("/gnd", 20.6, 35.7),
    ("/gnd", 18.55, 37.35),
    ("/gnd", 10.0, 29.7),
    ("/gnd", 11.0, 28.3),
    ("/gnd", 15.4, 24.4),
    ("/gnd", 18.6, 24.4),
    ("/gnd", 11.8, 47.2),
    ("/gnd", 12.8, 47.2),
    ("/gnd", 18.7, 53.3),
    ("/gnd", 17.2, 60.3),
    ("/gnd", 5.8, 62.05),
    ("/gnd", 6.8, 59.5),
    ("/gnd", 23.6, 8.4),
]

# Ground stitching across the pours, on a rough grid clear of the routed copper.
STITCH = [
    (x, y)
    for y in (10.5, 15.87, 20.5, 25.5)
    for x in (6.5, 12.0, 17.5, 21.0)
] + [(21.0, 30.5), (21.0, 41.5), (12.0, 42.5), (6.5, 40.0), (6.5, 46.0), (5.5, 53.0), (7.0, 55.0), (21.0, 50.4), (12.0, 50.0)]

SILK_KEPT = {"U1", "J1", "J2", "C4", "DC1"}
# PCBWAY prints legend strokes down to 0.15 mm; thinner ones may not appear.
SILK_MIN_STROKE = 0.15

# The back faces outward once the DevKit is plugged in, so labels live there.
TEXT = [
    ("milsblo", 13.33, 20.0, 0, "B.SilkS"),
    ("FAN1", 5.2, 54.4, 0, "B.SilkS"),
    ("FAN2", 21.4, 53.6, 0, "B.SilkS"),
    ("GND >", 6.3, 66.4, 0, "B.SilkS"),
    ("< GND", 21.3, 60.0, 0, "B.SilkS"),
    ("12V DC  CENTRE +", 13.33, 52.3, 0, "B.SilkS"),
    ("BME280", 7.3, 68.0, 0, "F.Fab"),
]

# reference: cathode pad number. The rails run this far either side of the pad
# centre, clear of the pad's solder mask opening.
CATHODE_PAD = {"LED1": "1"}
CATHODE_RAIL_OFFSET, CATHODE_RAIL_LENGTH = 0.8, 1.0


def mm(x, y):
    return pn.VECTOR2I(pn.FromMM(ORIGIN[0] + x), pn.FromMM(ORIGIN[1] + y))


LAYER = {"F.Cu": pn.F_Cu, "B.Cu": pn.B_Cu, "F.SilkS": pn.F_SilkS, "B.SilkS": pn.B_SilkS, "F.Fab": pn.F_Fab}


def place(board):
    for ref, (x, y, rot) in PLACEMENT.items():
        footprint = board.FindFootprintByReference(ref)
        footprint.SetPosition(mm(x, y))
        if footprint.IsFlipped() != (ref in BACK_SIDE):
            footprint.Flip(footprint.GetPosition(), pn.FLIP_DIRECTION_LEFT_RIGHT)
        footprint.SetOrientationDegrees(rot)
        footprint.Reference().SetLayer(pn.B_Fab if ref in BACK_SIDE else pn.F_Fab)
        footprint.Reference().SetVisible(True)
        for pad in footprint.Pads():
            # Reflowed SMD ground pads tie solid to the pour: thermal spokes
            # starve on 0402/0603 pads.
            if pad.GetNetname() == "/gnd" and pad.GetAttribute() == pn.PAD_ATTRIB_SMD:
                # The jack is soldered by hand, where a solid tie to the pour
                # steals the iron's heat.
                hand_soldered = ref in BACK_SIDE
                pad.SetLocalZoneConnection(pn.ZONE_CONNECTION_THERMAL if hand_soldered else pn.ZONE_CONNECTION_FULL)
    missing = {f.GetReference() for f in board.GetFootprints()} - set(PLACEMENT)
    if missing:
        raise SystemExit(f"unplaced footprints: {sorted(missing)}")


def outline(board):
    corners = [(0, 0), (WIDTH, 0), (WIDTH, HEIGHT), (0, HEIGHT)]
    for a, b in zip(corners, corners[1:] + corners[:1]):
        line = pn.PCB_SHAPE(board)
        line.SetShape(pn.SHAPE_T_SEGMENT)
        line.SetStart(mm(*a))
        line.SetEnd(mm(*b))
        line.SetLayer(pn.Edge_Cuts)
        line.SetWidth(pn.FromMM(0.1))
        board.Add(line)
    settings = board.GetDesignSettings()
    settings.SetAuxOrigin(mm(0, HEIGHT))
    settings.SetGridOrigin(mm(0, 0))


def net_of(board, name):
    net = board.FindNet(name)
    if net is None:
        raise SystemExit(f"unknown net {name}")
    return net


def route(board):
    for net, layer, width, points in TRACKS:
        for a, b in zip(points, points[1:]):
            track = pn.PCB_TRACK(board)
            track.SetStart(mm(*a))
            track.SetEnd(mm(*b))
            track.SetWidth(pn.FromMM(width))
            track.SetLayer(LAYER[layer])
            track.SetNet(net_of(board, net))
            board.Add(track)
    for net, x, y in VIAS + [("/gnd", x, y) for x, y in STITCH]:
        via = pn.PCB_VIA(board)
        via.SetViaType(pn.VIATYPE_THROUGH)
        via.SetPosition(mm(x, y))
        via.SetDrill(pn.FromMM(VIA_DRILL))
        via.SetWidth(pn.FromMM(VIA_D))
        via.SetLayerPair(pn.F_Cu, pn.B_Cu)
        via.SetNet(net_of(board, net))
        board.Add(via)


def zone(board, net, layer, points, name, priority=0, clearance=0.2, pad_connection=pn.ZONE_CONNECTION_THERMAL):
    z = pn.ZONE(board)
    z.SetLayer(LAYER[layer])
    z.SetNet(net_of(board, net))
    z.SetZoneName(name)
    z.SetAssignedPriority(priority)
    z.SetLocalClearance(pn.FromMM(clearance))
    z.SetMinThickness(pn.FromMM(0.2))
    z.SetPadConnection(pad_connection)
    z.SetThermalReliefGap(pn.FromMM(0.25))
    z.SetThermalReliefSpokeWidth(pn.FromMM(0.3))
    z.SetIslandRemovalMode(pn.ISLAND_REMOVAL_MODE_ALWAYS)
    outline = z.Outline()
    outline.NewOutline()
    for x, y in points:
        outline.Append(mm(x, y))
    board.Add(z)
    return z


def pours(board):
    edge = 0.0
    rect = [(edge, ANTENNA_KEEPOUT_Y), (WIDTH - edge, ANTENNA_KEEPOUT_Y), (WIDTH - edge, HEIGHT - edge), (edge, HEIGHT - edge)]
    zone(board, "/gnd", "F.Cu", rect, "gnd top")
    zone(board, "/gnd", "B.Cu", rect, "gnd bottom")
    pn.ZONE_FILLER(board).Fill(board.Zones())


def labels(board):
    for text, x, y, rot, layer in TEXT:
        item = pn.PCB_TEXT(board)
        item.SetText(text)
        item.SetPosition(mm(x, y))
        item.SetTextAngleDegrees(rot)
        item.SetLayer(LAYER[layer])
        item.SetMirrored(layer == "B.SilkS")
        item.SetTextSize(pn.VECTOR2I(pn.FromMM(0.9), pn.FromMM(0.9)))
        item.SetTextThickness(pn.FromMM(0.15))
        board.Add(item)


def cathode_marks(board):
    # Silk rails either side of the cathode pad: the LED has no other silk, and
    # the mark on the part itself is on its underside. An end bar, the more
    # common convention, would land on the cathode's ground via.
    for ref, cathode in CATHODE_PAD.items():
        footprint = board.FindFootprintByReference(ref)
        centre, pad = footprint.GetPosition(), footprint.FindPadByNumber(cathode).GetPosition()
        dx, dy = pad.x - centre.x, pad.y - centre.y
        length = (dx * dx + dy * dy) ** 0.5
        ux, uy = dx / length, dy / length
        side, half = pn.FromMM(CATHODE_RAIL_OFFSET), pn.FromMM(CATHODE_RAIL_LENGTH / 2)
        for sign in (1, -1):
            mid_x, mid_y = pad.x - uy * side * sign, pad.y + ux * side * sign
            rail = pn.PCB_SHAPE(board)
            rail.SetShape(pn.SHAPE_T_SEGMENT)
            rail.SetStart(pn.VECTOR2I(round(mid_x - ux * half), round(mid_y - uy * half)))
            rail.SetEnd(pn.VECTOR2I(round(mid_x + ux * half), round(mid_y + uy * half)))
            rail.SetLayer(pn.F_SilkS)
            rail.SetWidth(pn.FromMM(0.2))
            board.Add(rail)


def block_end(text, start):
    depth, end, in_string = 0, start, False
    while True:
        char = text[end]
        if in_string:
            if char == "\\":
                end += 1
            in_string = char != '"'
        elif char == '"':
            in_string = True
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return end + 1
        end += 1


def cut_blocks(text, pattern, keep=lambda block: False):
    out, position = [], 0
    for match in re.finditer(pattern, text, re.M):
        start = match.end() - len(match.group(1))
        if start < position:
            continue
        end = block_end(text, start)
        block = text[start:end]
        if keep(block):
            continue
        out.append(text[position:match.start()])
        position = end + 1 if text[end] == "\n" else end
    return "".join(out) + text[position:]


def widen_silk(footprint):
    # Footprints are stored in the board, so a library change alone never
    # reaches silk that is already placed.
    def widen(match):
        item = match.group(0)
        if '(layer "F.SilkS")' not in item and '(layer "B.SilkS")' not in item:
            return item
        return re.sub(
            r"\(width ([\d.]+)\)",
            lambda width: f"(width {max(float(width.group(1)), SILK_MIN_STROKE):g})",
            item,
        )

    out, position = [], 0
    for match in re.finditer(r"^\t\t\(fp_(?:line|arc|circle|poly|rect)\b", footprint, re.M):
        start = match.start() + 2
        if start < position:
            continue
        end = block_end(footprint, start)
        out.append(footprint[position:start] + widen(re.match(r"(?s).*", footprint[start:end])))
        position = end
    return "".join(out) + footprint[position:]


def strip_generated_items():
    # KiCad 10's Python bindings return unusable objects when board items are
    # iterated, so the previous outline, copper and labels are cut from the
    # file text before loading.
    text = BOARD.read_text(encoding="utf-8")
    text = cut_blocks(text, r"^\t(\((?:gr_\w+|segment|via|arc|zone)\b)")
    # Dense passives have no room for an outline or designator, so only parts
    # whose silk carries orientation keep it.
    out, position = [], 0
    for match in re.finditer(r"^\t\(footprint ", text, re.M):
        start = match.start() + 1
        end = block_end(text, start)
        block = text[start:end]
        ref = re.search(r'\(property\s+"Reference"\s+"([^"]+)"', block).group(1)
        keep_silk = ref in SILK_KEPT
        block = cut_blocks(
            block,
            r"^\t\t(\(fp_(?:line|arc|circle|poly|rect|text)\b)",
            lambda item: '(layer "F.SilkS")' not in item or (keep_silk and "${REFERENCE}" not in item),
        )
        block = widen_silk(block)
        out.append(text[position:start] + block)
        position = end
    text = "".join(out) + text[position:]
    BOARD.write_text(text, encoding="utf-8")


def main():
    strip_generated_items()
    board = pn.LoadBoard(str(BOARD))
    place(board)
    outline(board)
    route(board)
    labels(board)
    cathode_marks(board)
    pours(board)
    pn.SaveBoard(str(BOARD), board)
    print(f"wrote {BOARD}")


if __name__ == "__main__":
    main()
