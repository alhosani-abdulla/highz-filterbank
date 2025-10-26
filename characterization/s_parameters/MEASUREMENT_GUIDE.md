# S21 Measurement Quick Reference

## File Naming
```
filter_00.s2p  → Filter 0 (904.0 MHz)
filter_01.s2p  → Filter 1 (906.6 MHz)
...
filter_20.s2p  → Filter 20 (956.0 MHz)
```

## NanoVNA Measurement Steps

1. **Connect and Calibrate**
   - Port 1 → LO output
   - Port 2 → Filter output (disconnect detector temporarily)
   - Calibrate: SHORT-OPEN-LOAD at both ports
   - Range: 900-960 MHz, 201 points

2. **Measure Each Filter**
   - Navigate to S21 display
   - Format: Log Magnitude (dB)
   - Save as Touchstone .s2p file
   - Label: `filter_XX.s2p`

3. **Verify**
   - Check passband visible (~2-3 dB loss)
   - Out-of-band rejection visible
   - No cable/connection issues (smooth curve)

## Expected S21 Values

| Component              | Loss (dB) |
|------------------------|-----------|
| Cables (total)         | 2-4       |
| 8-way splitter         | ~9        |
| 4-way splitter         | ~6        |
| Filter insertion loss  | 2-3       |
| Connectors/mismatch    | 1-2       |
| **Total (typical)**    | **~15-25**|

In-band (at filter center): Lower loss (~15-20 dB)
Out-of-band: Much higher loss (>40 dB)

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
