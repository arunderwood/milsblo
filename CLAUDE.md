# CLAUDE.md — milsblo

> **milsblo** is a USB-C PD powered, ESP32-S3 backpack PCB that controls two 4-pin PWM PC fans and reads a BME280 temperature/humidity sensor. Designed in KiCad, manufactured at PCBWAY.

---

## Project overview

milsblo is a small, single-purpose circuit board that "backpacks" onto an **ESP32-S3-DevKitC-1 v1.1** dev board via female pin headers. A single USB-C cable provides 12V via Power Delivery negotiation, which powers the fans directly and steps down to 5V to feed the ESP32. The ESP32 sends 25kHz PWM directly to the fans' built-in controllers and reads ambient conditions from a BME280 sensor over I2C.

### What this board does

```
USB-C PD charger (65W+)
    │
    ▼
USB-C connector → CH224K (negotiates 12V)
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
- Board dimensions: **shorter** than ESP32-S3-DevKitC-1 (~69mm × 25.5mm). Target ~50–55mm length to avoid antenna keepout zone. Width matches header spacing (~25.5mm) or slightly wider for edge-mounted connectors. **Measure your actual DevKit with calipers before layout.**
- All SMD components on top side (bottom has female headers for the dev board)
- PCBWAY standard capabilities: ≥6 mil trace/space, ≥0.3mm drill, ≥0.15mm annular ring
- Power traces: 12V rail ≥ 40 mil (1mm), 5V rail ≥ 20 mil (0.5mm)

---

## Architecture decisions (already made — do not revisit)

| Subsystem | Component | Package | LCSC Part # | Why |
|-----------|-----------|---------|-------------|-----|
| USB-C PD sink | **CH224K** | ESSOP-10 | C970725 | Standalone 12V selection via single 24kΩ resistor. No MCU firmware needed. **PD 2.0/3.0 only** (no PD 3.1 EPR). Upgrade path: HUSB238 if PD 3.1 needed in future revision. |
| CH224K VDD feed | **1kΩ series + BZT52C5V1** | 0603 + SOD-123 | C21190, C173407 | VDD is an internal 3.3V shunt regulator (3.6V max, 30mA max sink). 1kΩ from 12V gives 8.7mA and 76mW in a 100mW part. The 5.1V Zener never conducts and is optional. |
| Buck converter | **AP63205WU-7** | TSOT-26 | C2071056 | Fixed 5V/2A output, 3.8–32V input, 4 external components. FB connects directly to the output; EN connects to the input. |
| Temp/humidity sensor | **BME280** (external breakout) | — | — | Connected via JST-SH 4-pin Qwiic/STEMMA QT connector on board. |
| USB-C connector | **USB-C 16-pin SMD** | — | C2765186 (or similar) | Needs CC1/CC2 for PD negotiation. **Verify LCSC part C2765186 is in stock and has exposed CC1 and CC2 pads** before layout. If unavailable, search LCSC for "USB-C 16-pin mid-mount SMD" with CC pins. 16 pins is sufficient (no USB 3.x data lines needed). |
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
| **KiBot** | Automated manufacturing file generation | `kibot -c pcbway.kibot.yaml` |
| **ngspice** | SPICE simulation of power and fan circuits | `ngspice -b milsblo_power.cir` |
| **ESPHome** | ESP32 firmware configuration and OTA updates | `esphome run milsblo.yaml` |

---

## Project phases

### Phases 1–2: Library and schematic (complete)

The circuit below is what `elec/kicad/milsblo.kicad_sch` implements and `tools/check_design.py` enforces.

**USB-PD:**
- USB-C CC1/CC2 run directly to the CH224K. Its reference circuits have no external pulldowns.
- CFG1: 24kΩ to GND selects 12V. CFG2 and CFG3 float.
- VDD: 12V → 1kΩ → VDD, with 1µF to GND. VDD is an internal 3.3V shunt regulator (30mA max sink).
- VBUS sense (pin 8): 12V → 10kΩ → pin 8.
- PG is open-drain and active low. It sinks the status LED: VDD → 470Ω → LED → PG. It is not routed to the ESP32.

**Buck converter:**
- AP63205WU-7 is fixed at 5.0V: FB connects directly to the output, with no divider.
- VIN and EN both connect to the 12V rail. PG must not drive EN, because PG is active low.
- 22µF ceramic input cap, 22µF ceramic output cap, 4.7µH inductor, 100nF bootstrap cap between BST and SW. The datasheet's typical circuit shows two 22µF output caps.
- Output → ESP32 DevKit 5V pin through the female header.

**Fan driver (instantiated twice):**
- 4-pin fan header: pin 1 = GND, pin 2 = +12V (always on), pin 3 = Tach (10kΩ pullup to 3.3V → ESP32 GPIO), pin 4 = PWM (100Ω series → ESP32 GPIO).
- No MOSFETs or flyback diodes: the fan's internal controller handles switching.
- 4-pin fans only. A 3-pin fan on this header runs at full speed.

**Sensor port:**
- JST-SH 4-pin: pin 1 = GND, pin 2 = 3.3V, pin 3 = SDA, pin 4 = SCL.
- 4.7kΩ pullups on SDA and SCL to 3.3V, 100nF decoupling on 3.3V.
- 3.3V comes from the DevKit's 3V3 pin through the header.

**Board level:** 100µF electrolytic on the 12V rail near the fan headers, 100nF local VBUS bypass.

### Phase 3: SPICE simulation (optional but recommended)

**Goal:** Verify power regulation and PWM behavior before building hardware.

`simulation/power_chain.cir` models an adjustable 0.6V divider at 1.5MHz, which is not this part: the AP63205 is fixed at 5.0V and switches at 1.1MHz. Do not rely on its buck results.

Write ngspice netlists to test:

1. **CH224K → AP63205 power chain:** Verify 5V output is stable under 500mA load (ESP32 peak). Step input from 0→12V to simulate PD negotiation completing.
2. **Worst-case power budget:** Two fans at 0.3A each + ESP32 at 0.5A = 1.1A at 12V = 13.2W. Verify USB-C PD source provides sufficient power (most 65W chargers handle this easily).

### Phase 4: Breadboard prototype

**Goal:** Validate the circuit works in real life before PCB fabrication.

**Shopping list for breadboard testing:**

| Item | Purpose | Approx cost |
|------|---------|-------------|
| ESP32-S3-DevKitC-1 v1.1 | Dev board | $12–18 |
| CH224K breakout board | PD negotiation test (AliExpress/AnalogLamb) | $2–3 |
| BME280 breakout (GY-BME280) | Sensor testing | $3–5 |
| 12V PC fan (4-pin PWM) | Load testing — **must be 4-pin** | $8–15 |
| Resistor kit (assorted) | 100Ω PWM series, 10kΩ tach pullups, etc. | $5 (kit) |
| Capacitor kit (assorted) | Decoupling | $5 (kit) |
| 65W+ USB-C PD charger | Power source | $15–25 (or use existing) |
| Breadboard + jumper wires | — | $5–10 |

**Testing sequence:**

1. **PD power:** CH224K breakout → verify 12V with multimeter. Do this FIRST and ALONE.
2. **Buck converter:** Wire AP63205 eval circuit (or use a pre-built 12V→5V buck module for breadboard). Verify 5V output.
3. **ESP32 power:** Feed 5V to DevKit VIN. Confirm boot, serial output, WiFi scan.
4. **Sensor:** Wire BME280 breakout to I2C. Run test sketch. Verify temp/humidity readings.
5. **Single fan:** Connect 4-pin fan: pin 1 = GND, pin 2 = 12V, pin 3 = tach (10kΩ pullup to 3.3V), pin 4 = ESP32 GPIO via 100Ω. PWM at 25kHz from ESP32. Verify speed control from 0–100%.
6. **Full integration:** Both fans + sensor + PD power. Run for 30+ minutes. Monitor for thermal issues.

### Phase 5: PCB layout in KiCad

**Goal:** Produce a manufacturable board layout from the KiCad schematic.

This phase is **manual work in KiCad** — layout requires human judgment.

**Layout priorities (in order):**
1. Place female headers first — these define the board outline and must align with the DevKitC-1
2. Place USB-C connector on one end of the board (accessible when backpacked)
3. Place CH224K and AP63205 near the USB-C connector (short high-current paths)
4. AP63205 thermal pad: place ≥4 thermal vias (0.3mm drill) under the exposed pad, connecting to bottom-layer ground pour. This is critical even at 500mA load.
5. Place fan headers on the board edge (accessible for cable routing)
6. Place 100Ω PWM series resistors near the fan headers (short signal traces)
7. Place sensor JST-SH connector on the board edge
8. Route 12V power traces at ≥40 mil width
9. Route 5V traces at ≥20 mil width
10. Fill remaining area with ground copper pour (both layers)
11. Verify antenna keepout: ensure no copper pour or traces within 15mm of the ESP32 module's antenna (the antenna end of the DevKit hangs off one end — your backpack board should be shorter to avoid this zone entirely)

**DRC settings for PCBWAY:**
```
Min trace width: 6 mil (0.15mm)
Min trace spacing: 6 mil (0.15mm)
Min drill: 0.3mm
Min annular ring: 0.15mm
Min hole-to-trace: 0.35mm
```

### Phase 6: Manufacturing file export

**Goal:** Generate PCBWAY-ready Gerber zip.

**Using kicad-cli (preferred for automation):**
```bash
# Run DRC first
kicad-cli pcb drc \
  --exit-code-violations \
  --format json \
  --output drc-report.json \
  elec/kicad/milsblo.kicad_pcb

# Export Gerbers (PCBWAY compatible — NO x2 format)
kicad-cli pcb export gerbers \
  --no-x2 \
  --subtract-soldermask \
  --use-drill-file-origin \
  --layers "F.Cu,B.Cu,F.SilkS,B.SilkS,F.Mask,B.Mask,Edge.Cuts" \
  --output gerbers/ \
  elec/kicad/milsblo.kicad_pcb

# Export drill files
kicad-cli pcb export drill \
  --format excellon \
  --excellon-zeros-format suppressleading \
  --excellon-min-header \
  --output gerbers/ \
  elec/kicad/milsblo.kicad_pcb

# Export BOM for assembly
kicad-cli sch export bom \
  --output milsblo-bom.csv \
  elec/kicad/milsblo.kicad_sch

# Export pick-and-place for assembly
kicad-cli pcb export pos \
  --format csv \
  --units mm \
  --output milsblo-pos.csv \
  elec/kicad/milsblo.kicad_pcb

# Zip for upload
cd gerbers && zip ../milsblo-gerbers.zip * && cd ..
```

**PCBWAY order settings:**
- Layers: 2
- Dimensions: measure from KiCad Edge.Cuts
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
7. **Thermal considerations.** The AP63205 dissipates ~0.5W at full load. Its thermal pad needs vias to a ground copper pour on the bottom layer.
8. **4-pin fans required.** This board is designed for 4-pin PWM fans. 3-pin fans plugged in will run at full speed (no PWM control) since their GND is on pin 1 and the PWM pin 4 will be unconnected.

### Things that must be verified by a human

- Every pin mapping between the schematic and the actual ESP32-S3-DevKitC-1 pinout diagram
- CH224K voltage selection resistor value (24kΩ for 12V). WCH publishes this value for the CH224Q/A and CH224D but no CH224K-specific table, so measure 12V on the breadboard.
- AP63205 inductor value and saturation current rating
- Board outline alignment with DevKitC-1 header spacing (measure your actual board with calipers)
- USB-C connector footprint compatibility with your specific connector part

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
├── tools/check_design.py    ← design check, run locally and in CI
├── firmware/                ← ESPHome configuration
├── simulation/              ← ngspice netlists
└── docs/                    ← breadboard guide, layout preview
```

---

## Start here

The schematic is complete and passes `python3 tools/check_design.py`. The next work is the Phase 4 breadboard, then Phase 5 layout. Do not skip the breadboard prototype — USB-C PD at 12V can damage components if the circuit has errors.
