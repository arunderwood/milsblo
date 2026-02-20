# milsblo — Phase 4 Breadboard Prototype Test Guide

This document guides you through breadboard validation of the milsblo circuit before PCB fabrication.
Phases 1–3 are complete: Atopile schematic compiles (19/19 parts), SPICE simulations passed.

---

## ⚠️ Safety: Read Before Applying Power

### USB-C PD at 12V is dangerous to prototype circuits

- 12V × 1A = 12W. Reversed or shorted connections can destroy components instantly.
- Always **verify polarity with a multimeter** before connecting load circuits.
- Build and test one stage at a time. Never jump ahead.
- A 65W USB-C PD charger can source 3A+ at 12V. A short circuit will blow your charger's protection, not just the wire.

### Use a CH224K breakout board for prototyping

**Do NOT attempt to breadboard the CH224K IC directly.**
Use a CH224K breakout board (AliExpress, ~$2–3). Breakout boards include onboard VDD regulation,
so the VDD clamping problem (see below) is already solved.

The breakout board tests the PD negotiation itself but NOT your specific CC resistor values or
USB-C connector footprint — those must be verified at PCB stage.

### CH224K VDD clamping issue (PCB design only — irrelevant for breakout)

The final PCB design includes a 5.1V Zener (BZT52C5V1, LCSC C173407) to clamp the CH224K VDD pin.
Without this clamp, at 12V VBUS the VDD pin sees ~12V, exceeding the 5.5V maximum, permanently
destroying the IC. This fix is already implemented in `elec/src/power/usb_pd.ato`.

Math: (12V − 5.1V) / 470Ω = 14.7mA; Zener dissipation = 74.9mW (< 500mW SOD-123 rating) ✓

---

## Shopping List

| Item | Purpose | LCSC/Source | Approx cost |
|------|---------|-------------|-------------|
| CH224K breakout board | PD negotiation test | AliExpress / AnalogLamb | $2–3 |
| ESP32-S3-DevKitC-1 v1.1 | Dev board (exact variant!) | Espressif / AliExpress | $12–18 |
| BME280 breakout (GY-BME280) | Sensor testing | AliExpress / Amazon | $3–5 |
| 4-pin PWM PC fan (120mm or 140mm) | Load testing — **must be 4-pin** | Amazon / PC supply store | $8–15 |
| 12V → 5V buck module (pre-built) | Power for ESP32 during breadboard test | AliExpress | $2–3 |
| 65W+ USB-C PD charger | Power source | Existing or Amazon | $15–25 |
| Resistors: 100Ω (×2), 10kΩ (×2), 4.7kΩ (×2) | PWM series, tach pullups, I2C pullups | Resistor kit | $5 (kit) |
| Capacitors: 100nF (×2), 1µF (×1) | Decoupling | Capacitor kit | $5 (kit) |
| Breadboard + jumper wires | — | — | $5–10 |
| Multimeter | Voltage verification | Existing | — |

**Note on fan header connectors:** The actual PCB uses CJT A2541WR-4P (LCSC C225490, JST-XH compatible).
For breadboard testing, use Dupont jumper wires directly to the fan connector or a fan extension cable.

---

## Prerequisites

1. Install ESPHome: `pip install esphome`
2. Fill in `firmware/secrets.yaml` with your WiFi credentials
3. Generate API/OTA keys: `esphome -q wizard firmware/milsblo.yaml` (copy keys into secrets.yaml)
4. USB cable (USB-A or USB-C to USB data) for initial firmware flash

---

## Test Sequence

Work through these stages in order. Verify each stage passes before proceeding.

---

### Stage 1: PD Power — 12V rail

**Goal:** Confirm 12V PD negotiation works before connecting any other components.

**Setup:**
- Connect CH224K breakout VOUT+ and GND only (no load)
- Plug in 65W+ USB-C PD charger

**Verify:**
- Multimeter on VOUT+ to GND: **11.9–12.1V** ✓
- Breakout board's PG (Power Good) LED lights (if present) ✓

**Expected from SPICE (power_chain.cir, Stage 1):**
- VBUS rises from 5V → 12V as CH224K negotiates (within ~500ms of connection)
- Output voltage settles to 12V ± 100mV

**Fail criteria:** Voltage stays at 5V (PD not negotiating — check charger supports PD 2.0/3.0),
or shows <11V (poor contact), or charger protection trips immediately (short circuit).

**5V-only charger warning:** milsblo will NOT power up with a 5V-only USB-C charger or a
USB-A-to-C cable. CH224K only negotiates 12V; if the charger does not offer PD at 12V, PG
stays low, the AP63205 EN pin is never asserted, the buck never starts, and the ESP32 never
boots. Use a 65W+ USB-C PD charger that explicitly supports 12V (check the charger's PD
voltage list in its specs).

---

### Stage 2: 5V Buck — ESP32 power rail

**Goal:** Verify 5.1V output to feed the ESP32 DevKit.

**Note:** The SPICE simulation of AP63205WU-7 with 750kΩ/100kΩ FB divider predicts **5.075V** output
(not exactly 5.0V). This is correct and expected — the DevKitC-1's AMS1117-3.3 LDO accepts 4.75–12V input.

**Setup:**
- Use a pre-built 12V→5V adjustable buck module for breadboard testing (safer than breadboarding the AP63205)
- Set output to 5.1V before connecting load
- Input: 12V from Stage 1
- Output: no load yet

**Verify:**
- Multimeter on buck output: **5.0–5.2V** ✓

**Then add load (100mA):**
- Connect a 50Ω / 0.5W resistor across the 5V output (100mA load)
- Voltage should hold at **5.0–5.2V** ✓

**Expected from SPICE (power_chain.cir, Stage 3):**
- Vout = 5.075V, ripple < 12.3mV at 500mA load
- Settling time < 200µs on step load

**Fail criteria:** Voltage below 4.75V or above 5.5V, or buck oscillates/gets hot.

---

### Stage 3: ESP32 boot

**Goal:** Confirm ESP32-S3-DevKitC-1 boots on breadboard 5V supply.

**Setup:**
- Connect buck 5V output → DevKit VIN pin
- Connect GND → DevKit GND pin
- Connect USB cable for flashing (laptop USB, not the PD charger)

**Flash firmware (first time):**
```bash
# From the milsblo repo root:
esphome run firmware/milsblo.yaml
```

ESPHome will compile, flash via USB, and begin logging. Expected serial output:
```
[I][app:xxx]: Running on ESP32-S3-DevKitC-1
[I][wifi:xxx]: WiFi connected
[I][api:xxx]: Connected to Home Assistant
```

**Verify:**
- Board boots without reset loop ✓
- WiFi connects (check router DHCP) ✓
- ESPHome dashboard shows "milsblo" online ✓
- Power Good sensor shows "Off" (no 12V PD connected to GPIO 10 yet) ✓

**Fail criteria:** Boot loop (power issue, try USB power only to isolate), WiFi not connecting
(check secrets.yaml SSID/password).

---

### Stage 4: BME280 sensor

**Goal:** Verify I2C temperature/humidity readings.

**Setup (add to existing Stage 3 breadboard):**
- BME280 breakout: VCC → DevKit 3.3V pin, GND → GND
- SDA → GPIO 8, SCL → GPIO 9
- 4.7kΩ pullups: SDA → 3.3V, SCL → 3.3V (may be on breakout already — check)
- 100nF decoupling cap across VCC/GND on the breakout

**Verify:**
- ESPHome logs show: `[I][i2c:xxx]: Found I2C device at address 0x76` ✓
- Temperature sensor shows room temperature (18–30°C typical) ✓
- Humidity sensor shows plausible reading (20–80% typical) ✓
- Pressure sensor shows ~1000–1020 hPa (sea level) ✓
- Readings update every 30 seconds ✓

**Check Home Assistant:**
- Three sensor entities appear in HA: Temperature, Pressure, Humidity ✓

**Fail criteria:** `[E][i2c:xxx]: Component ... I2C Bus Busy`, or no address found at 0x76.
If no I2C device found: check wiring, check pullups, try address 0x77 (some BME280 breakouts use SDO=VCC).
If SDO pin is connected to VCC on the breakout, add `address: 0x77` to milsblo.yaml.

---

### Stage 5: Single fan — PWM control + tach

**Goal:** Verify 25kHz PWM fan speed control and tach RPM reading.

**Setup (add to existing Stage 4 breadboard):**
- Fan pin 1 (GND, black) → breadboard GND
- Fan pin 2 (+12V, yellow) → 12V rail from Stage 1
- Fan pin 3 (Tach, green) → GPIO 6 via 10kΩ pullup to 3.3V
- Fan pin 4 (PWM, blue) → 100Ω resistor → GPIO 4

⚠️ **Fan pin 2 carries 12V. Double-check this connection before applying 12V.**

**Verify fan control:**
- In Home Assistant, open "Fan 1" entity
- Set to 100%: fan spins at full speed ✓
- Set to 50%: fan slows noticeably ✓
- Set to 0% (or off): fan stops or idles at minimum speed ✓

**Expected from SPICE (fan_driver.cir):**
- GPIO HIGH = 3.3V → after 100Ω series R → ~3.29V at fan pin 4 (meets Intel spec ≥2.0V) ✓
- PWM rise time < 5µs (well within 10µs Intel spec) ✓

**Verify tach reading:**
- ESPHome dashboard → "Fan 1 Speed" sensor
- At 100% duty: typical 120mm fan = 1200–2000 RPM; 140mm = 900–1400 RPM
- At 50% duty: roughly half max RPM (fan-dependent)
- Reading updates every 10 seconds ✓

**Fail criteria:**
- Fan doesn't respond to PWM (check 100Ω resistor polarity, check GPIO 4 is outputting PWM with oscilloscope or logic analyzer)
- RPM reads 0 at full speed (check tach wiring, 10kΩ pullup to 3.3V)
- Fan spins at full speed regardless of duty cycle (fan may not accept 3.3V logic — check fan spec)

---

### Stage 6: Full integration + 30-minute soak

**Goal:** Both fans + sensor running simultaneously for 30+ minutes, no thermal issues.

**Setup:**
- Add Fan 2: same wiring as Fan 1 but GPIO 5 (PWM) and GPIO 7 (Tach)

**Worst-case power budget (from CLAUDE.md Phase 3 analysis):**
- Two fans at 0.3A each = 0.6A at 12V = 7.2W
- ESP32 peak = 0.5A at 5V = 2.5W (via buck from 12V: 0.21A at 12V)
- Total 12V draw: ~0.81A = **9.7W** (well within 65W charger capability)

**Run for 30 minutes:**
- Set both fans to 75% in Home Assistant
- Monitor ESPHome logs for errors
- Check temperature readings remain plausible (shouldn't spike due to fan cooling)
- Touch 12V → 5V buck module and CH224K breakout: should be warm but not hot

**Pass criteria:**
- Both fans spin at commanded speed ✓
- Both tach readings stable ✓
- BME280 readings continuous ✓
- No ESPHome errors in logs ✓
- No component feels hot to touch (> ~60°C is concerning) ✓

---

## Known Gotchas from Phases 1–3

1. **Fan header pinout:** Standard 4-pin PC fan = GND / +12V / Tach / PWM (pins 1–4). Some
   fans have different wire colors. Verify with fan manufacturer's datasheet or multimeter.
   **Pin 1 orientation:** The PCB fan headers (CJT A2541WR-4P) have no key tab — the fan
   cable's keyed housing will fit in either orientation. Always connect with the cable notch
   toward the "Pin 1 ▸" silkscreen arrow (to be added in Phase 5 layout). Reversed connection
   puts 12V on the GND pin and GND on the 12V pin — this will damage the fan or the PCB.
   On breadboard: use a multimeter to confirm pin 2 (+12V, yellow wire on most fans) before
   applying 12V power.

2. **3-pin fans will run at full speed.** If you accidentally use a 3-pin fan, PWM pin 4 is
   unconnected — fan runs at 100% always. No damage, but no speed control.

3. **BME280 I2C address:** Default is 0x76 (SDO tied to GND). If breakout has SDO=VCC,
   use 0x77. Update `address:` in milsblo.yaml.

4. **GPIO internal pullups:** milsblo.yaml enables GPIO pullups for tach pins as a backup,
   but the board design includes 10kΩ external pullups. On breadboard you must add the
   external 10kΩ pullups manually — the internal ESP32 pullups are ~45kΩ and may be
   unreliable with long wires.

5. **ESP32 boot strapping pins:** GPIO 0, 3, 45, 46 have boot-time behavior. milsblo uses
   GPIO 4–10, which are free of strapping constraints on the DevKitC-1 v1.1.

6. **ESPHome API key:** The HA API uses encryption. If you lose the key, you must re-flash.
   Keep secrets.yaml backed up securely.

7. **OTA after first flash:** Once WiFi is working, subsequent flashes can be wireless:
   `esphome run firmware/milsblo.yaml --device milsblo.local`

---

## Next Steps After Breadboard Validation

Once all 6 stages pass:

1. Document any discrepancies from expected values (actual RPM range, actual buck output voltage, etc.)
2. Photograph the breadboard setup for reference
3. Proceed to Phase 5: PCB layout in KiCad
   - Open `elec/build/default/milsblo.kicad_pro`
   - Follow layout priorities in CLAUDE.md Phase 5
4. Remaining Phase 5 Atopile tasks (requires interactive TTY):
   - `ato create part` for 2× 1×22 female pin headers (ESP32 mating headers)
   - Wire all 44 ESP32 header pins in milsblo.ato
