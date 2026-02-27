# S21 Measurement Quick Reference

## File Naming
```
filter_01.s2p  → Filter 1 (904.0 MHz)
filter_02.s2p  → Filter 2 (906.6 MHz)
...
filter_21.s2p  → Filter 21 (956.0 MHz)
```

## VNA Measurement Steps

**Equipment Used:** Keysight E5071C ENA Series Network Analyzer

1. **Connect and Calibrate**
   - Port 1 → LO output
   - Port 2 → Filter output (disconnect detector temporarily)
   - Perform full 2-port calibration (SOLT: Short-Open-Load-Through)
   - Use appropriate calibration kit (SMA OSL)
   - Frequency range: 900-960 MHz
   - Number of points: 1601 (for high resolution)
   - IF Bandwidth: 70 kHz (recommended for good SNR)
   - Averaging: 16 (reduces noise)

2. **Configure Measurement**
   - Select S21 parameter
   - Format: Log Magnitude (dB)
   - Smoothing: 1.5% aperture (optional, for cleaner traces)
   - Output power: -20 dBm (avoid detector compression)

3. **Measure Each Filter**
   - Connect to filter path corresponding to filter number
   - Verify passband is visible at expected center frequency
   - Save as Touchstone .s2p file
   - Naming convention: `filter_01.s2p` through `filter_21.s2p`

4. **Quality Check**
   - Passband should show ~13-14 dB loss (in-band)
   - Out-of-band rejection should be visible (>40 dB)
   - Smooth frequency response (no sharp resonances or spikes)
   - Center frequency should match expected value (904.0 to 956.0 MHz)

**Alternative VNA:** For NanoVNA or similar instruments:
   - Use 201+ points minimum
   - Perform SHORT-OPEN-LOAD calibration at both ports
   - Increase averaging if trace is noisy

## RF Signal Chain (LO to Detector)

The S21 measurements capture the complete RF path from LO output to detector input:

```
LO Output
  ↓
1 dB Attenuator (placeholder)
  ↓
2-way Combiner (reverse splitter) .............. -3 to -4 dB
  ↓
Mini-Circuits Amplifier ZX60-P103LN+ ........... +13 to +14 dB
  ↓
Low Pass Filter (<1 GHz) ....................... -1 to -2 dB
  ↓
8-way Splitter QM-PD8-ST ....................... -10 to -14 dB
  ↓
4-way Splitter (6 total) ....................... -7 to -11 dB
  ↓
3 dB Attenuator ................................ -3 dB
  ↓
Cavity Bandpass Filter ......................... -1 dB (in-band)
  ↓
Detector Input (LT5534)
```

**Architecture:** All 21 filters are fed through both the 8-way splitter and then a 4-way splitter. The system uses 6 four-way splitters (connected to outputs of the 8-way splitter) to distribute the signal to all 21 filters. Unused splitter outputs (3 ports from the 4-way splitters, 2 ports from the 8-way) are terminated with 50 Ω loads to maintain proper impedance matching.

**Typical Net Loss (in-band at filter center):**
- Total path loss: ~13-14 dB (amplifier gain compensates for splitter losses)
- Measured S21 values: -13.1 to -14.5 dB across all 21 filters

**Note:** Out-of-band rejection (away from filter center) is much higher (>40 dB) due to filter narrowband response.

## Troubleshooting

- **Very high loss everywhere:** Check connections, recalibrate
- **Asymmetric response:** Possible damaged filter
- **Spiky/noisy:** Increase averaging, check IF bandwidth
- **No passband visible:** Wrong filter, check numbering

## After Measurement

1. Copy all 21 files to: `characterization/s_parameters/`
2. Update `metadata.json` with date and conditions
3. Commit to git: `git add characterization/ && git commit -m "Add S21 measurements"`
4. Restart dashboard - should show "S21 corrections loaded (21/21)"
