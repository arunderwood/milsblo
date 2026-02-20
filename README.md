# milsblo

USB-C PD powered ESP32-S3 backpack PCB for controlling two 4-pin PWM PC fans and reading a BME280 temperature/humidity sensor. Designed in Atopile, targeted for PCBWAY fabrication.

**For full project details, architecture decisions, and build instructions, see [CLAUDE.md](CLAUDE.md).**

## Quick overview

- **Power:** USB-C PD (negotiates 12V via CH224K) → AP63205 buck (12V → 5V) → ESP32-S3-DevKitC-1
- **Fan control:** 25kHz PWM on GPIO 4/5, tach feedback on GPIO 6/7
- **Sensor:** BME280 via JST-SH 4-pin (Qwiic/STEMMA QT) on I2C GPIO 8/9
- **Firmware:** ESPHome (`firmware/milsblo.yaml`), integrates with Home Assistant

## Project status

| Phase | Status |
|-------|--------|
| Phase 1: Component definitions | ✅ Complete |
| Phase 2: Atopile schematic | ✅ Complete |
| Phase 3: SPICE simulations | ✅ Complete |
| Phase 4: Firmware + test guide | ✅ Complete |
| Phase 5: PCB layout (KiCad) | 🔲 Not started |
| Phase 6: Manufacturing export | 🔲 Not started |

## Toolchain

```bash
uv pip install "atopile>=0.12,<0.13"
ato build                  # compile to KiCad project in build/
ngspice -b simulation/power_chain.cir
esphome run firmware/milsblo.yaml
```
