/*
 * High-Precision AD HAT Data Acquisition System
 * 
 * This program implements a multi-threaded data acquisition system for three AD HATs
 * (Analog-to-Digital Hardware Attached on Top) connected to a Raspberry Pi. It performs
 * continuous frequency sweeps while collecting data from multiple ADC channels and saves
 * the results in FITS format (commonly used in astronomy).
 */

/* Standard C Libraries */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <signal.h>
#include <pthread.h>
#include <time.h>
#include <math.h>
#include <unistd.h>
#include <sys/stat.h>
#include <errno.h>

/* Hardware-Specific Libraries */
#include <fitsio.h>
#include <pigpio.h>

/* Custom Hardware Driver */
#include "/home/peterson/highz/High-Precision_AD_HAT/c/lib/Driver/ADS1263.h"

/* Common highz constants and definitions */
#include "highz_common.h"

/* ============= Types and Constants ============= */

#define ChannelNumber ADC_CHANNEL_COUNT

/* GPIO pin definitions from common header */
/* Note: Despite the name "DRYDPIN", these are CS pins used by the Waveshare library */
const int ADHAT1_DRYDPIN = ADHAT1_CS_PIN;
const int ADHAT2_DRYDPIN = ADHAT2_CS_PIN;
const int ADHAT3_DRYDPIN = ADHAT3_CS_PIN;

const int GPIO_FREQ_INCREMENT = ACQ_GPIO_FREQ_INCREMENT;
const int GPIO_FREQ_RESET = ACQ_GPIO_FREQ_RESET;
const int GPIO_LO_POWER = ACQ_GPIO_LO_POWER;

/* Frequency Sweep Parameters from common header */
#define FREQ_MIN ACQ_FREQ_MIN
#define FREQ_MAX ACQ_FREQ_MAX
#define FREQ_STEP ACQ_FREQ_STEP
#define TOTAL_STEPS ACQ_TOTAL_STEPS

/* Debug output flags */
const int ENABLE_TIMING_OUTPUT = 1;
const int ENABLE_VERBOSE_MEASUREMENT = 0;
const int ENABLE_VERBOSE_SWEEP = 1;

/* Timing parameters from common header (can override) */
int LO_SETTLE_US = DEFAULT_LO_SETTLE_US;
int PULSE_LOW_US = DEFAULT_PULSE_LOW_US;
int INTER_SWEEP_WAIT_S = 0.1;  // seconds (different from default)

double LO_FREQ = FREQ_MIN;

// Global timezone offset in seconds (set via command line)
int TIMEZONE_OFFSET_SECONDS = 0;
char TIMEZONE_STRING[16] = "+00:00";

/* Data from all three AD HATs at a single frequency */
typedef struct {
    UDOUBLE ADHAT_1[ChannelNumber];
    UDOUBLE ADHAT_2[ChannelNumber];
    UDOUBLE ADHAT_3[ChannelNumber];
} GetAllValues;

/* Complete frequency sweep data */
typedef struct {
    GetAllValues *data;
    int nrows;
    double sys_voltage;
    char timestamp[32];
    double frequencies[TOTAL_STEPS];
    int spectrum_index;
    char cycle_id[32];
    int state;
    char timezone[16];
} FITS_DATA;

/* ============= Double Buffer System and Thread Synchronization ============= */

/* Double-buffering: allows simultaneous data collection and disk writing */
FITS_DATA *bufferA = NULL;
FITS_DATA *bufferB = NULL;

pthread_mutex_t buffer_mutex = PTHREAD_MUTEX_INITIALIZER;
pthread_cond_t buffer_ready_cond = PTHREAD_COND_INITIALIZER;

int buffer_to_write = 0;  // 0=none, 1=bufferA, 2=bufferB
volatile sig_atomic_t exit_flag = 0;

pthread_t global_writer_thread;

/* Writer thread parameters */
typedef struct {
    const char *filename;
    int nrows;
    int state;
    char cycle_id[32];
} writer_args_t;

/* ============= Forward Declarations ============= */
void FREE_DATA_ARRAY(FITS_DATA **ptr);
int CLOSE_GPIO(void);

/* ============= Helper Functions ============= */

/* Signal handler for clean termination (Ctrl+C) */
void Handler(int signo) {
    const char msg[] = "\n\n*** Interrupt signal received (Ctrl+C) - Shutting down... ***\n\n";
    write(STDERR_FILENO, msg, sizeof(msg) - 1);
    
    exit_flag = 1;
    pthread_cond_signal(&buffer_ready_cond);

    gpioWrite(GPIO_FREQ_INCREMENT, 1);
    gpioWrite(GPIO_FREQ_RESET, 1);
    gpioDelay(LO_SETTLE_US);
    printf("✓ LO control pins returned to idle HIGH\n");

    gpioWrite(GPIO_LO_POWER, 0);
    gpioDelay(LO_SETTLE_US);
    printf("✓ LO board powered down\n");
}

/*
 * Parse timezone string (e.g., "-07:00", "+05:30") into seconds offset
 * Returns offset in seconds, or 0 if parsing fails
 */
int PARSE_TIMEZONE(const char *tz_str) {
    if (!tz_str || strlen(tz_str) < 5) return 0;
    
    int sign = (tz_str[0] == '-') ? -1 : 1;
    int hours = 0, minutes = 0;
    
    if (sscanf(tz_str + 1, "%d:%d", &hours, &minutes) != 2) {
        fprintf(stderr, "Warning: Invalid timezone format '%s', using UTC\n", tz_str);
        return 0;
    }
    
    return sign * (hours * 3600 + minutes * 60);
}

/* Returns timestamp string "MMDDYYYY_HHMMSS" (caller must free) */
char *GET_TIME(void)
{
    char *buf = malloc(64);
    if (!buf) {
        fprintf(stderr, "Error: Failed to allocate memory for timestamp buffer\n");
        perror("GET_TIME malloc failed");
        return NULL;
    }
    
    time_t now = time(NULL);
    now += TIMEZONE_OFFSET_SECONDS;  // Apply timezone offset
    struct tm *t = gmtime(&now);     // Use gmtime since we already adjusted
    if (!t) {
        fprintf(stderr, "Error: Failed to get time\n");
        free(buf);
        return NULL;
    }
    
    if (strftime(buf, 64, "%m%d%Y_%H%M%S", t) == 0) {
        fprintf(stderr, "Error: Failed to format time string\n");
        free(buf);
        return NULL;
    }

    return buf;
}

/* Returns date string "MMDDYYYY" (caller must free) */
char *GET_DATE(void)
{
    char *buf = malloc(16);
    if (!buf) {
        fprintf(stderr, "Error: Failed to allocate memory for date buffer\n");
        perror("GET_DATE malloc failed");
        return NULL;
    }
    
    time_t now = time(NULL);
    now += TIMEZONE_OFFSET_SECONDS;  // Apply timezone offset
    struct tm *t = gmtime(&now);     // Use gmtime since we already adjusted
    if (!t) {
        fprintf(stderr, "Error: Failed to get local time\n");
        free(buf);
        return NULL;
    }
    
    if (strftime(buf, 16, "%m%d%Y", t) == 0) {
        fprintf(stderr, "Error: Failed to format date string\n");
        free(buf);
        return NULL;
    }

    return buf;
}

/* Creates /output_dir/MMDDYYYY/ directory (caller must free returned path) */
char *CREATE_DATE_DIRECTORY(const char *output_dir)
{
    char *date_str = GET_DATE();
    if (!date_str) {
        return NULL;
    }
    
    size_t path_len = strlen(output_dir) + 1 + strlen(date_str) + 1;
    char *full_path = malloc(path_len);
    if (!full_path) {
        fprintf(stderr, "Error: Failed to allocate memory for directory path\n");
        free(date_str);
        return NULL;
    }
    
    snprintf(full_path, path_len, "%s/%s", output_dir, date_str);
    free(date_str);
    
    struct stat st = {0};
    if (stat(full_path, &st) == -1) {
        if (mkdir(full_path, 0755) != 0) {
            fprintf(stderr, "Error: Failed to create directory %s: %s\n", full_path, strerror(errno));
            free(full_path);
            return NULL;
        }
        printf("Created date directory: %s\n", full_path);
    }
    
    return full_path;
}

/* Creates /output_dir/MMDDYYYY/cycle_XXX/ directory (caller must free returned path) */
char *CREATE_CYCLE_DIRECTORY(const char *output_dir, const char *cycle_id)
{
    if (!output_dir || !cycle_id) {
        fprintf(stderr, "Error: Invalid parameters for CREATE_CYCLE_DIRECTORY\n");
        return NULL;
    }
    
    // Parse date from cycle_id format: Cycle_MMDDYYYY_###
    // Expected format: "Cycle_02182026_001"
    if (strlen(cycle_id) < 14 || strncmp(cycle_id, "Cycle_", 6) != 0) {
        fprintf(stderr, "Error: Invalid cycle_id format '%s' (expected Cycle_MMDDYYYY_###)\n", cycle_id);
        return NULL;
    }
    
    // Extract date string (8 chars starting at position 6)
    char date_str[9];
    strncpy(date_str, cycle_id + 6, 8);
    date_str[8] = '\0';
    
    // Validate date string is numeric
    for (int i = 0; i < 8; i++) {
        if (date_str[i] < '0' || date_str[i] > '9') {
            fprintf(stderr, "Error: Invalid date in cycle_id '%s' (expected numeric MMDDYYYY)\n", cycle_id);
            return NULL;
        }
    }
    
    // Build date directory path
    size_t date_dir_len = strlen(output_dir) + 1 + 8 + 1;
    char *date_dir = malloc(date_dir_len);
    if (!date_dir) {
        fprintf(stderr, "Error: Failed to allocate memory for date directory path\n");
        return NULL;
    }
    snprintf(date_dir, date_dir_len, "%s/%s", output_dir, date_str);
    
    // Create date directory if it doesn't exist
    struct stat st = {0};
    if (stat(date_dir, &st) == -1) {
        if (mkdir(date_dir, 0755) != 0) {
            fprintf(stderr, "Error: Failed to create directory %s: %s\n", date_dir, strerror(errno));
            free(date_dir);
            return NULL;
        }
        printf("Created date directory: %s\n", date_dir);
    }
    
    size_t path_len = strlen(date_dir) + 1 + strlen(cycle_id) + 1;
    char *full_path = malloc(path_len);
    if (!full_path) {
        fprintf(stderr, "Error: Failed to allocate memory for cycle directory path\n");
        free(date_dir);
        return NULL;
    }
    
    snprintf(full_path, path_len, "%s/%s", date_dir, cycle_id);
    free(date_dir);
    
    // Reuse st for cycle directory check
    if (stat(full_path, &st) == -1) {
        if (mkdir(full_path, 0755) != 0) {
            fprintf(stderr, "Error: Failed to create cycle directory %s: %s\n", full_path, strerror(errno));
            free(full_path);
            return NULL;
        }
        printf("Created cycle directory: %s\n", full_path);
    }
    
    return full_path;
}

FITS_DATA* MAKE_DATA_ARRAY(int nrows) {
    FITS_DATA *data = malloc(sizeof(FITS_DATA));
    if (!data) {
        printf("Memory allocation for FITS_DATA failed!\n");
        return NULL;
    }
    data->data = malloc(sizeof(GetAllValues) * nrows);
    
    if (!data->data) {
        printf("Memory allocation for data array failed!\n");
        free(data);
        return NULL;
    }
    memset(data->data, 0, sizeof(GetAllValues) * nrows);
    data->nrows = nrows;
    data->sys_voltage = 0.0;
    return data;
}

void FREE_DATA_ARRAY(FITS_DATA **ptr) {
    if (ptr && *ptr) {
        if ((*ptr)->data) free((*ptr)->data);
        free(*ptr);
        *ptr = NULL;
    }
}

int COLLECT_ADC_DATA(GetAllValues *data_row) {
    if (!data_row) return -1;
    
    UBYTE ChannelList[ChannelNumber] = {0,1,2,3,4,5,6};
    
    ADS1263_GetAll(ChannelList, data_row->ADHAT_1, ChannelNumber, ADHAT1_DRYDPIN, get_DRDYPIN(ADHAT1_DRYDPIN));
    ADS1263_GetAll(ChannelList, data_row->ADHAT_2, ChannelNumber, ADHAT2_DRYDPIN, get_DRDYPIN(ADHAT2_DRYDPIN));
    ADS1263_GetAll(ChannelList, data_row->ADHAT_3, ChannelNumber, ADHAT3_DRYDPIN, get_DRDYPIN(ADHAT3_DRYDPIN));
    
    return 0;
}

/* Reads system voltage from ADC channel 7 on HAT 1 (top) */
double READ_SYSTEM_VOLTAGE(void) {
    UDOUBLE vltReading = ADS1263_GetChannalValue(SYS_VOLTAGE_CHANNEL, ADHAT1_DRYDPIN, get_DRDYPIN(ADHAT1_DRYDPIN));
    double adcVoltage;
    
    if ((vltReading >> 31) == 1){
        adcVoltage = ADC_REFERENCE_VOLTAGE * 2 - vltReading/2147483648.0 * ADC_REFERENCE_VOLTAGE;
    }
    else {
        adcVoltage = vltReading/2147483647.8 * ADC_REFERENCE_VOLTAGE;
    }
    
    double sysVoltage = adcVoltage * VOLTAGE_DIVIDER_FACTOR;
    
    if (ENABLE_VERBOSE_SWEEP) {
        printf("Sys Voltage (ADC) = %.6f V, Actual Sys Voltage = %.6f V\n", adcVoltage, sysVoltage);
    }
    return sysVoltage;
}

int STORE_FREQUENCY(FITS_DATA *input_struct, int index) {
    if (!input_struct) return -1;
    if (index < 0 || index >= TOTAL_STEPS) return -1;
    
    // Store the frequency that was just measured
    // After INCREMENT_LO_FREQUENCY, LO_FREQ points to the NEXT frequency,
    // but we just measured at the PREVIOUS frequency
    input_struct->frequencies[index] = LO_FREQ - FREQ_STEP;
    return 0;
}

/* Increments LO frequency via GPIO or resets to FREQ_MIN at end of sweep */
int INCREMENT_LO_FREQUENCY(void) {
    clock_t start_time, end_time;
    double cpu_time_used;
    
    start_time = clock();
    
    if (LO_FREQ < FREQ_MAX){
        // Send pulse to Arduino (programs on rising edge)
        gpioWrite(GPIO_FREQ_INCREMENT, 0);
        gpioDelay(PULSE_LOW_US);
        gpioWrite(GPIO_FREQ_INCREMENT, 1);
        gpioDelay(LO_SETTLE_US);
        
        // Arduino just programmed LO to curFreq and advanced curFreq
        // Now increment RPi counter to match
        LO_FREQ = LO_FREQ + FREQ_STEP;
    }
    else {
        gpioWrite(GPIO_FREQ_RESET, 0);
        gpioDelay(PULSE_LOW_US);
        gpioWrite(GPIO_FREQ_RESET, 1);
        sleep(INTER_SWEEP_WAIT_S);
        LO_FREQ = FREQ_MIN;
    }
    
    end_time = clock();
    cpu_time_used = ((double) (end_time - start_time)) / CLOCKS_PER_SEC;
    
    if (ENABLE_VERBOSE_MEASUREMENT) {
        printf("TIME TAKEN TO SET NEXT LO FREQ: %f\n", cpu_time_used);
    }
    
    return 0;
}

/* Collects ADC data at current LO frequency and increments to next frequency */
int GET_DATA(FITS_DATA *input_struct, int i) {
    if (!input_struct) return -1;
    if (i < 0 || i >= input_struct->nrows) return -1;
    if (!input_struct->data) return -1;
    
    // CRITICAL FIX: Increment LO BEFORE collecting data
    // With the updated Arduino code, the rising edge programs the frequency,
    // so after INCREMENT_LO_FREQUENCY completes, the hardware is at the correct frequency.
    INCREMENT_LO_FREQUENCY();
    
    if (ENABLE_VERBOSE_MEASUREMENT) {
        printf("##########################################\n");
        printf("MEASURING AT LO FREQ: %lf MHz (will store: %lf MHz)\n", 
               LO_FREQ - FREQ_STEP, LO_FREQ - FREQ_STEP);
        printf("##########################################\n");
    }

    if (COLLECT_ADC_DATA(&input_struct->data[i]) != 0) {
        fprintf(stderr, "Error: Failed to collect ADC data\n");
        return -1;
    }
    
    if (STORE_FREQUENCY(input_struct, i) != 0) {
        fprintf(stderr, "Error: Failed to store frequency\n");
        return -1;
    }
    
    return 0;
}

/* Saves sweep to FITS cube file: /Data/MMDDYYYY/Cycle_XXX/state_Y.fits */
int SAVE_OUTPUT(FITS_DATA* input_struct, int state) {
    if (!input_struct) return -1;

    fitsfile *fptr;
    int status = 0;
    const int num_channels = ChannelNumber * 3;
    const int cube_size = TOTAL_STEPS * num_channels;
    
    // Create cycle directory
    char *cycle_dir = CREATE_CYCLE_DIRECTORY(OUTPUT_DIR, input_struct->cycle_id);
    if (!cycle_dir) {
        fprintf(stderr, "Error: Failed to create cycle directory\n");
        return -1;
    }
    
    char filepath[512];
    snprintf(filepath, sizeof(filepath), "%s/state_%d.fits", cycle_dir, input_struct->state);
    
    struct stat st = {0};
    int file_exists = (stat(filepath, &st)== 0);
    
    int n_spectra_current = 0;
    long current_rows = 0;
    
    if (!file_exists) {
        char fits_filename[520];
        snprintf(fits_filename, sizeof(fits_filename), "!%s", filepath);
        
        if (fits_create_file(&fptr, fits_filename, &status)) {
            fprintf(stderr, "Error creating FITS file: %s\n", filepath);
            fits_report_error(stderr, status);
            free(cycle_dir);
            return status;
        }
        
        long naxes = 0;
        if (fits_create_img(fptr, BYTE_IMG, 0, &naxes, &status)) {
            fprintf(stderr, "Error creating primary HDU\n");
            fits_report_error(stderr, status);
            fits_close_file(fptr, &status);
            free(cycle_dir);
            return status;
        }
        
        int n_spectra = 1;
        int n_lo_pts = TOTAL_STEPS;
        char data_fmt[] = "image_cube";
        
        if (fits_update_key(fptr, TSTRING, "CYCLE_ID", input_struct->cycle_id, "Observation cycle identifier", &status) ||
            fits_update_key(fptr, TINT, "STATE", &input_struct->state, "Switch state", &status) ||
            fits_update_key(fptr, TINT, "N_FILTERS", (int*)&num_channels, "Number of filter channels", &status) ||
            fits_update_key(fptr, TINT, "N_LO_PTS", &n_lo_pts, "Number of LO frequency points", &status) ||
            fits_update_key(fptr, TINT, "N_SPECTRA", &n_spectra, "Number of spectra in this file", &status) ||
            fits_update_key(fptr, TSTRING, "DATA_FMT", data_fmt, "Data format type", &status)) {
            fits_report_error(stderr, status);
            fits_close_file(fptr, &status);
            free(cycle_dir);
            return status;
        }
        
        // Write ADC reference voltage and system voltage (separate to avoid const issues)
        double adc_vref = ADC_REFERENCE_VOLTAGE;
        if (fits_update_key(fptr, TDOUBLE, "ADC_VREF", &adc_vref, "ADC reference voltage (V)", &status) ||
            fits_update_key(fptr, TDOUBLE, "SYSVOLT", &input_struct->sys_voltage, "System voltage (V)", &status) ||
            fits_update_key(fptr, TSTRING, "TIMEZONE", input_struct->timezone, "Timezone offset", &status)) {
            fits_report_error(stderr, status);
            fits_close_file(fptr, &status);
            free(cycle_dir);
            return status;
        }
        
        char *ttype[] = {"DATA_CUBE", "SPECTRUM_TIMESTAMP", "SPECTRUM_INDEX", "SYSVOLT", "LO_FREQUENCIES"};
        char *tform[] = {"3024V", "25A", "1J", "1E", "144E"};
        char *tunit[] = {"", "", "", "volts", "MHz"};
        const char *extname = "IMAGE CUBE DATA";
        
        if (fits_create_tbl(fptr, BINARY_TBL, 0, 5, ttype, tform, tunit, extname, &status)) {
            fits_report_error(stderr, status);
            fits_close_file(fptr, &status);
            free(cycle_dir);
            return status;
        }
        
        printf("Created new FITS file: %s\n", filepath);
        current_rows = 0;
        
    } else {
        // File exists - open for appending
        if (fits_open_file(&fptr, filepath, READWRITE, &status)) {
            fprintf(stderr, "Error opening existing FITS file: %s\n", filepath);
            fits_report_error(stderr, status);
            free(cycle_dir);
            return status;
        }
        
        if (fits_read_key(fptr, TINT, "N_SPECTRA", &n_spectra_current, NULL, &status)) {
            fprintf(stderr, "Error reading N_SPECTRA from header\n");
            fits_report_error(stderr, status);
            fits_close_file(fptr, &status);
            free(cycle_dir);
            return status;
        }
        
        if (fits_movnam_hdu(fptr, BINARY_TBL, (char*)"IMAGE CUBE DATA", 0, &status)) {
            fprintf(stderr, "Error moving to binary table HDU\n");
            fits_report_error(stderr, status);
            fits_close_file(fptr, &status);
            free(cycle_dir);
            return status;
        }
        
        if (fits_get_num_rows(fptr, &current_rows, &status)) {
            fprintf(stderr, "Error getting number of rows\n");
            fits_report_error(stderr, status);
            fits_close_file(fptr, &status);
            free(cycle_dir);
            return status;
        }
        
        if (fits_insert_rows(fptr, current_rows, 1, &status)) {
            fprintf(stderr, "Error inserting new row\n");
            fits_report_error(stderr, status);
            fits_close_file(fptr, &status);
            free(cycle_dir);
            return status;
        }
        
        int new_n_spectra = n_spectra_current + 1;
        if (fits_movabs_hdu(fptr, 1, NULL, &status) ||
            fits_update_key(fptr, TINT, "N_SPECTRA", &new_n_spectra, "Number of spectra in this file", &status) ||
            fits_movnam_hdu(fptr, BINARY_TBL, (char*)"IMAGE CUBE DATA", 0, &status)) {
            fprintf(stderr, "Error updating N_SPECTRA header\n");
            fits_report_error(stderr, status);
            fits_close_file(fptr, &status);
            free(cycle_dir);
            return status;
        }
        
        printf("Appending to existing FITS file: %s (sweep #%d)\n", filepath, new_n_spectra);
    }
    
    free(cycle_dir);
    
    UDOUBLE *data_cube = malloc(sizeof(UDOUBLE) * cube_size);
    if (!data_cube) {
        fprintf(stderr, "Memory allocation failed for data cube\n");
        fits_close_file(fptr, &status);
        return -1;
    }
    
    for (int freq_idx = 0; freq_idx < TOTAL_STEPS; freq_idx++) {
        int cube_offset = freq_idx * num_channels;
        for (int ch = 0; ch < ChannelNumber; ch++) {
            data_cube[cube_offset + ch] = input_struct->data[freq_idx].ADHAT_1[ch];
        }
        for (int ch = 0; ch < ChannelNumber; ch++) {
            data_cube[cube_offset + ChannelNumber + ch] = input_struct->data[freq_idx].ADHAT_2[ch];
        }
        for (int ch = 0; ch < ChannelNumber; ch++) {
            data_cube[cube_offset + 2*ChannelNumber + ch] = input_struct->data[freq_idx].ADHAT_3[ch];
        }
    }
    
    float *lo_frequencies = malloc(sizeof(float) * TOTAL_STEPS);
    if (!lo_frequencies) {
        fprintf(stderr, "Memory allocation failed for LO frequencies\n");
        free(data_cube);
        fits_close_file(fptr, &status);
        return -1;
    }
    for (int i = 0; i < TOTAL_STEPS; i++) {
        lo_frequencies[i] = (float)input_struct->frequencies[i];
    }
    
    long row = current_rows + 1;
    int spectrum_index = input_struct->spectrum_index;
    float sysvolt = (float)input_struct->sys_voltage;
    char *timestamp_ptr = input_struct->timestamp;
    
    if (fits_write_col(fptr, TUINT, 1, row, 1, cube_size, data_cube, &status) ||
        fits_write_col(fptr, TSTRING, 2, row, 1, 1, &timestamp_ptr, &status) ||
        fits_write_col(fptr, TINT, 3, row, 1, 1, &spectrum_index, &status) ||
        fits_write_col(fptr, TFLOAT, 4, row, 1, 1, &sysvolt, &status) ||
        fits_write_col(fptr, TFLOAT, 5, row, 1, TOTAL_STEPS, lo_frequencies, &status)) {
        fprintf(stderr, "Error writing data to row %ld\n", row);
        fits_report_error(stderr, status);
        free(data_cube);
        free(lo_frequencies);
        fits_close_file(fptr, &status);
        return status;
    }
    
    free(data_cube);
    free(lo_frequencies);
    
    if (fits_close_file(fptr, &status)) {
        fits_report_error(stderr, status);
        return status;
    }
    
    printf("Sweep data saved successfully.\n");
    return 0;
}

int INITIALIZE_ADS(void)
{
    printf("Initializing High Precision AD HAT...\n");
    SYSFS_GPIO_Init();
    printf("GPIO Initialized.\n");
    printf("Initializing SPI Interface...\n");
    
    DEV_Module_Init(18, ADHAT1_DRYDPIN, get_DRDYPIN(ADHAT1_DRYDPIN));
    DEV_Module_Init(18, ADHAT2_DRYDPIN, get_DRDYPIN(ADHAT2_DRYDPIN));
    DEV_Module_Init(18, ADHAT3_DRYDPIN, get_DRDYPIN(ADHAT3_DRYDPIN));
    ADS1263_reset(18);
    printf("SPI Interface initialized. Initializing AD HATs...\n");
    
    if(ADS1263_init_ADC1(ADS1263_38400SPS, ADHAT1_DRYDPIN) == 1) {
        printf("\r\n END \r\n");
        DEV_Module_Exit(ADHAT1_DRYDPIN, get_DRDYPIN(ADHAT1_DRYDPIN));
        exit(0);
    }
    
    if(ADS1263_init_ADC1(ADS1263_38400SPS, ADHAT2_DRYDPIN) == 1) {
        printf("\r\n END \r\n");
        DEV_Module_Exit(ADHAT2_DRYDPIN, get_DRDYPIN(ADHAT2_DRYDPIN));
        exit(0);
    }
    
    if(ADS1263_init_ADC1(ADS1263_38400SPS, ADHAT3_DRYDPIN) == 1) {
        printf("\r\n END \r\n");
        DEV_Module_Exit(ADHAT3_DRYDPIN, get_DRDYPIN(ADHAT3_DRYDPIN));
        exit(0);
    }
    
    ADS1263_SetMode(0);
    printf("All AD HATS successfully initialized.\n");
    return 0;
}

int CLOSE_GPIO(void)
{
    printf("Shutting down all GPIOs...\n");
    DEV_Module_Exit(18, ADHAT1_DRYDPIN);
    DEV_Module_Exit(18, ADHAT2_DRYDPIN);
    DEV_Module_Exit(18, ADHAT3_DRYDPIN);
    SYSFS_GPIO_Release();
    printf("Shutdown complete.\n");
    return 0;
}

void CLEANUP_AND_SHUTDOWN(void)
{
    printf("\n========================================\n");
    printf("Starting cleanup procedure...\n");
    printf("========================================\n");
    
    gpioWrite(GPIO_FREQ_INCREMENT, 1);
    gpioWrite(GPIO_FREQ_RESET, 1);
    gpioDelay(LO_SETTLE_US);
    printf("✓ LO control pins returned to idle HIGH\n");

    gpioWrite(GPIO_LO_POWER, 0);
    gpioDelay(LO_SETTLE_US);
    printf("✓ LO board powered down\n");
    
    gpioTerminate();
    printf("✓ GPIO hardware released\n");
    
    CLOSE_GPIO();
    printf("✓ AD HAT GPIOs closed\n");
    
    printf("========================================\n");
    printf("Cleanup complete\n");
    printf("========================================\n");
}

void* writer_thread_func(void *arg) {
    writer_args_t *args = (writer_args_t*)arg;
    int state = args->state;

    while (1) {
        if (ENABLE_VERBOSE_SWEEP) {
            printf("NOT SAVING YET...\n");
        }
        pthread_mutex_lock(&buffer_mutex);
        while (buffer_to_write == 0 && !exit_flag) {
            pthread_cond_wait(&buffer_ready_cond, &buffer_mutex);
        }
        
        /* Check if exit requested AND no pending buffer */
        if (exit_flag && buffer_to_write == 0) {
            pthread_mutex_unlock(&buffer_mutex);
            break;
        }

        FITS_DATA *buf = NULL;
        if (buffer_to_write == 1) buf = bufferA;
        else if (buffer_to_write == 2) buf = bufferB;

        buffer_to_write = 0;
        pthread_mutex_unlock(&buffer_mutex);
        
        if (buf) {
            
            if (ENABLE_VERBOSE_SWEEP) {
                printf("ABOUT TO SAVE DATA...\n");
            }
        
            int status = SAVE_OUTPUT(buf, state);

            if (ENABLE_VERBOSE_SWEEP) {
                printf("STATUS: %d\n", status);
            }
            
            if (status != 0) {
                printf("Error saving FITS data: %d\n", status);
            }
        }
        }
    return NULL;
}

int main(int argc, char **argv) {
    if (argc != 5) {
        fprintf(stderr, "Usage: %s <cycle_id> <state> <num_spectra> <timezone>\n", argv[0]);
        fprintf(stderr, "  <cycle_id>    : Cycle identifier (e.g., 'Cycle_02182026_001')\n");
        fprintf(stderr, "                  Format: Cycle_MMDDYYYY_### (date embedded in ID)\n");
        fprintf(stderr, "  <state>       : State value (0-7)\n");
        fprintf(stderr, "                  0=Antenna, 1=Open, 2=Short, 3=Long Cable Open,\n");
        fprintf(stderr, "                  4=Black Body, 5=Ambient, 6=Noise Diode, 7=Long Cable Short\n");
        fprintf(stderr, "  <num_spectra> : Number of sweeps/spectra to collect (positive integer)\n");
        fprintf(stderr, "  <timezone>    : Timezone offset (e.g., -07:00, +00:00)\n");
        return 1;
    }
    
    char cycle_id[32];
    strncpy(cycle_id, argv[1], 31);
    cycle_id[31] = '\0';
    
    char *endptr;
    long state_long = strtol(argv[2], &endptr, 10);
    if (*endptr != '\0' || state_long < 0 || state_long > 7) {
        fprintf(stderr, "Error: Invalid state '%s'. Must be integer 0-7.\n", argv[2]);
        return 1;
    }
    int target_state = (int)state_long;
    
    long num_spectra_long = strtol(argv[3], &endptr, 10);
    if (*endptr != '\0' || num_spectra_long <= 0) {
        fprintf(stderr, "Error: Invalid num_spectra '%s'. Must be positive integer.\n", argv[3]);
        return 1;
    }
    int num_spectra = (int)num_spectra_long;
    
    char *timezone = argv[4];
    
    // Parse and store timezone
    TIMEZONE_OFFSET_SECONDS = PARSE_TIMEZONE(timezone);
    strncpy(TIMEZONE_STRING, timezone, 15);
    TIMEZONE_STRING[15] = '\0';
    
    const char *state_names[] = {
        "Antenna", "Open Circuit", "Short Circuit", "Long Cable Open Circuit",
        "Black Body", "Ambient Temperature Load", "Noise Diode", "Long Cable Short Circuit"
    };
    
    int nrows = TOTAL_STEPS;
    
    printf("========================================\n");
    printf("Data Acquisition Configuration\n");
    printf("========================================\n");
    printf("  Cycle ID: %s\n", cycle_id);
    printf("  State: %d (%s)\n", target_state, state_names[target_state]);
    printf("  Sweeps to collect: %d\n", num_spectra);
    printf("  Measurements per sweep: %d\n", nrows);
    printf("  Frequency range: %.0f-%.0f MHz\n", FREQ_MIN, FREQ_MAX);
    printf("  Frequency step: %.1f MHz\n", FREQ_STEP);
    printf("  Output directory: %s\n", OUTPUT_DIR);
    printf("========================================\n");

    bufferA = MAKE_DATA_ARRAY(nrows);
    bufferB = MAKE_DATA_ARRAY(nrows);

    if (!bufferA || !bufferB) {
        printf("Failed to allocate buffers\n");
        return 1;
    }
    
    strncpy(bufferA->cycle_id, cycle_id, 31);
    bufferA->cycle_id[31] = '\0';
    bufferA->state = target_state;
    strncpy(bufferA->timezone, TIMEZONE_STRING, 15);
    bufferA->timezone[15] = '\0';
    
    strncpy(bufferB->cycle_id, cycle_id, 31);
    bufferB->cycle_id[31] = '\0';
    bufferB->state = target_state;
    strncpy(bufferB->timezone, TIMEZONE_STRING, 15);
    bufferB->timezone[15] = '\0';
    
    INITIALIZE_ADS();
    
    if (gpioInitialise() < 0) {
        fprintf(stderr, "Error: Failed to initialize pigpio for GPIO access.\n");
        fprintf(stderr, "Make sure no other process has locked the GPIO hardware.\n");
        return 1;
    }
    printf("✓ pigpio initialized for GPIO access\n");
    
    signal(SIGINT, Handler);
    signal(SIGTERM, Handler);
    printf("✓ Signal handlers installed for Ctrl+C\n");
    
    gpioSetMode(GPIO_FREQ_INCREMENT, PI_OUTPUT);
    gpioSetMode(GPIO_FREQ_RESET, PI_OUTPUT);
    gpioSetMode(GPIO_LO_POWER, PI_OUTPUT);

    gpioWrite(GPIO_FREQ_INCREMENT, 1);
    gpioWrite(GPIO_FREQ_RESET, 1);
    gpioDelay(LO_SETTLE_US);
    
    gpioWrite(GPIO_LO_POWER, 1);
    gpioDelay(LO_SETTLE_US);
    
    // Reset to FREQ_MIN
    gpioWrite(GPIO_FREQ_RESET, 0);
    gpioDelay(PULSE_LOW_US);
    gpioWrite(GPIO_FREQ_RESET, 1);
    gpioDelay(LO_SETTLE_US);
    // Arduino curFreq is now 650 MHz, but LO hardware not programmed yet
    // First GET_DATA call will program it

    sleep(1);

    printf("Starting main data acquisition loop...\n");

    writer_args_t writer_args = {
        .nrows = nrows,
        .state = target_state
    };
    strncpy(writer_args.cycle_id, cycle_id, 31);
    writer_args.cycle_id[31] = '\0';

    // Create writer thread and store handle globally for signal handler
    pthread_create(&global_writer_thread, NULL, writer_thread_func, &writer_args);

    int current_buffer = 1;
    int row_index = 0;
    int sweeps_completed = 0;
    
    clock_t sweep_start_time, sweep_end_time, program_start_time;
    double sweep_time_used;
    int sweep_count = 0;
    double total_sweep_time = 0.0;
    double min_sweep_time = -1.0;
    double max_sweep_time = 0.0;
    
    program_start_time = clock();
    
    while (!exit_flag && sweeps_completed < num_spectra) {
        clock_t start_time, end_time;
        double cpu_time_used;
        
        start_time = clock();
        FITS_DATA *active_buffer = (current_buffer == 1) ? bufferA : bufferB;
        
        if (row_index == 0) {
            active_buffer->sys_voltage = READ_SYSTEM_VOLTAGE();
            
            char *sweep_time = GET_TIME();
            if (!sweep_time) {
                fprintf(stderr, "Error: Failed to generate sweep timestamp\n");
                break;
            }
            snprintf(active_buffer->timestamp, sizeof(active_buffer->timestamp), "%s.fits", sweep_time);
            free(sweep_time);
            
            active_buffer->spectrum_index = sweeps_completed;
            
            if (ENABLE_TIMING_OUTPUT || ENABLE_VERBOSE_SWEEP) {
                sweep_start_time = clock();
            }
            
            if (ENABLE_VERBOSE_SWEEP) {
                printf("\n========================================\n");
                printf("Starting sweep #%d/%d (State: %d, LO freq: %.1f MHz)\n", 
                       sweeps_completed + 1, num_spectra, target_state, LO_FREQ);
                printf("========================================\n");
            }
        }
        
        int result = GET_DATA(active_buffer, row_index);
        
        if (exit_flag) {
            printf("\nExit signal detected. Breaking out of main loop...\n");
            break;
        }
        
        if (result != 0) {
            printf("Error occurred in GET_DATA. Exiting main loop...\n");
            break;
        }
        
        row_index++;

        if (row_index >= nrows) {
            sweep_end_time = clock();
            sweep_time_used = ((double) (sweep_end_time - sweep_start_time)) / CLOCKS_PER_SEC;
            sweep_count++;
            
            total_sweep_time += sweep_time_used;
            if (min_sweep_time < 0 || sweep_time_used < min_sweep_time) {
                min_sweep_time = sweep_time_used;
            }
            if (sweep_time_used > max_sweep_time) {
                max_sweep_time = sweep_time_used;
            }
            
            if (ENABLE_TIMING_OUTPUT) {
                printf("\n========================================\n");
                printf("Sweep #%d/%d COMPLETED (State %d)\n", sweep_count, num_spectra, target_state);
                printf("  Total measurements: %d\n", nrows);
                printf("  Frequency range: %.1f - %.1f MHz\n", FREQ_MIN, FREQ_MAX);
                printf("  Sweep duration: %.3f seconds\n", sweep_time_used);
                printf("  Average time per measurement: %.4f seconds\n", sweep_time_used / nrows);
                printf("========================================\n");
            }
            
            pthread_mutex_lock(&buffer_mutex);
            buffer_to_write = current_buffer;
            pthread_cond_signal(&buffer_ready_cond);
            pthread_mutex_unlock(&buffer_mutex);
            
            sweeps_completed++;
            
            if (sweeps_completed >= num_spectra) {
                printf("\n========================================\n");
                printf("Target reached: Collected %d sweeps for State %d\n", sweeps_completed, target_state);
                printf("Exiting data acquisition...\n");
                printf("========================================\n");
                exit_flag = 1;
                break;
            }

            current_buffer = (current_buffer == 1) ? 2 : 1;
            row_index = 0;
        }
        end_time = clock();
        
        cpu_time_used = ((double) (end_time-start_time)) / CLOCKS_PER_SEC;
        if (ENABLE_VERBOSE_MEASUREMENT) {
            printf("LOOP EXECUTION TIME: %f seconds\n", cpu_time_used);
        }
    }

    printf("\n========================================\n");
    printf("Beginning clean shutdown sequence...\n");
    printf("========================================\n");
    
    printf("Step 1/4: Signaling writer thread to stop...\n");
    pthread_mutex_lock(&buffer_mutex);
    exit_flag = 1;
    pthread_cond_signal(&buffer_ready_cond);
    pthread_mutex_unlock(&buffer_mutex);

    printf("Waiting for writer thread to complete...\n");
    pthread_join(global_writer_thread, NULL);
    printf("✓ Writer thread completed\n");

    printf("\nStep 2/4: Freeing data buffers...\n");
    FREE_DATA_ARRAY(&bufferA);
    FREE_DATA_ARRAY(&bufferB);
    printf("✓ Buffers freed\n");
    
    printf("\nStep 3/4: Shutting down hardware...\n");
    CLEANUP_AND_SHUTDOWN();
    
    clock_t program_end_time = clock();
    double total_program_time = ((double) (program_end_time - program_start_time)) / CLOCKS_PER_SEC;
    
    printf("\n========================================\n");
    printf("Step 4/4: Final Statistics Summary\n");
    printf("========================================\n");
    printf("Data Collection:\n");
    printf("  State: %d (%s)\n", target_state, state_names[target_state]);
    printf("  Target sweeps: %d\n", num_spectra);
    printf("  Sweeps completed: %d\n", sweep_count);
    printf("  Measurements per sweep: %d\n", nrows);
    printf("  Total measurements: %d\n", sweep_count * nrows);
    printf("\n");
    printf("Timing Statistics:\n");
    printf("  Total program runtime: %.2f seconds (%.2f minutes)\n", 
           total_program_time, total_program_time / 60.0);
    
    if (sweep_count > 0) {
        printf("  Total sweep time: %.2f seconds\n", total_sweep_time);
        printf("  Average sweep duration: %.3f seconds\n", total_sweep_time / sweep_count);
        printf("  Minimum sweep duration: %.3f seconds\n", min_sweep_time);
        printf("  Maximum sweep duration: %.3f seconds\n", max_sweep_time);
        printf("  Average time per measurement: %.4f seconds\n", 
               total_sweep_time / (sweep_count * nrows));
    }
    
    printf("\n");
    printf("Program terminated successfully\n");
    printf("========================================\n");

    printf("\n========================================\n");
    printf("Program ended cleanly.\n");
    printf("========================================\n");

    return 0;
}