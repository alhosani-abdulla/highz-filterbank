/*==============================================================================
 * HIGHZ COMMON HEADER
 * 
 * Shared constants, types, and function declarations used across multiple
 * programs in the highz-filterbank data acquisition system.
 * 
 * Last updated: 2026-02-27
 *=============================================================================*/

#ifndef HIGHZ_COMMON_H
#define HIGHZ_COMMON_H

/*==============================================================================
 * ADC HARDWARE CONFIGURATION
 *=============================================================================*/

/* AD HAT GPIO Pin Definitions (BCM numbering) */
#define ADHAT1_CS_PIN       12  /* Top ADC HAT - Chip Select */
#define ADHAT1_DRDY_PIN     16  /* Top ADC HAT - Data Ready */

#define ADHAT2_CS_PIN       22  /* Middle ADC HAT - Chip Select */
#define ADHAT2_DRDY_PIN     17  /* Middle ADC HAT - Data Ready */

#define ADHAT3_CS_PIN       23  /* Bottom ADC HAT - Chip Select */
#define ADHAT3_DRDY_PIN     25  /* Bottom ADC HAT - Data Ready */

#define ADC_RST_PIN         18  /* Common reset pin for all ADCs */

/* ADC Reference Voltage Configuration */
#define ADC_REFERENCE_VOLTAGE   2.5  /* Volts - Internal 2.5V reference */
                                      /* NOTE: Set to 5.08 for external AVDD/AVSS reference */
                                      /* Also change REFMUX in ADS1263.c line ~393 to 0x24 for external */

/* ADC Sampling Configuration */
#define ADC_SAMPLE_RATE     38400  /* Samples per second */
#define ADC_CHANNEL_COUNT   7      /* Number of channels per ADC (0-6) */

/*==============================================================================
 * LOG DETECTOR CONFIGURATION
 *=============================================================================*/

/* Log detector used to measure local oscillator power during calibration */
#define LOG_DETECTOR_CHANNEL    7      /* ADC channel (AIN7) */
#define LOG_DETECTOR_CS_PIN     22     /* Middle ADC HAT (ADHAT2) */
#define LOG_DETECTOR_DRDY_PIN   17     /* Middle ADC HAT data ready */

/*==============================================================================
 * SYSTEM VOLTAGE MONITORING
 *=============================================================================*/

/* System voltage divider configuration */
#define VOLTAGE_DIVIDER_FACTOR  11.0   /* Divider ratio for system voltage measurement */
#define SYS_VOLTAGE_CHANNEL     7      /* Channel 7 on ADHAT1 (top ADC) */
#define SYS_VOLTAGE_CS_PIN      12     /* Top ADC HAT */
#define SYS_VOLTAGE_DRDY_PIN    16     /* Top ADC HAT data ready */

/*==============================================================================
 * ARDUINO CONTROL GPIO PINS
 *=============================================================================*/

/* These pins control the Arduino LO sweep controller */
/* NOTE: Pins differ between calibration (calib) and data acquisition (acq) programs */

/* Calibration sweep pins (filterSweep.c / calib program) */
#define CALIB_GPIO_FREQ_INCREMENT   13  /* Increment frequency (falling edge) */
#define CALIB_GPIO_FREQ_RESET       19  /* Reset frequency sweep (falling edge) */
#define CALIB_GPIO_LO_POWER         26  /* LO board power (HIGH=ON, LOW=OFF) */

/* Data acquisition pins (continuous_acq.c / acq program) */
#define ACQ_GPIO_FREQ_INCREMENT     4   /* Increment frequency (falling edge) */
#define ACQ_GPIO_FREQ_RESET         5   /* Reset frequency sweep (falling edge) */
#define ACQ_GPIO_LO_POWER           6   /* LO board power (HIGH=ON, LOW=OFF) */

/*==============================================================================
 * FREQUENCY SWEEP PARAMETERS
 *=============================================================================*/

/* Calibration sweep: Band B (filterSweep.c / calib program) */
#define CALIB_FREQ_MIN      900.0   /* MHz */
#define CALIB_FREQ_MAX      960.0   /* MHz */
#define CALIB_FREQ_STEP     0.2     /* MHz */
#define CALIB_TOTAL_STEPS   301     /* (960-900)/0.2 + 1 */

/* Data acquisition sweep: Full band (continuous_acq.c / acq program) */
#define ACQ_FREQ_MIN        650.0   /* MHz */
#define ACQ_FREQ_MAX        936.0   /* MHz */
#define ACQ_FREQ_STEP       2.0     /* MHz */
#define ACQ_TOTAL_STEPS     144     /* (936-650)/2 + 1 */

/*==============================================================================
 * TIMING PARAMETERS
 *=============================================================================*/

/* Default timing values (can be overridden in individual programs) */
#define DEFAULT_LO_SETTLE_US        50      /* Microseconds - LO settling time after freq change */
#define DEFAULT_PULSE_LOW_US        50      /* Microseconds - GPIO pulse width */
#define DEFAULT_INTER_SWEEP_WAIT_S  1       /* Seconds - wait between sweeps for LO stabilization */

/*==============================================================================
 * DATA OUTPUT CONFIGURATION
 *=============================================================================*/

#define OUTPUT_DIR  "/media/peterson/INDURANCE/Data"  /* Base directory for all data */

/*==============================================================================
 * UTILITY MACROS
 *=============================================================================*/

/* Convert ADC counts to voltage (32-bit signed ADC) */
#define ADC_COUNTS_TO_VOLTAGE(counts, ref_voltage) \
    (((counts) >> 31) == 1 ? \
        ((ref_voltage) * 2.0 - (counts) / 2147483648.0 * (ref_voltage)) : \
        ((counts) / 2147483647.8 * (ref_voltage)))

/* System voltage from ADC voltage through divider */
#define SYSTEM_VOLTAGE(adc_voltage) ((adc_voltage) * VOLTAGE_DIVIDER_FACTOR)

/*==============================================================================
 * TYPE DEFINITIONS
 *=============================================================================*/

/* Ensure these types are defined (they may also be in ADS1263.h) */
#ifndef UDOUBLE
typedef unsigned int UDOUBLE;  /* 32-bit unsigned */
#endif

#ifndef UBYTE
typedef unsigned char UBYTE;   /* 8-bit unsigned */
#endif

#ifndef UWORD
typedef unsigned short UWORD;  /* 16-bit unsigned */
#endif

#endif /* HIGHZ_COMMON_H */
