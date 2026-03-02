# Hardware Configuration

Documentation for the High-Z Filterbank hardware setup, including ADC HAT wiring and GPIO pin assignments.

## ADC HAT Stack Configuration

The system uses three **Waveshare High-Precision AD HAT** boards stacked on a Raspberry Pi. Each HAT contains an **ADS1263** 32-bit ADC with 10 differential input channels.

### Physical Stack Layout

```
┌─────────────────────────┐
│   TOP HAT (ADC #1)      │  CS Pin: 12, DRDY Pin: 16
│   Hardware Mods: YES    │  Filters: 1-7 (Channels 0-6)
├─────────────────────────┤
│   MIDDLE HAT (ADC #2)   │  CS Pin: 22, DRDY Pin: 17
│   Hardware Mods: NO     │  Filters: 8-14 (Channels 0-6)
├─────────────────────────┤
│   BOTTOM HAT (ADC #3)   │  CS Pin: 23, DRDY Pin: 25
│   Hardware Mods: YES    │  Filters: 15-21 (Channels 0-6)
├─────────────────────────┤
│   Raspberry Pi 4        │
└─────────────────────────┘
```

### Pin Mapping

| ADC Position | CS Pin (BCM) | DRDY Pin (BCM) | Hardware Modifications | Filter Range |
|--------------|--------------|----------------|------------------------|--------------|
| **Top**      | 12           | 16             | GPIO 12 & 16 hardwired | Filters 1-7  |
| **Middle**   | 22           | 17             | None (default config)  | Filters 8-14 |
| **Bottom**   | 23           | 25             | GPIO 23 & 25 hardwired | Filters 15-21|

**Notes:**
- CS (Chip Select) pin is what you specify in software
- DRDY (Data Ready) pin is automatically mapped by `get_DRDYPIN()` function
- All three ADCs share the SPI bus (MOSI/MISO/SCK)

### Hardware Modifications

**Top and Bottom HATs** have custom wiring on the underside:
- Wire from GPIO CS pin to board components (enables unique chip select)
- Wire from GPIO DRDY pin to board components (enables unique data ready signal)

**Middle HAT** uses the default Waveshare configuration without modifications.

This custom wiring allows three identical HAT boards to operate independently on the same Raspberry Pi.

## GPIO Pin Assignments

### ADC Control (BCM Numbering)

```
Pin 12  → Top HAT Chip Select (CS)
Pin 16  → Top HAT Data Ready (DRDY)

Pin 22  → Middle HAT Chip Select (CS) - Default
Pin 17  → Middle HAT Data Ready (DRDY) - Default

Pin 23  → Bottom HAT Chip Select (CS)
Pin 25  → Bottom HAT Data Ready (DRDY)

Pin 18  → Reset (RST) - Shared by all ADCs
```

### Filterbank Control

```
Pin 4   → LO Frequency Increment (triggers +2 MHz step)
Pin 5   → LO Frequency Reset (returns to 650 MHz)
Pin 6   → LO Power Enable/Disable

Pin 20  → State Control Bit 0  (LSB)
Pin 24  → State Control Bit 1
Pin 27  → State Control Bit 2  (MSB)
```

State pins form a 3-bit code (0-7) to select calibration states:
- 000 (0) = Antenna/sky measurement
- 001 (1) = Ambient load
- 010 (2) = Filter calibration sweep
- 011-111 (3-7) = Other calibration loads

## ADC Configuration

### Reference Voltage

**Current Configuration (as of code inspection):**
```c
ADC_REFERENCE_VOLTAGE = 2.5V  // Internal reference
REFMUX = 0x00                 // Internal ±2.5V reference selected
```

**Alternative Configuration:**
```c
ADC_REFERENCE_VOLTAGE = 5.08V // External AVDD/AVSS
REFMUX = 0x24                 // External reference selected
```

⚠️ **Important:** The reference voltage setting in `ADS1263.c` must match the `ADC_REFERENCE_VOLTAGE` constant in `continuous_acq.c` for accurate voltage readings.

### ADC Specifications

- **Model:** Texas Instruments ADS1263
- **Resolution:** 32-bit (signed integer)
- **Sample Rate:** 38400 SPS (configured)
- **Input Channels:** 10 differential pairs per ADC (using channels 0-6)
- **Input Mode:** Single-ended
- **Digital Filter:** Sinc1 (fastest response)
- **Settling Time:** 35 µs
- **CRC Check:** Enabled for data integrity

### Channel Configuration

Each ADC reads **7 channels** (0-6) per frequency step:
- Channel 0-6: Filter detector outputs
- Channels 7-9: Available but unused in current configuration

## Filter Connection Mapping

### Signal Routing

**Top HAT (Pin 12):**
- AIN0 → Filter 1 detector output
- AIN1 → Filter 2 detector output
- AIN2 → Filter 3 detector output
- AIN3 → Filter 4 detector output
- AIN4 → Filter 5 detector output
- AIN5 → Filter 6 detector output
- AIN6 → Filter 7 detector output

**Middle HAT (Pin 22):**
- AIN0 → Filter 8 detector output
- AIN1 → Filter 9 detector output
- AIN2 → Filter 10 detector output
- AIN3 → Filter 11 detector output
- AIN4 → Filter 12 detector output
- AIN5 → Filter 13 detector output
- AIN6 → Filter 14 detector output

**Bottom HAT (Pin 23):**
- AIN0 → Filter 15 detector output
- AIN1 → Filter 16 detector output
- AIN2 → Filter 17 detector output
- AIN3 → Filter 18 detector output
- AIN4 → Filter 19 detector output
- AIN5 → Filter 20 detector output
- AIN6 → Filter 21 detector output

### Data Storage Order

In FITS files, data is stored as a `DATA_CUBE` with dimensions [144 frequencies × 21 channels]:
```
Channels 0-6:   Top HAT    (Filters 1-7)
Channels 7-13:  Middle HAT (Filters 8-14)
Channels 14-20: Bottom HAT (Filters 15-21)
```

## Testing and Verification

### Voltage Monitor Tool

A standalone voltage monitoring program is available for testing individual ADC channels:

```bash
# Compile
cd /home/peterson/highz/High-Precision_AD_HAT/c
make voltage_monitor

# Usage
sudo ./bin/voltage_monitor [channel] [cs_pin]

# Examples
sudo ./bin/voltage_monitor 0 12   # Read channel 0 from top HAT
sudo ./bin/voltage_monitor 3 22   # Read channel 3 from middle HAT
sudo ./bin/voltage_monitor 6 23   # Read channel 6 from bottom HAT
```

**Test Procedure:**
1. Connect a known voltage source (0-2.5V with current settings)
2. Connect GND to ADC GND
3. Connect +V to desired channel input
4. Run voltage_monitor and verify reading matches input voltage

### Identifying ADC Positions

If you need to determine which physical HAT corresponds to which pin:

1. **Visual inspection:** Look for hardwired GPIO modifications on underside
   - Top: Has wires on GPIO 12 & 16
   - Middle: No modifications
   - Bottom: Has wires on GPIO 23 & 25

2. **Signal injection:** Apply a test voltage to a channel and read with voltage_monitor using different pins (12, 22, 23) to identify which responds

3. **Filter testing:** Apply RF signal to a known filter and measure which ADC channel shows response

## Troubleshooting

### CRC Errors

If you see repeated CRC errors during ADC reads:
```
⚠️  CRC error on ADC read. Retrying...
```

**Causes:**
- Only one or two ADCs initialized (need all three for shared SPI bus)
- Incorrect pin assignments
- Hardware failure

**Solution:**
- Ensure all three ADCs are initialized before reading any data
- Verify GPIO connections and hardware modifications
- Check for loose connections or damaged HAT boards

### "Pin not initialized" Errors

```
Pin 12 not initialized
Pin 16 not initialized
```

**Cause:** GPIO system not initialized before ADC operations

**Solution:**
- Call `SYSFS_GPIO_Init()` before any `DEV_Module_Init()` calls
- See voltage_monitor.c for proper initialization sequence

### Reference Voltage Mismatch

If voltage readings seem incorrect by a factor of ~2:

**Check that:**
1. `REFMUX` register in `ADS1263.c` matches your hardware setup
   - `0x00` for internal 2.5V reference
   - `0x24` for external 5.08V reference
2. `ADC_REFERENCE_VOLTAGE` in `continuous_acq.c` matches actual reference
3. Recompile both voltage_monitor and acquisition programs after changes

## Maintenance Notes

### Changing Reference Voltage

To switch from internal 2.5V to external 5.08V reference:

1. **Edit ADS1263.c** (line ~393):
```c
UBYTE REFMUX = 0x24;   // 0x00=Internal ±2.5V, 0x24=VDD/VSS
```

2. **Edit continuous_acq.c** (line ~60):
```c
const double ADC_REFERENCE_VOLTAGE = 5.08;  // Volts
```

3. **Edit voltage_monitor.c** (line ~24):
```c
#define REF  5.08  // Reference voltage in volts
```

4. **Recompile everything:**
```bash
cd /home/peterson/highz/highz-filterbank
make clean && make

cd /home/peterson/highz/High-Precision_AD_HAT/c
make voltage_monitor
```

### Physical Stack Order

The physical stacking order (top/middle/bottom) does NOT affect functionality as long as the GPIO wiring matches the documentation above. The pin assignments (12, 22, 23) are determined by electrical connections, not physical position.

However, for clarity and maintenance, it's recommended to maintain the documented order.

## References

- **ADS1263 Datasheet:** Texas Instruments SBAS932
- **Waveshare HAT:** [High-Precision AD HAT](https://www.waveshare.com/high-precision-ad-hat.htm)
- **Source Code:** `/home/peterson/highz/High-Precision_AD_HAT/c/lib/Driver/ADS1263.c`
- **Pin Mapping Function:** `get_DRDYPIN()` in ADS1263.c (line ~58)

---

*Last Updated: February 26, 2026*
