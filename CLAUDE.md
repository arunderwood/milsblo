# CLAUDE.md — milsblo

> **milsblo** is a USB-C PD powered, ESP32-S3 backpack PCB that controls two 4-pin PWM PC fans and reads a BME280 temperature/humidity sensor. Designed in Atopile, manufactured at PCBWAY.

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
| Buck converter | **AP63205WU-7** | TSOT-26 | C2071056 | Fixed 5V/2A output, 3.8–32V input, 4 external components. |
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
GPIO 10 → CH224K PG (Power Good) input, optional status LED
```

> **Note:** GPIOs 4–10 on the ESP32-S3-DevKitC-1 are on the left header, well clear of strapping pins, USB, and JTAG. Verify against the official Espressif pinout before finalizing.

---

## Toolchain

### Primary: Atopile (code-first circuit design)

Atopile is a Python-like DSL that compiles `.ato` files into KiCad projects. We chose it because:

- It has the largest community among code-first EDA tools (~2,600 GitHub stars)
- An ESP32-S3 board has been designed, manufactured, and proven to work via Atopile + Claude
- Its constraint solver auto-selects passive components from JLCPCB's catalog
- CLI-driven workflow (`ato build`, `ato create part`) works naturally from this terminal

**Install:** `uv pip install "atopile>=0.12,<0.13"` (pin to v0.12.x stable series; v0.14+ is a core rewrite — test before upgrading. Requires Python 3.11+)

**Key commands:**
```bash
ato create project milsblo        # scaffold new project
ato create part -s <LCSC_ID>      # create component from LCSC part number
ato build                          # compile → KiCad project in build/
ato install <package>              # install community packages
```

**Language quick reference for this project:**
```ato
# Modules define reusable circuit blocks
module FanDriver:
    r_pwm = new Resistor   # 100Ω PWM series protection

    r_pwm.value = 100ohm +/- 5%

    # Connections use the ~ operator
    signal pwm_in          # from ESP32 GPIO
    signal fan_gnd         # board GND (direct, no switching)
    signal fan_12v         # 12V rail (always-on)
    signal fan_tach        # tach output to ESP32 GPIO
    signal fan_pwm_out     # to fan pin 4

    pwm_in ~ r_pwm.p1; r_pwm.p2 ~ fan_pwm_out
    # No MOSFETs or flyback diodes — fan's internal controller handles switching

# Top-level board module composes subsystems
module Milsblo:
    # Power
    usb_c = new USB_C_Connector
    pd_sink = new CH224K
    buck = new AP63205

    # Fan channels (4-pin PWM, no MOSFETs needed)
    fan1 = new FanDriver
    fan2 = new FanDriver

    # Sensor
    sensor_conn = new JST_SH_4pin

    # Dev board
    esp32_headers = new DevKitC1_Headers
```

### Secondary tools

| Tool | Purpose | Command |
|------|---------|---------|
| **KiCad 9.x** | PCB layout, routing, DRC, Gerber export | Open `build/default/milsblo.kicad_pro` after `ato build` |
| **kicad-cli** | Headless DRC and Gerber export | `kicad-cli pcb drc`, `kicad-cli pcb export gerbers` |
| **KiBot** | Automated manufacturing file generation | `kibot -c pcbway.kibot.yaml` |
| **ngspice** | SPICE simulation of power and fan circuits | `ngspice -b milsblo_power.cir` |
| **ESPHome** | ESP32 firmware configuration and OTA updates | `esphome run milsblo.yaml` |

---

## Project phases

### Phase 1: Atopile project setup and component creation

**Goal:** Scaffold the project, create all custom component definitions, verify they compile.

1. `ato create project milsblo && cd milsblo`
2. Create custom parts that aren't in the Atopile ecosystem:
   - `ato create part -s C970725` → CH224K (verify pin mapping against datasheet)
   - `ato create part -s C2071056` → AP63205WU-7
   - USB-C connector (C2765186 or find suitable 16-pin mid-mount)
   - JST-SH 4-pin connector (C160404)
   - JST-XH 4-pin headers or standard 2.54mm 4-pin headers for fans
   - Note: AO3400A and SS14 are NOT needed (4-pin fans have internal controllers)
3. Install any available community packages:
   - Check `packages.atopile.io` for existing generic resistor/capacitor packages
   - `ato install generics` if available
4. Verify: `ato build` should compile with no errors (even if connections aren't wired yet)

**Deliverable:** Project compiles. All component footprints are assigned and valid.

### Phase 2: Schematic entry in Atopile

**Goal:** Write the complete circuit as `.ato` modules, compile to KiCad.

Create modular circuit blocks:

```
milsblo/
├── elec/
│   └── src/
│       ├── milsblo.ato          # top-level board module
│       ├── power/
│       │   ├── usb_pd.ato       # CH224K + USB-C connector + CC resistors
│       │   └── buck_5v.ato      # AP63205 + inductor + caps
│       ├── fan/
│       │   └── fan_driver.ato   # 4-pin PWM header + 100Ω PWM resistor + tach pullup (reused ×2)
│       └── sensor/
│           └── sensor_port.ato  # JST-SH connector + I2C pullups
├── ato.yaml
└── build/                        # generated by ato build
```

**Circuit details to implement:**

**USB-PD (usb_pd.ato):**
- USB-C connector with 5.1kΩ pulldowns on CC1/CC2 (required for PD)
- CH224K wired per datasheet: VBUS → VIN, 24kΩ from CFG1 to GND (selects 12V)
- 1µF decoupling cap on VDD
- PG (Power Good) output routed to ESP32 GPIO 10

**Buck converter (buck_5v.ato):**
- AP63205WU-7: VIN from 12V rail, EN tied to CH224K PG (power sequencing)
- 22µF ceramic input cap, 22µF ceramic output cap, 4.7µH inductor, 100nF bootstrap cap
- BST pin → bootstrap cap → SW pin
- Output → ESP32 DevKit VIN pin through the female header

**Fan driver (fan_driver.ato) — instantiate twice:**
- 4-pin fan header: pin 1 = GND (board GND, direct), pin 2 = +12V (direct from 12V rail, always-on), pin 3 = Tach (10kΩ pullup to 3.3V → ESP32 GPIO), pin 4 = PWM (100Ω series → ESP32 GPIO)
- No MOSFETs or flyback diodes — the fan's internal controller handles all PWM switching
- 100Ω series resistor on PWM pin 4 for GPIO protection only
- Tach line: 10kΩ pullup to 3.3V, routed to ESP32 GPIO 6/7
- ESP32 3.3V GPIO drives pin 4 directly (4-pin fans accept 3.3V logic as valid high)
- **Fan compatibility:** 4-pin fans only. 3-pin fans plugged into a 4-pin header will run at full speed (PWM pin unconnected to 3-pin fan).

**Sensor port (sensor_port.ato):**
- JST-SH 4-pin: pin 1 = GND, pin 2 = 3.3V, pin 3 = SDA, pin 4 = SCL
- 4.7kΩ pullups on SDA and SCL to 3.3V
- 100nF decoupling cap on 3.3V pin
- Note: 3.3V comes from the ESP32 dev board's 3V3 output pin through the header
- Total external 3.3V draw: ~5mA (pullups + sensor). Well within ESP32-S3-DevKitC-1's onboard 3.3V regulator capacity (~500mA available minus ~200mA for ESP32 SoC).

**Top-level (milsblo.ato):**
- Compose all submodules
- Map signals to ESP32 header pins per the pin assignment table above
- Add board-level decoupling: 100µF electrolytic on 12V rail near fan headers

**Validation:** `ato build` compiles cleanly. Open `build/default/milsblo.kicad_pro` in KiCad and visually inspect the schematic for correctness.

### Phase 3: SPICE simulation (optional but recommended)

**Goal:** Verify power regulation and PWM behavior before building hardware.

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

**Goal:** Produce a manufacturable board layout from the Atopile-generated schematic.

This phase is **manual work in KiCad** — Atopile generates the schematic and netlist, but layout requires human judgment.

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
  build/default/milsblo.kicad_pcb

# Export Gerbers (PCBWAY compatible — NO x2 format)
kicad-cli pcb export gerbers \
  --no-x2 \
  --subtract-soldermask \
  --use-drill-file-origin \
  --layers "F.Cu,B.Cu,F.SilkS,B.SilkS,F.Mask,B.Mask,Edge.Cuts" \
  --output gerbers/ \
  build/default/milsblo.kicad_pcb

# Export drill files
kicad-cli pcb export drill \
  --format excellon \
  --excellon-zeros-format suppressleading \
  --excellon-min-header \
  --output gerbers/ \
  build/default/milsblo.kicad_pcb

# Export BOM for assembly
kicad-cli sch export bom \
  --output milsblo-bom.csv \
  build/default/milsblo.kicad_sch

# Export pick-and-place for assembly
kicad-cli pcb export pos \
  --format csv \
  --units mm \
  --output milsblo-pos.csv \
  build/default/milsblo.kicad_pcb

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

# Optional: Power Good status from CH224K
binary_sensor:
  - platform: gpio
    pin:
      number: GPIO10
      mode:
        input: true
    name: "USB-C PD Power Good"
    device_class: power
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
2. **Forgotten connections.** Claude may generate component modules but forget to wire them together at the top level. Verify every net in the schematic after `ato build`.
3. **Wrong passive values.** Claude has chosen 330Ω where 10kΩ was needed. Cross-reference every resistor/capacitor value against the relevant datasheet.
4. **Missing decoupling caps.** Every IC needs a 100nF ceramic cap within 5mm of its power pins. Claude often forgets these.
5. **Antenna keepout.** The ESP32-S3 module has a PCB antenna that requires 15mm clearance. Your backpack board should NOT extend under the antenna.
6. **Ground pours.** Claude doesn't do layout, but when you do it manually, ensure solid ground planes on both layers with adequate stitching vias.
7. **Thermal considerations.** The AP63205 dissipates ~0.5W at full load. Its thermal pad needs vias to a ground copper pour on the bottom layer.
8. **4-pin fans required.** This board is designed for 4-pin PWM fans. 3-pin fans plugged in will run at full speed (no PWM control) since their GND is on pin 1 and the PWM pin 4 will be unconnected.

### Things that must be verified by a human

- Every pin mapping between Atopile code and the actual ESP32-S3-DevKitC-1 pinout diagram
- CH224K voltage selection resistor value (24kΩ for 12V — verify against YOUR charger's PD capabilities)
- AP63205 inductor value and saturation current rating
- Board outline alignment with DevKitC-1 header spacing (measure your actual board with calipers)
- USB-C connector footprint compatibility with your specific connector part

---

## File structure after setup

```
milsblo/
├── CLAUDE.md               ← this file
├── elec/                    ← Atopile circuit design
│   ├── ato.yaml
│   └── src/
│       ├── milsblo.ato
│       ├── power/
│       ├── fan/
│       └── sensor/
├── firmware/                ← ESPHome configuration
│   ├── milsblo.yaml
│   └── secrets.yaml
├── simulation/              ← ngspice netlists
│   ├── power_chain.cir
│   └── fan_driver.cir
├── manufacturing/           ← PCBWAY-ready outputs
│   ├── gerbers/
│   ├── milsblo-bom.csv
│   └── milsblo-pos.csv
├── docs/                    ← breadboard photos, schematic PDFs, notes
│   ├── breadboard-test.md
│   └── schematic.pdf
└── build/                   ← Atopile output (generated, gitignored)
    └── default/
        ├── milsblo.kicad_pro
        ├── milsblo.kicad_sch
        └── milsblo.kicad_pcb
```

---

## Start here

Begin with **Phase 1**. Run:

```bash
uv pip install "atopile>=0.12,<0.13"
ato create project milsblo
cd milsblo
```

Then create the CH224K part definition from LCSC C970725 and verify it compiles. Proceed sequentially through the phases. Do not skip the breadboard prototype — USB-C PD at 12V can damage components if the circuit has errors.
