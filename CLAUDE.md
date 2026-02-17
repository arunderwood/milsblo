# CLAUDE.md — milsblo

> **milsblo** is a USB-C PD powered, ESP32-S3 backpack PCB that controls two 3-wire PC fans with PWM and reads a BME280 temperature/humidity sensor. Designed in Atopile, manufactured at PCBWAY.

---

## Project overview

milsblo is a small, single-purpose circuit board that "backpacks" onto an **ESP32-S3-DevKitC-1 v1.1** dev board via female pin headers. A single USB-C cable provides 12V via Power Delivery negotiation, which powers the fans directly and steps down to 5V to feed the ESP32. The ESP32 controls fan speed via low-side MOSFET PWM switching and reads ambient conditions from a BME280 sensor over I2C.

### What this board does

```
USB-C PD charger (65W+)
    │
    ▼
USB-C connector → CH224K (negotiates 12V)
    │
    ├──→ 12V rail ──→ AO3400 MOSFET × 2 ──→ Fan headers × 2
    │
    └──→ AP63205 (12V → 5V buck) ──→ ESP32 DevKit VIN pin
                                         │
                                         ├── GPIO PWM × 2 → MOSFET gates
                                         ├── GPIO × 2 ← Fan tach inputs
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
| Buck converter | **AP63205WU-7** | TSOT-26 | C2890835 | Fixed 5V/2A output, 3.8–32V input, 4 external components. |
| Fan MOSFET (×2) | **AO3400A** | SOT-23 | C20917 | 30V/5.8A, 52mΩ RDS(on) at 2.5V Vgs. Fully on at 3.3V logic. |
| Flyback diode (×2) | **SS14** | SMA | C2480 | 40V/1A Schottky. Protects MOSFET from inductive kickback. |
| Temp/humidity sensor | **BME280** (external breakout) | — | — | Connected via JST-SH 4-pin Qwiic/STEMMA QT connector on board. |
| USB-C connector | **USB-C 16-pin SMD** | — | C2765186 (or similar) | Needs CC1/CC2 for PD negotiation. **Verify LCSC part C2765186 is in stock and has exposed CC1 and CC2 pads** before layout. If unavailable, search LCSC for "USB-C 16-pin mid-mount SMD" with CC pins. 16 pins is sufficient (no USB 3.x data lines needed). |
| Sensor connector | **JST-SH 4-pin** (SM04B-SRSS-TB) | — | C160404 | Qwiic/STEMMA QT compatible: GND, 3.3V, SDA, SCL. |
| Fan headers (×2) | **JST-XH 3-pin** or 2.54mm pin header | Through-hole | — | Standard PC fan pinout: GND, 12V(switched), Tach. |
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
    mosfet = new AO3400A
    diode = new SS14
    r_gate = new Resistor
    r_pulldown = new Resistor
    
    r_gate.value = 100ohm +/- 5%
    r_pulldown.value = 10kohm +/- 5%
    
    # Connections use the ~ operator
    signal pwm_in
    signal fan_power
    signal fan_gnd
    signal fan_tach
    
    pwm_in ~ r_gate.p1; r_gate.p2 ~ mosfet.gate
    mosfet.source ~ fan_gnd
    mosfet.drain ~ diode.anode; diode.cathode ~ fan_power
    r_pulldown.p1 ~ mosfet.gate; r_pulldown.p2 ~ fan_gnd

# Top-level board module composes subsystems
module Milsblo:
    # Power
    usb_c = new USB_C_Connector
    pd_sink = new CH224K
    buck = new AP63205
    
    # Fan channels
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
| **PlatformIO** | ESP32 firmware build and flash | `pio run -t upload` |

---

## Project phases

### Phase 1: Atopile project setup and component creation

**Goal:** Scaffold the project, create all custom component definitions, verify they compile.

1. `ato create project milsblo && cd milsblo`
2. Create custom parts that aren't in the Atopile ecosystem:
   - `ato create part -s C970725` → CH224K (verify pin mapping against datasheet)
   - `ato create part -s C2890835` → AP63205WU-7
   - `ato create part -s C20917` → AO3400A
   - `ato create part -s C2480` → SS14
   - USB-C connector (C2765186 or find suitable 16-pin mid-mount)
   - JST-SH 4-pin connector
   - JST-XH 3-pin headers or standard 2.54mm 3-pin headers for fans
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
│       │   └── fan_driver.ato   # AO3400 + flyback + gate resistors (reused ×2)
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
- AO3400A: gate via 100Ω series resistor from ESP32 PWM GPIO
- 10kΩ gate-to-source pulldown (keeps fan off during boot/reset)
- SS14 flyback diode: cathode to 12V, anode to MOSFET drain
- Fan header: pin 1 = Fan GND (connects to MOSFET drain — switched), pin 2 = +12V (direct from 12V rail — always on), pin 3 = tach
- Tach line: 10kΩ pullup to 3.3V, routed to ESP32 GPIO
- **Tach with low-side PWM:** The tach output is referenced to the fan's GND pin (MOSFET drain), which floats during PWM off-time. Tach pulses are only valid during PWM on-time. Firmware should sample tach during on-periods, or run fans at 100% briefly to get accurate RPM readings.

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
2. **Fan driver PWM:** Verify AO3400 switching at 25kHz with 12V drain supply. Check gate rise/fall times with 100Ω series resistor. Verify flyback diode clamps drain voltage during turn-off.
3. **Worst-case power budget:** Two fans at 0.3A each + ESP32 at 0.5A = 1.1A at 12V = 13.2W. Verify USB-C PD source provides sufficient power (most 65W chargers handle this easily).

### Phase 4: Breadboard prototype

**Goal:** Validate the circuit works in real life before PCB fabrication.

**Shopping list for breadboard testing:**

| Item | Purpose | Approx cost |
|------|---------|-------------|
| ESP32-S3-DevKitC-1 v1.1 | Dev board | $12–18 |
| CH224K breakout board | PD negotiation test (AliExpress/AnalogLamb) | $2–3 |
| IRLZ44N MOSFET (TO-220) | Breadboard-friendly substitute for AO3400 | $1–2 |
| BME280 breakout (GY-BME280) | Sensor testing | $3–5 |
| 12V PC fan (any 3-wire) | Load testing | $5–10 |
| SS14 diode | Flyback protection | $0.50 |
| Resistor kit (assorted) | Gate resistors, pullups, pulldowns | $5 (kit) |
| Capacitor kit (assorted) | Decoupling | $5 (kit) |
| 65W+ USB-C PD charger | Power source | $15–25 (or use existing) |
| Breadboard + jumper wires | — | $5–10 |

**Testing sequence:**

1. **PD power:** CH224K breakout → verify 12V with multimeter. Do this FIRST and ALONE.
2. **Buck converter:** Wire AP63205 eval circuit (or use a pre-built 12V→5V buck module for breadboard). Verify 5V output.
3. **ESP32 power:** Feed 5V to DevKit VIN. Confirm boot, serial output, WiFi scan.
4. **Sensor:** Wire BME280 breakout to I2C. Run test sketch. Verify temp/humidity readings.
5. **Single fan:** Wire IRLZ44N with gate resistor + pulldown. PWM from ESP32. Verify speed control from 0–100%. Listen for audible whine (adjust frequency if needed).
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
6. Place AO3400 MOSFETs near their respective fan headers
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

### Phase 7: ESP32 firmware

**Goal:** PlatformIO project with fan control, sensor reading, and web UI.

```
firmware/
├── platformio.ini
├── src/
│   └── main.cpp
├── include/
│   └── config.h
└── data/               # SPIFFS web UI files
    └── index.html
```

**platformio.ini:**
```ini
[env:esp32s3]
platform = espressif32
board = esp32-s3-devkitc-1
framework = arduino
monitor_speed = 115200
lib_deps =
    adafruit/Adafruit BME280 Library
    adafruit/Adafruit Unified Sensor
    me-no-dev/ESPAsyncWebServer
    me-no-dev/AsyncTCP
```

**Key firmware features:**
- 25kHz LEDC PWM on GPIO 4 and 5
- Tach reading via pulse counting on GPIO 6 and 7 (interrupt-driven)
- BME280 forced-mode reads every 30 seconds (avoids self-heating). Apply ~1°C temperature offset correction in firmware — BME280 reads 1–2°C high due to internal self-heating even in forced mode. Use a 3.3V-only breakout to minimize this.
- Simple async web server for fan speed control and sensor dashboard
- Optional: MQTT for Home Assistant integration (relevant for your HA setup)
- Optional: mDNS at `milsblo.local`

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
├── firmware/                ← PlatformIO ESP32 project
│   ├── platformio.ini
│   └── src/
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
