# milsblo SPICE Simulations

Simulations of the 5V rail ripple and the fan PWM signal path.

## Prerequisites

Install ngspice (macOS):
```bash
brew install ngspice
```

## Files

| File | What it simulates |
|------|-------------------|
| `power_chain.cir` | AP63205 output ripple with one and two 22µF capacitors |
| `fan_driver.cir` | ESP32 GPIO → 100Ω → fan pin 4 RC signal path at 25kHz |

## Running

```bash
# 5V rail output ripple
ngspice -b simulation/power_chain.cir

# Fan PWM driver simulation
ngspice -b simulation/fan_driver.cir
```

The `-b` flag runs in batch mode (no GUI). Measured results print to stdout.

## Results

### power_chain.cir

The AP63205 has no public SPICE model, so this netlist simulates only what the passives set: ripple current in the output capacitor. Output voltage, loop stability and load-step response are not simulated. Those need the datasheet and a measurement on the board.

| Measurement | Simulated | Target | Pass? |
|-------------|-----------|--------|-------|
| `ripple_1x22uF` (pk-pk, as on the board) | **3.17mV** | < 50mV | ✓ |
| `ripple_2x22uF` (pk-pk, datasheet typical circuit) | **1.58mV** | < 50mV | ✓ |

Both use nominal capacitance. A 22µF ceramic at 5V DC bias has less than its rated value, so measured ripple will be somewhat higher.

### fan_driver.cir

ESP32 GPIO (3.3V, 50Ω source) → 100Ω series → 10nF fan input cap + 100kΩ pullup to 5V.
25kHz, 50% duty. Steady-state after 80µs.

| Measurement | Simulated | Target (Intel fan spec) | Pass? |
|-------------|-----------|-------------------------|-------|
| `Vfan_high` (logic HIGH) | **3.30V** | ≥ 2.0V | ✓ |
| `Vfan_low` (logic LOW) | **7.5mV** | ≤ 0.8V | ✓ |
| `t_rise` (10%→90%) | **3.28µs** | < 5µs (< 12.5% of half-period) | ✓ |
| `t_fall` (90%→10%) | **3.32µs** | < 5µs | ✓ |

## Design notes

### AP63205 output

The AP63205WU-7 is fixed at 5.0V (4.95–5.05V) and switches at 1.1MHz ([DS41326](https://www.diodes.com/assets/Datasheets/AP63200-AP63201-AP63203-AP63205.pdf)). FB connects directly to the output, so the regulator corrects for the drop across the inductor's resistance.

### Ripple calculation (analytical)

```
D       = 5.0 / 12                                       = 0.4167
ΔIL     = (Vin − Vout) × D / (Fsw × L) = 7 × 0.4167 / (1.1MHz × 4.7µH) = 0.564A pk-pk
ΔV_cap  = ΔIL / (8 × Fsw × Cout)       = 0.564 / (8 × 1.1MHz × 22µF)   = 2.91mV
ΔV_esr  = ΔIL × ESR                    = 0.564 × 3mΩ                   = 1.69mV
```

The capacitive and ESR ripple peak at different times, so the simulated 3.17mV is less than their sum.

### Inductor

CENKER CKCS4018-4.7uH/M, LCSC [C354574](https://www.lcsc.com/product-detail/C354574.html): Isat 1.7A, rated 1.2A, DCR 90mΩ.

```
IL_peak = 500mA + 282mA = 782mA at the 500mA ESP32 peak  → below the 1.2A rating
```

The converter stays in continuous conduction above about 282mA of load.

### Fan PWM RC filter

```
τ      = R_PWM × C_fan = 100Ω × 10nF = 1µs
f_3dB  = 1/(2π × 1µs) = 159kHz  >>  25kHz PWM fundamental  ✓
t_rise = 2.2 × τ = 2.2µs  (simulated: 3.3µs — slightly higher due to 50Ω GPIO source impedance)
```
The 3.3µs rise time is well within the 20µs half-period at 25kHz. Full logic swing
is achieved. Fan PWM control is valid.

### Power budget (analytical)

```
Fans:    2 × 0.3A × 12V = 7.2W
Buck:    0.5A × 5.0V / 0.85η ≈ 2.9W  (draws about 245mA from the 12V rail)
Total:   ~10.1W nominal
Margin:  65W USB-C PD charger leaves more than 50W of headroom  ✓
```

## Viewing waveforms (optional)

```bash
ngspice simulation/power_chain.cir
# at the ngspice prompt:
run
plot V(VOUT1) V(VOUT2)
```
