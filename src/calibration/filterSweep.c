#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <signal.h>
#include <unistd.h>
#include <fitsio.h>
#include <time.h>
#include <pigpio.h>
#include <sys/stat.h>
#include <errno.h>

// AD HAT driver (now in organized highz directory structure)
#include "/home/peterson/highz/High-Precision_AD_HAT/c/lib/Driver/ADS1263.h"

// Types and constants
#define ChannelNumber 7

// GPIO pin definitions (BCM numbering)
const int ADHAT1_DRYDPIN = 12;
const int ADHAT2_DRYDPIN = 22;
const int ADHAT3_DRYDPIN = 23;

const int GPIO_FREQ_INCREMENT = 13;  // Increment frequency (falling edge trigger)
const int GPIO_FREQ_RESET = 19;      // Reset frequency sweep (falling edge trigger)
const int GPIO_LO_POWER = 26;        // LO board power control (HIGH=ON, LOW=OFF)

// Filter sweep Band B: 900-960 MHz, 0.2 MHz step (matches SweepFilter.ino)
const double FREQ_MIN = 900.0;
const double FREQ_MAX = 960.0;
const double FREQ_STEP = 0.2;
#define TOTAL_STEPS 301  // (FREQ_MAX - FREQ_MIN) / FREQ_STEP + 1 = (960-900)/0.2 + 1
double LO_FREQ = FREQ_MIN;          // Start frequency initialized to FREQ_MIN

const char *OUTPUT_DIR = "/media/peterson/INDURANCE/Data";

// Configurable timing parameters
// All times are in milliseconds unless noted otherwise.
int LO_SETTLE_US = 50;        // usleep in GET_DATA (50 microseconds)
int PULSE_LOW_US = 50;      // gpioDelay for low pulse when incrementing (microseconds)
int INTER_SWEEP_WAIT_S = 1;   // seconds between sweeps for LO stabilization

const double VOLTAGE_DIVIDER_FACTOR = 11.0;

// Global timezone offset in seconds (set via command line)
int TIMEZONE_OFFSET_SECONDS = 0;
char TIMEZONE_STRING[16] = "+00:00";

/* Data from all three AD HATs at a single frequency */
typedef struct {
    UDOUBLE ADHAT_1[ChannelNumber];
    UDOUBLE ADHAT_2[ChannelNumber];
    UDOUBLE ADHAT_3[ChannelNumber];
} GetAllValues;

/* Complete frequency sweep data with metadata at sweep level */
typedef struct {
    GetAllValues *data;               // Array of 301 measurements (one per frequency)
    int nrows;                        // Number of measurements (301)
    double sys_voltage;               // System voltage (read once per sweep)
    char timestamp[32];               // Timestamp for this sweep
    double frequencies[TOTAL_STEPS];  // Array of 301 LO frequencies
    int spectrum_index;               // Index of this spectrum (0 for single sweep)
    char cycle_id[32];                // Cycle identifier (e.g., "cycle_001")
    char state[32];                   // State descriptor (e.g., "filtercal_+5dBm")
    char timezone[16];                // Timezone string (e.g., "-07:00")
} FITS_DATA;

// Global flag for signal handling
volatile sig_atomic_t exit_flag = 0;

void Handler(int signo) {
    // Use write() for async-signal safety
    const char msg[] = "\n\n*** Interrupt signal received (Ctrl+C) - Shutting down... ***\n\n";
    write(STDERR_FILENO, msg, sizeof(msg) - 1);
    exit_flag = 1;
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

/* Get current time with timezone offset applied */
char *GET_TIME(void)
{
    char *buf = malloc(64);
    if (!buf) return NULL;
    
    time_t now = time(NULL);
    now += TIMEZONE_OFFSET_SECONDS;  // Apply timezone offset
    struct tm *t = gmtime(&now);     // Use gmtime since we already adjusted
    strftime(buf, 64, "%m%d%Y_%H%M%S", t);
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

// Allocate FITS_DATA with dynamic array
FITS_DATA* MAKE_DATA_ARRAY(int nrows, const char *cycle_id) {
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
    data->spectrum_index = 0;
    memset(data->timestamp, 0, sizeof(data->timestamp));
    strncpy(data->cycle_id, cycle_id, 31);
    data->cycle_id[31] = '\0';
    memset(data->state, 0, sizeof(data->state));
    strncpy(data->timezone, TIMEZONE_STRING, 15);
    data->timezone[15] = '\0';
    memset(data->frequencies, 0, sizeof(data->frequencies));
    return data;
}

void FREE_DATA_ARRAY(FITS_DATA **ptr) {
    if (ptr && *ptr) {
        if ((*ptr)->data) free((*ptr)->data);
        free(*ptr);
        *ptr = NULL;
    }
}

/* Reads system voltage from ADC channel 7 on HAT 3 */
double READ_SYSTEM_VOLTAGE(void) {
    UDOUBLE vltReading = ADS1263_GetChannalValue(7, ADHAT3_DRYDPIN, get_DRDYPIN(ADHAT3_DRYDPIN));
    double adcVoltage;
    
    if ((vltReading >> 31) == 1){
        adcVoltage = 5 * 2 - vltReading/2147483648.0 * 5;
    }
    else {
        adcVoltage = vltReading/2147483647.8 * 5;
    }
    
    double sysVoltage = adcVoltage * VOLTAGE_DIVIDER_FACTOR;
    
    printf("System voltage: %.2f V\n", sysVoltage);
    return sysVoltage;
}

/*
 * Collects ADC data from all three AD HATs
 * Parameters:
 *   data_row: Pointer to GetAllValues structure to store the data
 * Returns: 0 on success, -1 on failure
 */
int COLLECT_ADC_DATA(GetAllValues *data_row) {
    if (!data_row) return -1;
    
    UBYTE ChannelList[ChannelNumber] = {0,1,2,3,4,5,6};
    
    ADS1263_GetAll(ChannelList, data_row->ADHAT_1, ChannelNumber, ADHAT1_DRYDPIN, get_DRDYPIN(ADHAT1_DRYDPIN));
    ADS1263_GetAll(ChannelList, data_row->ADHAT_2, ChannelNumber, ADHAT2_DRYDPIN, get_DRDYPIN(ADHAT2_DRYDPIN));
    ADS1263_GetAll(ChannelList, data_row->ADHAT_3, ChannelNumber, ADHAT3_DRYDPIN, get_DRDYPIN(ADHAT3_DRYDPIN));
    
    return 0;
}

/*
 * Increments the Local Oscillator frequency
 * Sends GPIO pulse to Arduino to advance frequency
 * Returns: 0 on success
 */
int INCREMENT_LO_FREQUENCY(void) {
    if (LO_FREQ < FREQ_MAX) {
        // Send falling edge pulse to Arduino to advance frequency
        gpioWrite(GPIO_FREQ_INCREMENT, 0);
        gpioDelay(PULSE_LOW_US);  // low pulse (microseconds)
        
        // Rising edge: complete the pulse
        gpioWrite(GPIO_FREQ_INCREMENT, 1);
        gpioDelay(LO_SETTLE_US);  // low pulse (microseconds)
        
        // Update local frequency tracker
        LO_FREQ = LO_FREQ + FREQ_STEP;
    }
    
    return 0;
}

/*
 * Main data collection function - orchestrates the measurement cycle
 * Parameters:
 *   input_struct: FITS_DATA structure containing data buffer
 *   i: Row index in the buffer where data will be stored
 *   power_dbm: Output power level for this measurement (for display only)
 * Returns: 0 on success, -1 on error
 */
int GET_DATA(FITS_DATA *input_struct, int i, int power_dbm) {
    // Validate inputs
    if (!input_struct) return -1;
    if (i < 0 || i >= input_struct->nrows) return -1;
    if (!input_struct->data) return -1;
    
    printf("========================================\n");
    printf("LO FREQ: %.1f MHz @ %+d dBm\n", LO_FREQ, power_dbm);   
    printf("========================================\n");
    
    // Collect ADC data from all three AD HATs at current frequency
    if (COLLECT_ADC_DATA(&input_struct->data[i]) != 0) {
        fprintf(stderr, "Error: Failed to collect ADC data\n");
        return -1;
    }
    
    // Store frequency in array (will be saved to FITS later)
    input_struct->frequencies[i] = LO_FREQ;
    
    // Increment frequency for next measurement
    INCREMENT_LO_FREQUENCY();
    
    return 0;
}

/*
 * Save sweep data to FITS file with image cube format
 * Parameters:
 *   input_struct: FITS_DATA structure with sweep data
 *   nrows: Number of frequency measurements (301)
 *   power_dbm: Power level for this sweep (+5 or -4)
 * Returns: 0 on success, -1 on error
 */
int SAVE_OUTPUT(FITS_DATA* input_struct, int nrows, int power_dbm) {
    if (!input_struct) return -1;
    if (nrows != TOTAL_STEPS) {
        fprintf(stderr, "Error: Expected %d measurements, got %d\n", TOTAL_STEPS, nrows);
        return -1;
    }

    fitsfile *fptr = NULL;
    int status = 0;
    
    // Create directory structure
    char *cycle_dir = CREATE_CYCLE_DIRECTORY(OUTPUT_DIR, input_struct->cycle_id);
    if (!cycle_dir) {
        fprintf(stderr, "Error: Failed to create cycle directory\n");
        return -1;
    }
    
    // Get current timestamp and system voltage
    char *timestamp = GET_TIME();
    if (!timestamp) {
        fprintf(stderr, "Error: Failed to get timestamp\n");
        free(cycle_dir);
        return -1;
    }
    strncpy(input_struct->timestamp, timestamp, 31);
    input_struct->timestamp[31] = '\0';
    free(timestamp);
    
    input_struct->sys_voltage = READ_SYSTEM_VOLTAGE();
    input_struct->spectrum_index = 0;  // Single spectrum per file
    
    // Set state string
    snprintf(input_struct->state, sizeof(input_struct->state), "filtercal_%+ddBm", power_dbm);
    
    // Build filename: /Data/MMDDYYYY/Cycle_XXX/filtercal_±XdBm.fits
    char filename[64];
    char full_path[512];
    snprintf(filename, sizeof(filename), "filtercal_%+ddBm.fits", power_dbm);
    snprintf(full_path, sizeof(full_path), "!%s/%s", cycle_dir, filename);
    
    printf("Saving to: %s\n", full_path + 1);  // Skip '!' for display
    
    // Create FITS file with PRIMARY HDU
    if (fits_create_file(&fptr, full_path, &status)) {
        fits_report_error(stderr, status);
        free(cycle_dir);
        return -1;
    }
    
    // Create minimal primary image (required by FITS standard)
    long naxes[1] = {0};
    if (fits_create_img(fptr, BYTE_IMG, 0, naxes, &status)) {
        fits_report_error(stderr, status);
        fits_close_file(fptr, &status);
        free(cycle_dir);
        return -1;
    }
    
    // Write PRIMARY HDU headers
    if (fits_write_key(fptr, TSTRING, "CYCLE_ID", input_struct->cycle_id,
                       "Cycle identifier", &status)) {
        fits_report_error(stderr, status);
    }
    if (fits_write_key(fptr, TSTRING, "STATE", input_struct->state,
                       "Calibration state", &status)) {
        fits_report_error(stderr, status);
    }
    if (fits_write_key(fptr, TSTRING, "TIMESTAMP", input_struct->timestamp,
                       "Sweep timestamp (MMDDYYYY_HHMMSS)", &status)) {
        fits_report_error(stderr, status);
    }
    if (fits_write_key(fptr, TSTRING, "TIMEZONE", input_struct->timezone,
                       "Timezone offset", &status)) {
        fits_report_error(stderr, status);
    }
    int n_filters = 21;
    if (fits_write_key(fptr, TINT, "N_FILTERS", &n_filters,
                       "Number of filter channels", &status)) {
        fits_report_error(stderr, status);
    }
    int n_lo_pts = TOTAL_STEPS;  // 301
    if (fits_write_key(fptr, TINT, "N_LO_PTS", &n_lo_pts,
                       "Number of LO frequency points", &status)) {
        fits_report_error(stderr, status);
    }
    int n_spectra = 1;
    if (fits_write_key(fptr, TINT, "N_SPECTRA", &n_spectra,
                       "Number of spectra in this file", &status)) {
        fits_report_error(stderr, status);
    }
    if (fits_write_key(fptr, TSTRING, "DATA_FMT", "image_cube",
                       "Data format type", &status)) {
        fits_report_error(stderr, status);
    }
    if (fits_write_key(fptr, TDOUBLE, "SYSVOLT", &input_struct->sys_voltage,
                       "System voltage (V)", &status)) {
        fits_report_error(stderr, status);
    }
    
    // Create binary table extension with 5 columns
    char *ttype[] = {"DATA_CUBE", "SPECTRUM_TIMESTAMP", "SPECTRUM_INDEX", "SYSVOLT", "LO_FREQUENCIES"};
    char *tform[] = {"6321K", "32A", "J", "D", "301D"};  // 6321 = 301 freq × 21 channels
    char *tunit[] = {"ADC", "", "", "V", "MHz"};
    
    const char *extname = "FILTER CALIBRATION DATA";
    if (fits_create_tbl(fptr, BINARY_TBL, 0, 5, ttype, tform, tunit, extname, &status)) {
        fits_report_error(stderr, status);
        fits_close_file(fptr, &status);
        free(cycle_dir);
        return -1;
    }
    
    // Allocate and pack DATA_CUBE: 301 frequencies × 21 channels = 6321 values
    const int n_channels = 21;
    const int cube_size = TOTAL_STEPS * n_channels;  // 6321
    UDOUBLE *data_cube = malloc(cube_size * sizeof(UDOUBLE));
    if (!data_cube) {
        fprintf(stderr, "Error: Failed to allocate data cube\n");
        fits_close_file(fptr, &status);
        free(cycle_dir);
        return -1;
    }
    
    // Pack cube: for each frequency, write all 21 channels
    for (int freq_idx = 0; freq_idx < TOTAL_STEPS; freq_idx++) {
        for (int ch = 0; ch < 7; ch++) {
            data_cube[freq_idx * n_channels + ch] = input_struct->data[freq_idx].ADHAT_1[ch];
        }
        for (int ch = 0; ch < 7; ch++) {
            data_cube[freq_idx * n_channels + 7 + ch] = input_struct->data[freq_idx].ADHAT_2[ch];
        }
        for (int ch = 0; ch < 7; ch++) {
            data_cube[freq_idx * n_channels + 14 + ch] = input_struct->data[freq_idx].ADHAT_3[ch];
        }
    }
    
    // Build frequency array
    for (int i = 0; i < TOTAL_STEPS; i++) {
        input_struct->frequencies[i] = FREQ_MIN + i * FREQ_STEP;
    }
    
    // Write single row with all data
    if (fits_write_col(fptr, TUINT, 1, 1, 1, cube_size, data_cube, &status)) {
        fits_report_error(stderr, status);
        free(data_cube);
        fits_close_file(fptr, &status);
        free(cycle_dir);
        return -1;
    }
    
    char *timestamp_ptr = input_struct->timestamp;
    if (fits_write_col(fptr, TSTRING, 2, 1, 1, 1, &timestamp_ptr, &status)) {
        fits_report_error(stderr, status);
        free(data_cube);
        fits_close_file(fptr, &status);
        free(cycle_dir);
        return -1;
    }
    
    if (fits_write_col(fptr, TINT32BIT, 3, 1, 1, 1, &input_struct->spectrum_index, &status)) {
        fits_report_error(stderr, status);
        free(data_cube);
        fits_close_file(fptr, &status);
        free(cycle_dir);
        return -1;
    }
    
    if (fits_write_col(fptr, TDOUBLE, 4, 1, 1, 1, &input_struct->sys_voltage, &status)) {
        fits_report_error(stderr, status);
        free(data_cube);
        fits_close_file(fptr, &status);
        free(cycle_dir);
        return -1;
    }
    
    if (fits_write_col(fptr, TDOUBLE, 5, 1, 1, TOTAL_STEPS, input_struct->frequencies, &status)) {
        fits_report_error(stderr, status);
        free(data_cube);
        fits_close_file(fptr, &status);
        free(cycle_dir);
        return -1;
    }
    
    // Clean up
    free(data_cube);
    free(cycle_dir);
    
    if (fits_close_file(fptr, &status)) {
        fits_report_error(stderr, status);
        return -1;
    }
    
    printf("✓ FITS file saved: %s\n", filename);
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

int main(int argc, char **argv) {
    // Start total program timer
    time_t program_start_time = time(NULL);
    clock_t program_start_clock = clock();

    // Check command-line arguments
    if (argc != 3) {
        printf("Usage: %s <cycle_id> <timezone>\n", argv[0]);
        printf("Example: %s Cycle_02182026_001 -07:00\n", argv[0]);
        printf("         %s Cycle_02192026_015 +00:00\n", argv[0]);
        printf("Note: cycle_id format is Cycle_MMDDYYYY_### (date embedded in ID)\n");
        return 1;
    }
    char *cycle_id = argv[1];
    char *timezone = argv[2];
    
    // Parse and store timezone
    TIMEZONE_OFFSET_SECONDS = PARSE_TIMEZONE(timezone);
    strncpy(TIMEZONE_STRING, timezone, 15);
    TIMEZONE_STRING[15] = '\0';

    // Timing parameters are configurable in the source (no environment overrides)
    printf("\n=== Filter Calibration Sweep ===\n");
    printf("Cycle ID: %s\n", cycle_id);
    printf("Timezone: %s\n", TIMEZONE_STRING);
    printf("Frequency range: %.1f - %.1f MHz (step: %.1f MHz)\n", 
           FREQ_MIN, FREQ_MAX, FREQ_STEP);
    printf("Measurements per sweep: %d\n", TOTAL_STEPS);
    printf("Dual power sweep: +5 dBm → -4 dBm\n");
    printf("Output: 2 FITS files (one per power level)\n\n");

    int nrows = TOTAL_STEPS;  // One measurement per frequency step

    // Print active timing settings for transparency when tuning
    printf("Active timing settings:\n");
    printf("  LO_SETTLE_US=%d us, PULSE_LOW_US=%d us, INTER_SWEEP_WAIT_S=%d s\n", 
            LO_SETTLE_US, PULSE_LOW_US, INTER_SWEEP_WAIT_S);

    // Allocate single buffer for one complete sweep
    FITS_DATA *sweep_data = MAKE_DATA_ARRAY(nrows, cycle_id);
    if (!sweep_data) {
        printf("Failed to allocate sweep buffer\n");
        return 1;
    }
    
    INITIALIZE_ADS();
    
    if (gpioInitialise() < 0){
        printf("initialization of pigpio failed\n");
        return 1;
    }
    
    // CRITICAL: Install signal handler AFTER gpioInitialise()
    // This overrides pigpio's default signal handler
    signal(SIGINT, Handler);
    signal(SIGTERM, Handler);
    printf("✓ Signal handlers installed for Ctrl+C\n\n");
    
    // BCM numbering - Arduino Nano GPIO connections
    gpioSetMode(GPIO_FREQ_INCREMENT, PI_OUTPUT); // Increment frequency (falling edge)
    gpioSetMode(GPIO_FREQ_RESET, PI_OUTPUT);     // Reset frequency sweep (falling edge)
    gpioSetMode(GPIO_LO_POWER, PI_OUTPUT);       // LO board power control

    // Initialize: FREQ_INCREMENT and FREQ_RESET idle HIGH, LO_POWER LOW (board off)
    gpioWrite(GPIO_FREQ_INCREMENT, 1);
    gpioWrite(GPIO_FREQ_RESET, 1);
    gpioWrite(GPIO_LO_POWER, 0);  // LO board initially off
    gpioDelay(500); // 500 us settle
    
    printf("Initializing filter sweep (Band B: 900-960 MHz)...\n");
    printf("Dual power sweep: +5 dBm, then -4 dBm\n");
    
    // Reset frequency sweep to ensure starting from 900 MHz
    printf("Resetting Arduino frequency counter to start position...\n");
    gpioWrite(GPIO_FREQ_RESET, 0);
    gpioDelay(PULSE_LOW_US);  // reset low pulse (us)
    gpioWrite(GPIO_FREQ_RESET, 1);
    gpioDelay(PULSE_LOW_US);  // reset settle (us)
    printf("Frequency counter reset to %.1f MHz\n\n", FREQ_MIN);
    
    // Turn LO board ON to enable sweep
    gpioWrite(GPIO_LO_POWER, 1);
    gpioDelay(LO_SETTLE_US); // LO power settle (us)
    printf("LO board powered on\n\n");

    // Perform two sweeps at different power levels
    int power_levels[] = {+5, -4};
    double sweep_times[2] = {0.0, 0.0};  // Store sweep durations
    
    for (int sweep = 0; sweep < 2; sweep++) {
        int power_dbm = power_levels[sweep];
        printf("\n========================================\n");
        printf("Starting Sweep %d at %+d dBm\n", sweep + 1, power_dbm);
        printf("========================================\n\n");
        
        // Start sweep timer
        clock_t sweep_start = clock();
        
        // Reset frequency to start
        LO_FREQ = FREQ_MIN;
        
        // Collect all measurements for this sweep
        for (int i = 0; i < nrows; i++) {
            // Check exit flag before each measurement
            if (exit_flag) {
                printf("\nSweep interrupted by user. Cleaning up...\n");
                goto cleanup;
            }
            
            GET_DATA(sweep_data, i, power_dbm);
        }
        
        // Save sweep data to FITS file
        printf("\nSaving sweep %d data...\n", sweep + 1);
        int save_status = SAVE_OUTPUT(sweep_data, nrows, power_dbm);
        if (save_status != 0) {
            printf("Error saving sweep %d: status %d\n", sweep + 1, save_status);
        } else {
            printf("✓ Sweep %d saved successfully\n", sweep + 1);
        }
        
        // End sweep timer and store duration
        clock_t sweep_end = clock();
        sweep_times[sweep] = ((double)(sweep_end - sweep_start)) / CLOCKS_PER_SEC;
        printf("Sweep %d duration: %.2f seconds\n", sweep + 1, sweep_times[sweep]);
        
        // If not the last sweep, reset for next power level
        if (sweep < 1) {
            printf("\nPreparing for sweep %d...\n", sweep + 2);
            
            // Send RESET signal to reset frequency sweep on Arduino
            gpioWrite(GPIO_FREQ_RESET, 0);
            gpioDelay(PULSE_LOW_US); // reset low pulse (us)
            gpioWrite(GPIO_FREQ_RESET, 1);
            gpioDelay(PULSE_LOW_US); // reset settle (us)
            
            printf("Frequency reset for %+d dBm sweep\n", power_levels[sweep + 1]);
            printf("Allowing LO to stabilize output power...\n");
            sleep(INTER_SWEEP_WAIT_S); // seconds settling time for LO power stabilization
        }
    }
    
    printf("\n========================================\n");
    printf("Both sweeps completed successfully!\n");
    printf("========================================\n");

cleanup:
    FREE_DATA_ARRAY(&sweep_data);
    
    printf("\nShutting down...\n");
    
    // Reset Arduino to initial state (frequency counter reset)
    // Some firmware requires two pulses to reliably return to initial state.
    for (int _r = 0; _r < 2; _r++) {
        gpioWrite(GPIO_FREQ_RESET, 0);
        gpioDelay(10000);  // 10ms LOW pulse
        gpioWrite(GPIO_FREQ_RESET, 1);
        gpioDelay(5000);   // 5ms settle
    }
    printf("Arduino reset (double pulse)\n");
    
    // Power down LO board
    gpioWrite(GPIO_LO_POWER, 0);
    gpioDelay(5000);
    printf("LO board powered down\n");
    
    gpioTerminate();
    CLOSE_GPIO();

    // Calculate total program runtime
    time_t program_end_time = time(NULL);
    clock_t program_end_clock = clock();
    double total_cpu_time = ((double)(program_end_clock - program_start_clock)) / CLOCKS_PER_SEC;
    double total_wall_time = difftime(program_end_time, program_start_time);
    
    printf("\n========================================\n");
    printf("TIMING SUMMARY\n");
    printf("========================================\n");
    printf("Sweep 1 (+5 dBm):  %.2f seconds\n", sweep_times[0]);
    printf("Sweep 2 (-4 dBm):  %.2f seconds\n", sweep_times[1]);
    printf("Total sweep time:  %.2f seconds\n", sweep_times[0] + sweep_times[1]);
    printf("----------------------------------------\n");
    printf("Total CPU time:    %.2f seconds\n", total_cpu_time);
    printf("Total wall time:   %.0f seconds (%.1f minutes)\n", total_wall_time, total_wall_time / 60.0);
    printf("========================================\n");

    printf("\n========================================\n");
    printf("Filter sweep program terminated\n");
    printf("========================================\n");

    return 0;
}
