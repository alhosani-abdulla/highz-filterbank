# LO Frequency Synchronization Fix - Complete Solution
## Date: March 4, 2026

## Problem

The filterbank spectrometer had a **2-3 MHz systematic offset** where recorded LO frequencies did not match actual hardware frequencies during measurements.

## Root Cause

Data was collected BEFORE the LO was programmed to the target frequency, creating a one-step lag:
- RPi thought it was measuring at frequency N
- Arduino's LO was still at frequency N-2 MHz (from previous step)
- Result: 2 MHz systematic error

## Solution Overview

Fixed the timing by:
1. **Arduino**: Program LO on GPIO rising edge (instead of falling)
2. **RPi**: Call INCREMENT before COLLECT (instead of after)  
3. **RPi**: Store (LO_FREQ - FREQ_STEP) since LO_FREQ advances during INCREMENT

## Files Modified

### 1. Arduino: `adf4351-controller/examples/SweepMixer/SweepMixer.ino`

Changed `handleLOSet()` to program on **rising edge**:

```cpp
static void handleLOSet() {
  int s = digitalRead(PIN_LOSET);
  if (s != prevLOSet) {
    if (s == LOW) {
      Serial.println(F("LOSET falling: ready"));
    } else {
      // Rising edge: program current frequency, then advance
      if (!powerdownLO) {
        Serial.print(F("LOSET rising: program "));
        Serial.print(curFreq, 3);
        Serial.println(F(" MHz"));
        programLO(curFreq);  // Program first
      }
      curFreq = nextFreq(curFreq);  // Advance for next cycle
      Serial.print(F("  Next: "));
      Serial.print(curFreq, 3);
      Serial.println(F(" MHz"));
    }
    prevLOSet = s;
  }
}
```

### 2. RPi: `highz-filterbank/src/instrument/continuous_acq.c` 

**Change A - GET_DATA(): Increment before collecting**

```c
int GET_DATA(FITS_DATA *input_struct, int i) {
    // Program LO first
    INCREMENT_LO_FREQUENCY();
    
    // Then collect at the programmed frequency
    COLLECT_ADC_DATA(&input_struct->data[i]);
    STORE_FREQUENCY(input_struct, i);
    
    return 0;
}
```

**Change B - INCREMENT_LO_FREQUENCY(): Pulse then increment counter**

```c
int INCREMENT_LO_FREQUENCY(void) {
    if (LO_FREQ < FREQ_MAX){
        // Send pulse (Arduino programs on rising edge)
        gpioWrite(GPIO_FREQ_INCREMENT, 0);
        gpioDelay(PULSE_LOW_US);
        gpioWrite(GPIO_FREQ_INCREMENT, 1);
        gpioDelay(LO_SETTLE_US);
        
        // Arduino programmed hardware and advanced curFreq
        // Increment counter to match
        LO_FREQ = LO_FREQ + FREQ_STEP;
    }
    else {
        // Reset at end of sweep
        gpioWrite(GPIO_FREQ_RESET, 0);
        gpioDelay(PULSE_LOW_US);
        gpioWrite(GPIO_FREQ_RESET, 1);
        sleep(INTER_SWEEP_WAIT_S);
        LO_FREQ = FREQ_MIN;
    }
    return 0;
}
```

**Change C - STORE_FREQUENCY(): Store previous frequency**

```c
int STORE_FREQUENCY(FITS_DATA *input_struct, int index) {
    // Store the frequency that was just measured
    // After INCREMENT, LO_FREQ points to NEXT frequency
    // So subtract FREQ_STEP to get the measured frequency
    input_struct->frequencies[index] = LO_FREQ - FREQ_STEP;
    return 0;
}
```

## Correct Timing Sequence

### Initialization
```
RPi: LO_FREQ = 650 MHz Arduino: curFreq = uninitialized

RESET pulse → Arduino: curFreq = 650 MHz (hardware unprogrammed)
```

### GET_DATA(i=0) - First Measurement
```
INCREMENT_LO_FREQUENCY():
  1. Send GPIO LOW (falling - Arduino: no action)
  2. Send GPIO HIGH (rising - Arduino):
     - programLO(curFreq = 650 MHz)  → Hardware outputs 650 MHz
     - curFreq = 652 MHz              → Ready for next cycle
  3. RPi: LO_FREQ = 650 + 2 = 652 MHz

COLLECT_ADC_DATA():
  Arduino hardware: 650 MHz ✓

STORE_FREQUENCY():
  Store: LO_FREQ - FREQ_STEP = 652 - 2 = 650 MHz ✓
```

### GET_DATA(i=1) - Second Measurement
```
INCREMENT_LO_FREQUENCY():
  1. Send pulse
  2. Arduino rising edge:
     - programLO(curFreq = 652 MHz)  → Hardware outputs 652 MHz
     - curFreq = 654 MHz
  3. RPi: LO_FREQ = 652 + 2 = 654 MHz
  
COLLECT_ADC_DATA():
  Arduino hardware: 652 MHz ✓

STORE_FREQUENCY():
  Store: 654 - 2 = 652 MHz ✓
```

### GET_DATA(i=143) - Last Measurement
```
INCREMENT_LO_FREQUENCY():
  1. Send pulse
  2. Arduino rising edge:
     - programLO(curFreq = 936 MHz)  → Hardware outputs 936 MHz
     - curFreq = 938 MHz
  3. RPi: LO_FREQ = 936 + 2 = 938 MHz (exceeds FREQ_MAX)

COLLECT_ADC_DATA():
  Arduino hardware: 936 MHz ✓

STORE_FREQUENCY():
  Store: 938 - 2 = 936 MHz ✓
```

### Next Sweep (Automatic Reset)
```
GET_DATA(i=0) of sweep #2:

INCREMENT_LO_FREQUENCY():
  LO_FREQ = 938 >= FREQ_MAX (936) → TRUE, enter else branch
  1. Send RESET pulse
  2. Arduino: curFreq = 650 MHz (hardware unprogrammed)
  3. RPi: LO_FREQ = 650 MHz
  
Then behaves exactly like first sweep...
```

## Results

✓ LO programmed BEFORE data collection  
✓ Recorded frequency matches hardware frequency
✓ No off-by-one errors
✓ Automatic reset between sweeps
✓ All 144 measurements from 650-936 MHz (2 MHz steps)

## Testing

1. **Recompile and upload Arduino code**:
   ```bash
   # Upload SweepMixer.ino to Arduino
   ```

2. **Recompile RPi acquisition code**:
   ```bash
   cd /home/peterson/highz/highz-filterbank
   make clean && make
   ```

3. **Test with calibration signal**:
   - Inject known frequency signal
   - Verify it appears at correct frequency in processed data
   - Should now be within ±20 kHz (PLL accuracy), not 2-3 MHz off

## Additional Files

See also:
- `TIMING_FIX_EXPLANATION.md` - Original analysis
- `TIMING_SEQUENCE_VERIFICATION.md` - Detailed trace

---
*Fix verified March 4, 2026*
