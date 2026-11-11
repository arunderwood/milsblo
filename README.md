# milsblo

**milsblo** is a portmanteau of **[MILSBO](https://www.ikea.com/us/en/p/milsbo-glass-door-cabinet-anthracite-30396448/)** — IKEA's popular glass-door cabinet — and ***blow***, for the fan-control feature at the heart of the board.

> An experiment in vibe-coded circuit design by someone without much electronics experience.

## Background

Hobbyists convert MILSBO cabinets into [miniature indoor greenhouses](https://daught.me/blog/2024/ikea-milsbo-greenhouse/) using grow lights, humidifiers, and fans. Circulation fans are critical: airflow strengthens stems and prevents the mold that thrives in warm, stagnant, humid air.

**milsblo** is the electronics backbone for that setup.

## What it does

A single USB-C cable delivers [12V via USB Power Delivery](https://learn.adafruit.com/understanding-usb-type-c-cable-types-pitfalls-and-more/usb-power-delivery-usb-pd) — one cord powers both fans and the microcontroller. The board backpacks onto an ESP32-S3-DevKitC-1 via female pin headers.

```
USB-C PD charger (65W+)
    │
    ▼
CH224A (PD sink) → 12V rail ──→ Fan headers × 2 (always-on 12V)
                           └──→ AP63205 buck → 5V → ESP32-S3-DevKitC-1
                                                         │
                                                         ├── 25kHz PWM → Fan 1 & 2 speed control
                                                         ├── Tach input ← Fan RPM feedback
                                                         └── I2C → BME280 temp/humidity sensor
```

- **Power:** USB-C PD negotiates 12V via CH224A; stepped to 5V by AP63205 buck converter
- **Fan control:** 25kHz PWM on GPIO 4/5 (silent, full-range speed), tach feedback on GPIO 6/7
- **Sensor:** BME280 via JST-SH 4-pin (Qwiic/STEMMA QT compatible) on I2C GPIO 8/9
- **Firmware:** ESPHome (`firmware/milsblo.yaml`) — integrates with Home Assistant

## Project status

| Phase | Status |
|-------|--------|
| Phase 1: Component definitions | ✅ Complete |
| Phase 2: KiCad schematic | ✅ Complete |
| Phase 3: SPICE simulations | ✅ Complete |
| Phase 4: Firmware + test guide | ✅ Complete |
| Phase 5: PCB layout (KiCad) | ✅ Complete |
| Phase 6: Manufacturing export | ✅ Complete (`tools/export_fab.sh`) |

## Design

Designed in [KiCad](https://www.kicad.org/). The project lives in `elec/kicad/`, and `tools/check_design.py` checks it against the part datasheets.

**For full architecture decisions and build instructions, see [CLAUDE.md](CLAUDE.md).**

## Toolchain

```bash
python3 tools/check_design.py       # ERC, DRC, parity, connectivity, datasheet and layout rules
tools/export_fab.sh                 # Gerber zip, BOM and pick-and-place in elec/build/fab
ngspice -b simulation/power_chain.cir
esphome run firmware/milsblo.yaml
```
