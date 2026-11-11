# CLAUDE.md — milsblo

> **milsblo** is a 12 V barrel-jack powered, ESP32-S3 backpack PCB that controls two 4-pin PWM PC fans and reads a BME280 temperature/humidity sensor. Designed in KiCad, manufactured at PCBWAY.

---

## Project overview

milsblo is a small, single-purpose circuit board that "backpacks" onto an **ESP32-S3-DevKitC-1 v1.1** dev board via female pin headers. A 12 V DC supply on a 5.5 × 2.1 mm barrel jack powers the fans directly and steps down to 5V to feed the ESP32. The ESP32 sends 25kHz PWM directly to the fans' built-in controllers and reads ambient conditions from a BME280 sensor over I2C.

### What this board does

```
12 V DC supply, centre positive, 1.5 A or more
    │
    ▼
Barrel jack → AO3407A (reverse-polarity protection)
    │
    ├──→ 12V rail ──→ Fan headers × 2 (pin 2, always-on 12V)
    │
    └──→ AP63205 (12V → 5V buck) ──→ ESP32 DevKit VIN pin
                                         │
                                         ├── GPIO PWM × 2 → 100Ω → Fan pin 4 (PWM control)
                                         ├── GPIO × 2 ← Fan pin 3 (tach, 10kΩ pullup)
                                         └── I2C (SDA/SCL) → JST-SH 4-pin → BME280
```

### Design constraints

- **Two-layer PCB**, 1.6mm FR4, 1oz copper
- Board dimensions: **68.5mm × 26.66mm**. J1 and J2 (DevKit J1/J3) are 22.86mm apart per Espressif's v1.1 drawing, and the DevKit is 62.74mm × 25.4mm. The board runs from just past the pin 1 row (stopping before the antenna) to 5mm past the DevKit's USB end, which gives the connectors room.
- Stacking: **DevKit on top.** Sockets and every part except the barrel jack are on this board's top side; the DevKit plugs down into the sockets, so its USB ports, buttons and antenna stay exposed. Tall parts must clear the ~11mm under the DevKit. The jack is 11.0mm tall, so it is on the back.
- PCBWAY standard capabilities: ≥6 mil trace/space, ≥0.3mm drill, ≥0.15mm annular ring
- Power traces: 12V rail ≥ 40 mil (1mm), 5V rail ≥ 20 mil (0.5mm)

---

## Architecture decisions (already made — do not revisit)

| Subsystem | Component | Package | LCSC Part # | Why |
|-----------|-----------|---------|-------------|-----|
| Power input | **DC050-T** barrel jack | SMD, right angle | C431534 | 5.5mm plug, 2.0mm pin, rated 12V 1.5A. Mounted on the back at the bottom edge. A fixed 12V supply needs no negotiation, so any 12V brick works. USB-C PD is not used because 12V is an optional charger profile. |
| Reverse-polarity protection | **AO3407A** P-MOSFET | SOT-23 | C15155 | Barrel plugs come in both polarities. Drain to the jack, source to the 12V rail, gate to ground: 48mΩ when on, so the fans still get 12V. VGS limit is ±20V. |
| Buck converter | **AP63205WU-7** | TSOT-26 | C2071056 | Fixed 5V/2A output, 3.8–32V input, 5 external components (2 × 22µF output). FB connects directly to the output; EN connects to the input. |
| Temp/humidity sensor | **BME280** (external breakout) | — | — | Connected via JST-SH 4-pin Qwiic/STEMMA QT connector on board. |
| Sensor connector | **JST-SH 4-pin** (SM04B-SRSS-TB) | — | C160404 | Qwiic/STEMMA QT compatible: GND, 3.3V, SDA, SCL. |
| Fan headers (×2) | **JST-XH 4-pin** or 2.54mm 4-pin header | Through-hole | — | Standard 4-pin PC fan pinout: GND, +12V, Tach, PWM. Fan's internal controller handles switching. |
| Dev board headers | **2×22-pin female header, 2.54mm** | Through-hole | — | Mates with ESP32-S3-DevKitC-1 male pins. |

### ESP32-S3-DevKitC-1 pin assignments

```
GPIO 4  → Fan 1 PWM (LEDC channel 0, 25kHz)
GPIO 5  → Fan 2 PWM (LEDC channel 1, 25kHz)
GPIO 6  → Fan 1 Tach input (10kΩ pullup to 3.3V)
GPIO 7  → Fan 2 Tach input (10kΩ pullup to 3.3V)
GPIO 8  → I2C SDA (BME280, with 4.7kΩ pullup to 3.3V)
GPIO 9  → I2C SCL (BME280, with 4.7kΩ pullup to 3.3V)
```

> **Note:** GPIOs 4–9 on the ESP32-S3-DevKitC-1 are on the left header, well clear of strapping pins, USB, and JTAG. Verify against the official Espressif pinout before finalizing.

---

## Toolchain

### Primary: KiCad 10

`elec/kicad/` is the design source. The schematic is label-only: every connected pin carries a net label and there are no wires, so connectivity changes read as text diffs.

```bash
python3 tools/check_design.py                  # ERC, schematic parity, connectivity and datasheet rules
python3 tools/check_design.py --update-golden  # accept a connectivity change after reviewing it
python3 -m unittest discover -s tools          # prove each rule fails on a deliberate error
```

- Run `tools/check_design.py` after every schematic change. It uses only the Python standard library and is the same check CI runs in the `kicad/kicad:10.0.8` image.
- Parts live in the project library, `elec/kicad/library/`. Every BOM part carries an `LCSC Part` field.
- `kicad-cli` has no update-PCB command. Sync with Update PCB from Schematic in KiCad (re-link by reference designator on, replace footprints off), then confirm the check still passes.
- `elec/preserved/default.net` is the last atopile netlist, kept for reference only. Its circuit contains the errors corrected in the KiCad schematic.

### Secondary tools

| Tool | Purpose | Command |
|------|---------|---------|
| **KiCad 10.x** | Schematic, PCB layout, routing, DRC, Gerber export | Open `elec/kicad/milsblo.kicad_pro` |
| **kicad-cli** | Headless DRC and Gerber export | `kicad-cli pcb drc`, `kicad-cli pcb export gerbers` |
| **ngspice** | SPICE simulation of power and fan circuits | `ngspice -b simulation/power_chain.cir` |
| **ESPHome** | ESP32 firmware configuration and OTA updates | `esphome run milsblo.yaml` |

---

## Project phases

### Phases 1–2: Library and schematic (complete)

The circuit below is what `elec/kicad/milsblo.kicad_sch` implements and `tools/check_design.py` enforces.

**Power input:**
- Jack centre pin → net `vin` → Q1 drain. Q1 source → 12V rail. Q1 gate → GND. Nothing else connects to `vin`.
- Jack sleeve (pad 4) and switch contact (pad 3) both go to GND.
- A centre-negative supply leaves Q1 off with its body diode reverse biased, so the board stays unpowered and undamaged.
- Q1's gate sees the full supply voltage, so the input limit is 20V. The 12V-rail capacitors are rated 25V or more.
- Power LED: 12V → 4.7kΩ → LED → GND (about 2mA).

**Buck converter:**
- AP63205WU-7 is fixed at 5.0V: FB connects directly to the output, with no divider.
- VIN and EN both connect to the 12V rail.
- 22µF ceramic input cap, two 22µF ceramic output caps, 4.7µH inductor, 100nF bootstrap cap between BST and SW.
- Output → ESP32 DevKit 5V pin through the female header.

**Fan driver (instantiated twice):**
- 4-pin fan header: pin 1 = GND, pin 2 = +12V (always on), pin 3 = Tach (10kΩ pullup to 3.3V → ESP32 GPIO), pin 4 = PWM (100Ω series → ESP32 GPIO).
- No MOSFETs or flyback diodes: the fan's internal controller handles switching.
- 4-pin fans only. A 3-pin fan on this header runs at full speed.

**Sensor port:**
- JST-SH 4-pin: pin 1 = GND, pin 2 = 3.3V, pin 3 = SDA, pin 4 = SCL.
- 4.7kΩ pullups on SDA and SCL to 3.3V, 100nF decoupling on 3.3V.
- 3.3V comes from the DevKit's 3V3 pin through the header.

**Board level:** 100µF electrolytic on the 12V rail near the fan headers, 100nF bypass on the 12V rail at Q1.

### Phase 3: SPICE simulation (complete)

`simulation/` covers what has a usable model: ripple on the 5V rail and the fan PWM signal path. The AP63205 has no public SPICE model, so its output voltage, stability and load-step response come from the datasheet and from measuring the board. See `simulation/README.md` for results.

**Worst-case power budget:** two fans at 0.3A each, plus the ESP32 at 0.5A on 5V (about 0.25A from the 12V rail through the buck) = 0.85A at 12V, about 10W. The jack is rated 1.5A; use a 12V supply rated 1.5A or more.

### Phase 4: Breadboard prototype

**Goal:** Validate the circuit works in real life before PCB fabrication.

**Shopping list for breadboard testing:**

| Item | Purpose | Approx cost |
|------|---------|-------------|
| ESP32-S3-DevKitC-1 v1.1 | Dev board | $12–18 |
| BME280 breakout (GY-BME280) | Sensor testing | $3–5 |
| 12V PC fan (4-pin PWM) | Load testing — **must be 4-pin** | $8–15 |
| Resistor kit (assorted) | 100Ω PWM series, 10kΩ tach pullups, etc. | $5 (kit) |
| Capacitor kit (assorted) | Decoupling | $5 (kit) |
| 12V DC supply, 1.5A+, 5.5 × 2.1mm centre-positive plug | Power source | $8–12 (or use existing) |
| Breadboard + jumper wires | — | $5–10 |

**Testing sequence:**

1. **12V supply:** measure the plug with a multimeter before connecting anything: 11.4–12.6V, centre positive. Do this FIRST and ALONE. Unregulated bricks read high with no load; anything over 15V is the wrong supply.
2. **Buck converter:** Wire AP63205 eval circuit (or use a pre-built 12V→5V buck module for breadboard). Verify 5V output.
3. **ESP32 power:** Feed 5V to DevKit VIN. Confirm boot, serial output, WiFi scan.
4. **Sensor:** Wire BME280 breakout to I2C. Run test sketch. Verify temp/humidity readings.
5. **Single fan:** Connect 4-pin fan: pin 1 = GND, pin 2 = 12V, pin 3 = tach (10kΩ pullup to 3.3V), pin 4 = ESP32 GPIO via 100Ω. PWM at 25kHz from ESP32. Verify speed control from 0–100%.
6. **Full integration:** Both fans + sensor + the 12V supply. Run for 30+ minutes. Monitor for thermal issues.

### Phase 5: PCB layout in KiCad (complete)

The layout is generated: `tools/layout_board.py` holds the outline, placement, every copper path and the pours, so a layout change is a reviewable diff. It needs the Python inside KiCad, because it uses pcbnew:

```bash
/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3 tools/layout_board.py
python3 tools/check_design.py
```

KiCad's board editor and this script both write `elec/kicad/milsblo.kicad_pcb`. After a hand edit, port the change to the script, or the next regeneration loses it.

**Layout facts `check_design.py` enforces:**
- Board DRC with 0 violations and 0 unconnected at every severity, using the PCBWAY rules in the project and `elec/kicad/milsblo.kicad_dru`.
- 12V tracks at 1.016mm (40 mil) or more, including the `vin` run from the jack to Q1, and 5V at 0.508mm (20 mil) or more. No supply rail runs through a zone.
- Sockets 22.86mm apart, pin 1 at the antenna end, on the top side.
- Antenna: the board stops at the pin 1 row, and no pour, via or routing is allowed in the first 6mm below it except the 3.3V and ground stubs from pins 1 and 2 that the header forces.
- Barrel jack on the back with its mouth at the bottom edge, JST-SH on the bottom edge, fan headers on the left and right edges.
- Decoupling within 5mm of the parts they serve, and ground pours on both layers with stitching vias.

The AP63205 is TSOT-26, with no exposed pad. Its input capacitor sits on pins 3 and 4, and ground vias sit at the capacitor and pin 4 to reach the bottom-layer pour.

**DRC settings for PCBWAY (in the project):**
```
Min trace width: 6 mil (0.15mm)
Min trace spacing: 6 mil (0.15mm)
Min drill: 0.3mm
Min annular ring: 0.15mm
Min hole-to-trace: 0.35mm
```

### Phase 6: Manufacturing file export

**Goal:** Generate PCBWAY-ready Gerber zip.

```bash
tools/export_fab.sh
```

This writes `elec/build/fab/milsblo-gerbers.zip` (Gerbers, separate PTH and NPTH drill files), `milsblo-bom.csv` and `milsblo-pos.csv`, with the drill origin at the bottom-left board corner so positions are positive. CI runs it too. The position file covers the top side only: the jack on the back is soldered by hand, like the sockets and fan headers.

**PCBWAY order settings:**
- Layers: 2
- Dimensions: 68.5mm × 26.66mm
- Thickness: 1.6mm
- Copper weight: 1oz
- Surface finish: HASL (cheapest) or ENIG (if hand-soldering fine-pitch)
- Solder mask: green (fastest) or black (aesthetic)
- Silkscreen: white
- Min order: 5 pcs (~$5 + shipping)

### Phase 7: ESPHome configuration

**Goal:** ESPHome YAML configuration for fan control, sensor reading, and Home Assistant integration.

```
firmware/
└── milsblo.yaml        # ESPHome configuration
```

**milsblo.yaml:**
```yaml
esphome:
  name: milsblo
  friendly_name: Milsblo Fan Controller
  platformio_options:
    board_build.flash_mode: dio

esp32:
  board: esp32-s3-devkitc-1
  framework:
    type: arduino

# Enable logging
logger:

# Enable Home Assistant API
api:
  encryption:
    key: !secret milsblo_api_key

ota:
  - platform: esphome
    password: !secret milsblo_ota_password

wifi:
  ssid: !secret wifi_ssid
  password: !secret wifi_password

  # Enable fallback hotspot in case wifi connection fails
  ap:
    ssid: "Milsblo Fallback Hotspot"
    password: !secret milsblo_ap_password

# Web server for debugging (optional, disable for production)
web_server:
  port: 80

# I2C bus for BME280
i2c:
  sda: GPIO8
  scl: GPIO9
  scan: true

# BME280 sensor
sensor:
  - platform: bme280_i2c
    temperature:
      name: "Temperature"
      filters:
        - offset: -1.0  # Compensate for self-heating
      accuracy_decimals: 1
    pressure:
      name: "Pressure"
      accuracy_decimals: 0
    humidity:
      name: "Humidity"
      accuracy_decimals: 0
    address: 0x76
    update_interval: 30s

  # Fan 1 tach
  - platform: pulse_counter
    pin:
      number: GPIO6
      mode:
        input: true
        pullup: true
    name: "Fan 1 Speed"
    unit_of_measurement: 'RPM'
    filters:
      - multiply: 0.5  # Most PC fans output 2 pulses per revolution
    count_mode:
      rising_edge: INCREMENT
      falling_edge: DISABLE
    update_interval: 10s

  # Fan 2 tach
  - platform: pulse_counter
    pin:
      number: GPIO7
      mode:
        input: true
        pullup: true
    name: "Fan 2 Speed"
    unit_of_measurement: 'RPM'
    filters:
      - multiply: 0.5
    count_mode:
      rising_edge: INCREMENT
      falling_edge: DISABLE
    update_interval: 10s

# PWM outputs for fan control
output:
  - platform: ledc
    pin: GPIO4
    frequency: 25000 Hz
    id: fan1_pwm

  - platform: ledc
    pin: GPIO5
    frequency: 25000 Hz
    id: fan2_pwm

# Fan control entities
fan:
  - platform: speed
    output: fan1_pwm
    name: "Fan 1"

  - platform: speed
    output: fan2_pwm
    name: "Fan 2"

```

**Key ESPHome features:**
- **LEDC PWM** on GPIO 4 and 5 at 25kHz (silent operation)
- **Pulse counter** tach reading on GPIO 6 and 7 with 10-second sampling windows
- **BME280 I2C** sensor with -1°C offset correction for self-heating
- **Fan entities** with native Home Assistant speed control (0-100%)
- **Web UI** at `http://milsblo.local` for debugging
- **Native Home Assistant integration** via API
- **OTA updates** for wireless firmware upgrades
- **Fallback AP mode** if WiFi fails

**Note on tach accuracy:** With 4-pin fans, GND is directly connected (no floating), so tach pulses are clean at all duty cycles. ESPHome's pulse_counter should give accurate RPM readings across the full 0–100% speed range.

**secrets.yaml** (create in same directory):
```yaml
wifi_ssid: "YourSSID"
wifi_password: "YourPassword"
milsblo_api_key: "generate-with-esphome"
milsblo_ota_password: "generate-with-esphome"
milsblo_ap_password: "fallback-password"
```

**Installation:**
```bash
# Install ESPHome
pip install esphome

# Compile and upload (first time via USB)
esphome run milsblo.yaml

# Future updates via OTA
esphome run milsblo.yaml --device milsblo.local
```

---

## Important warnings

### Things Claude gets wrong in hardware design

Based on documented failures from AI-assisted PCB projects:

1. **Power trace widths.** Claude defaults to minimum trace width for everything. 12V at 1A needs ≥40 mil traces. Always verify.
2. **Forgotten connections.** Claude may generate component modules but forget to wire them together at the top level. Run `python3 tools/check_design.py` after every schematic change.
3. **Wrong passive values.** Claude has chosen 330Ω where 10kΩ was needed. Cross-reference every resistor/capacitor value against the relevant datasheet.
4. **Missing decoupling caps.** Every IC needs a 100nF ceramic cap within 5mm of its power pins. Claude often forgets these.
5. **Antenna keepout.** The ESP32-S3 module has a PCB antenna that requires 15mm clearance. Your backpack board should NOT extend under the antenna.
6. **Ground pours.** Claude doesn't do layout, but when you do it manually, ensure solid ground planes on both layers with adequate stitching vias.
7. **Thermal considerations.** The AP63205 dissipates ~0.5W at full load. It is TSOT-26 with no exposed pad, so heat leaves through its pins into the ground pour; its datasheet recommends 2oz copper and this board is 1oz.
8. **4-pin fans required.** This board is designed for 4-pin PWM fans. 3-pin fans plugged in will run at full speed (no PWM control) since their GND is on pin 1 and the PWM pin 4 will be unconnected.

### Things that must be verified by a human

- Every pin mapping between the schematic and the actual ESP32-S3-DevKitC-1 pinout diagram
- Supply polarity and voltage: measure the plug before first use. Q1 blocks a reversed supply, but nothing stops a 19V laptop brick from reaching the fans.
- AP63205 inductor value and saturation current rating
- DevKit pin-to-edge dimensions and the real socket height (calipers on a real DevKit), including the antenna-end overhang
- A real fan plug on the A2541WR-4P header: it has no key, so a plug can go on reversed
- The barrel jack footprint against a real DC050-T: it was drawn from the SHOU HAN drawing, not from a tested library part. Check the two locating pegs and the four pads before soldering.
- That the jack on the back suits the enclosure: it stands 11mm off the back of the board.

---

## File structure

```
milsblo/
├── CLAUDE.md               ← this file
├── elec/
│   ├── kicad/               ← KiCad project: the design source
│   │   ├── milsblo.kicad_pro
│   │   ├── milsblo.kicad_sch
│   │   ├── milsblo.kicad_pcb
│   │   ├── connectivity.golden
│   │   └── library/
│   └── preserved/default.net
├── tools/                   ← design check, its tests, layout generator, fab export
├── firmware/                ← ESPHome configuration
├── simulation/              ← ngspice netlists
└── docs/                    ← breadboard guide, layout preview
```

---

## Start here

The schematic and layout are complete and pass `python3 tools/check_design.py`. The next work is the Phase 4 breadboard, then an order from `elec/build/fab/`. Do not skip the breadboard prototype — 12V can damage components if the circuit has errors.
