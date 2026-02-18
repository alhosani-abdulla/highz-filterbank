/*
 * High-Precision AD HAT Data Acquisition System
 * 
 * This program implements a multi-threaded data acquisition system for three AD HATs
 * (Analog-to-Digital Hardware Attached on Top) connected to a Raspberry Pi. It performs
 * continuous frequency sweeps while collecting data from multiple ADC channels and saves
 * the results in FITS format (commonly used in astronomy).
 */

/* Standard C Libraries */
#include <stdio.h>    // Standard I/O operations
#include <stdlib.h>   // Memory allocation, random numbers
#include <string.h>   // String manipulation
#include <signal.h>   // Signal handling
#include <pthread.h>  // POSIX threading
#include <time.h>     // Time functions
#include <math.h>     // Mathematical functions
#include <unistd.h>   // POSIX API (write, usleep)
#include <sys/stat.h> // Directory creation
#include <errno.h>    // Error codes

/* Hardware-Specific Libraries */
#include <fitsio.h>   // FITS file format handling
#include <pigpio.h>   // Raspberry Pi GPIO control

/* Custom Hardware Driver - Updated path for organized highz directory structure */
#include "/home/peterson/highz/High-Precision_AD_HAT/c/lib/Driver/ADS1263.h"  // AD HAT driver

/* ============= Types and Constants ============= */

/* Number of ADC channels to read from each AD HAT */
#define ChannelNumber 7

/* GPIO pin definitions AD HATs (BCM numbering) */
const int ADHAT1_DRYDPIN = 12;  // ADC data ready pin for first AD HAT
const int ADHAT2_DRYDPIN = 22;  // ADC data ready pin for second AD HAT
const int ADHAT3_DRYDPIN = 23;  // ADC data ready pin for third AD HAT

/* GPIO pin definitions for Arduino Nano control (BCM numbering) */
const int GPIO_FREQ_INCREMENT = 4;  // Increment frequency (falling edge trigger)
const int GPIO_FREQ_RESET = 5;      // Reset frequency sweep (falling edge trigger)
const int GPIO_LO_POWER = 6;        // LO board power control (HIGH=ON, LOW=OFF)

/* Frequency Sweep Parameters - Data Acquisition: 650-936 MHz, 2 MHz steps */
#define FREQ_MIN 650.0              // Starting frequency (MHz)
#define FREQ_MAX 936.0              // Ending frequency (MHz)
#define FREQ_STEP 2.0               // Frequency increment per step (MHz)
#define TOTAL_STEPS 144             // Calculated: (FREQ_MAX - FREQ_MIN) / FREQ_STEP + 1 = (936-650)/2 + 1

/* Output Directory Configuration */
const char *OUTPUT_DIR = "/media/peterson/INDURANCE/Data";  // Directory for saving FITS files

/* Performance Monitoring Configuration */
const int ENABLE_TIMING_OUTPUT = 1;           // Set to 1 to enable sweep timing output, 0 to disable
const int ENABLE_VERBOSE_MEASUREMENT = 0;     // Set to 1 to enable per-measurement debug output, 0 to disable
const int ENABLE_VERBOSE_SWEEP = 1;           // Set to 1 to enable per-sweep debug output, 0 to disable

/* Voltage Divider Configuration */
const double VOLTAGE_DIVIDER_FACTOR = 11.0;   // Voltage divider factor for system voltage measurement (actual voltage = ADC reading * factor)

// Configurable timing parameters
// All times are in milliseconds unless noted otherwise.
int LO_SETTLE_US = 50;        // usleep in GET_DATA (50 microseconds)
int PULSE_LOW_US = 50;        // gpioDelay for low pulse when incrementing (microseconds)
int INTER_SWEEP_WAIT_S = 0.1;   // seconds between sweeps for LO stabilization

/* Global Variables for Frequency Control */
double LO_FREQ = FREQ_MIN;     // Local Oscillator starting frequency (initialized to FREQ_MIN)

/* 
 * Structure to hold data from all three AD HATs
 * Each instance represents one measurement at a single frequency
 */
typedef struct {
    UDOUBLE ADHAT_1[ChannelNumber];  // Data from first AD HAT (7 channels)
    UDOUBLE ADHAT_2[ChannelNumber];  // Data from second AD HAT (7 channels)
    UDOUBLE ADHAT_3[ChannelNumber];  // Data from third AD HAT (7 channels)
} GetAllValues;

/* 
 * Structure for managing FITS file data
 * Contains an array of measurements for one complete frequency sweep
 */
typedef struct {
    GetAllValues *data;      // Array of 144 measurements (one per frequency)
    int nrows;              // Number of measurements (should be 144)
    double sys_voltage;     // System voltage (read once per sweep)
    char timestamp[32];     // Timestamp for this sweep
    double frequencies[TOTAL_STEPS]; // Array of LO frequencies for this sweep
    int spectrum_index;     // Index of this spectrum (for multi-sweep files)
    char cycle_id[32];      // Cycle identifier (e.g., "cycle_001")
    int state;              // State for this sweep (0-7)
} FITS_DATA;

/* ============= Double Buffer System and Thread Synchronization ============= */

/*
 * Double-buffering system:
 * Uses two buffers to allow simultaneous data collection and writing.
 * While one buffer is being filled with new data, the other can be written to disk.
 */
FITS_DATA *bufferA = NULL;  // First buffer for double-buffering
FITS_DATA *bufferB = NULL;  // Second buffer for double-buffering

/* Thread Synchronization Primitives */
pthread_mutex_t buffer_mutex = PTHREAD_MUTEX_INITIALIZER;     // Protects buffer access
pthread_cond_t buffer_ready_cond = PTHREAD_COND_INITIALIZER;  // Signals buffer ready to write

/* Buffer State Tracking */
int buffer_to_write = 0;   // 0 = none, 1 = bufferA, 2 = bufferB
volatile sig_atomic_t exit_flag = 0;  // Program termination flag (volatile for signal safety)

/* Global thread handle for cleanup in signal handler */
pthread_t global_writer_thread;

/* 
 * Structure for passing parameters to writer thread
 * Contains information needed for FITS file creation
 */
typedef struct {
    const char *filename;  // Output filename (not used with new format)
    int nrows;            // Number of rows per sweep (should be 144)
    int state;            // Switch state value
    char cycle_id[32];    // Cycle identifier
} writer_args_t;

/* ============= Forward Declarations ============= */
void FREE_DATA_ARRAY(FITS_DATA **ptr);
int CLOSE_GPIO(void);

/* ============= Helper Functions ============= */

/*
 * Signal handler for clean program termination
 * Parameters:
 *   signo: Signal number received
 * Returns: void
 * Note: Sets exit_flag to trigger cleanup in main loop
 */
void Handler(int signo) {
    // Use write() instead of printf() as it's async-signal-safe
    const char msg[] = "\n\n*** Interrupt signal received (Ctrl+C) - Shutting down... ***\n\n";
    write(STDERR_FILENO, msg, sizeof(msg) - 1);
    
    // Set exit flag - main loop will handle cleanup
    exit_flag = 1;
    
    // Wake up writer thread if it's waiting
    pthread_cond_signal(&buffer_ready_cond);

    // Return LO control pins to idle HIGH state (ready for next trigger)
    gpioWrite(GPIO_FREQ_INCREMENT, 1);
    gpioWrite(GPIO_FREQ_RESET, 1);
    gpioDelay(LO_SETTLE_US);
    printf("✓ LO control pins returned to idle HIGH\n");

    // Power down LO board (filterSweep needs it off)
    gpioWrite(GPIO_LO_POWER, 0);
    gpioDelay(LO_SETTLE_US);
    printf("✓ LO board powered down\n");
}

/*
 * Generates timestamp string in format "MMDDYYYY_HHMMSS.fits"
 * Returns:
 *   char*: Dynamically allocated string with current timestamp
 *   NULL: If memory allocation fails
 * Note: Caller must free the returned string
 */
char *GET_TIME(void)
{
    char *buf = malloc(64);
    if (!buf) {
        fprintf(stderr, "Error: Failed to allocate memory for timestamp buffer\n");
        // Could also log system error info:
        perror("GET_TIME malloc failed");
        return NULL;
    }
    
    time_t now = time(NULL);
    struct tm *t = localtime(&now);
    if (!t) {
        fprintf(stderr, "Error: Failed to get local time\n");
        free(buf);  // Clean up allocated memory
        return NULL;
    }
    
    if (strftime(buf, 64, "%m%d%Y_%H%M%S", t) == 0) {
        fprintf(stderr, "Error: Failed to format time string\n");
        free(buf);  // Clean up allocated memory
        return NULL;
    }

    return buf;
}

/*
 * Gets date string in format "MMDDYYYY" for directory creation
 * Returns:
 *   char*: Dynamically allocated string with current date
 *   NULL: If memory allocation fails
 * Note: Caller must free the returned string
 */
char *GET_DATE(void)
{
    char *buf = malloc(16);
    if (!buf) {
        fprintf(stderr, "Error: Failed to allocate memory for date buffer\n");
        perror("GET_DATE malloc failed");
        return NULL;
    }
    
    time_t now = time(NULL);
    struct tm *t = localtime(&now);
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

/*
 * Creates date-based directory if it doesn't exist
 * Parameters:
 *   output_dir: Base output directory path
 * Returns:
 *   char*: Full path to date directory (caller must free)
 *   NULL: On error
 */
char *CREATE_DATE_DIRECTORY(const char *output_dir)
{
    char *date_str = GET_DATE();
    if (!date_str) {
        return NULL;
    }
    
    // Allocate buffer for full path: output_dir + "/" + date + null terminator
    size_t path_len = strlen(output_dir) + 1 + strlen(date_str) + 1;
    char *full_path = malloc(path_len);
    if (!full_path) {
        fprintf(stderr, "Error: Failed to allocate memory for directory path\n");
        free(date_str);
        return NULL;
    }
    
    snprintf(full_path, path_len, "%s/%s", output_dir, date_str);
    free(date_str);
    
    // Create directory if it doesn't exist (mkdir -p behavior)
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

/*
 * Creates cycle-based directory under date directory if it doesn't exist
 * Parameters:
 *   output_dir: Base output directory path
 *   cycle_id: Cycle identifier (e.g., "cycle_001")
 * Returns:
 *   char*: Full path to cycle directory (caller must free)
 *   NULL: On error
 */
char *CREATE_CYCLE_DIRECTORY(const char *output_dir, const char *cycle_id)
{
    if (!output_dir || !cycle_id) {
        fprintf(stderr, "Error: Invalid parameters for CREATE_CYCLE_DIRECTORY\n");
        return NULL;
    }
    
    // First create date directory
    char *date_dir = CREATE_DATE_DIRECTORY(output_dir);
    if (!date_dir) {
        return NULL;
    }
    
    // Allocate buffer for full path: date_dir + "/" + cycle_id + null terminator
    size_t path_len = strlen(date_dir) + 1 + strlen(cycle_id) + 1;
    char *full_path = malloc(path_len);
    if (!full_path) {
        fprintf(stderr, "Error: Failed to allocate memory for cycle directory path\n");
        free(date_dir);
        return NULL;
    }
    
    snprintf(full_path, path_len, "%s/%s", date_dir, cycle_id);
    free(date_dir);
    
    // Create cycle directory if it doesn't exist
    struct stat st = {0};
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
    data->sys_voltage = 0.0;  // Initialize system voltage
    return data;
}

void FREE_DATA_ARRAY(FITS_DATA **ptr) {
    if (ptr && *ptr) {
        if ((*ptr)->data) free((*ptr)->data);
        free(*ptr);
        *ptr = NULL;
    }
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
 * Reads system voltage from ADC channel 7 on HAT 23
 * Returns: Actual system voltage in volts (after applying voltage divider factor)
 */
double READ_SYSTEM_VOLTAGE(void) {
    UDOUBLE vltReading = ADS1263_GetChannalValue(7, ADHAT3_DRYDPIN, get_DRDYPIN(ADHAT3_DRYDPIN));
    double adcVoltage;
    
    if ((vltReading >> 31) == 1){
        adcVoltage = 5 * 2 - vltReading/2147483648.0 * 5;
    }
    else {
        adcVoltage = vltReading/2147483647.8 * 5;
    }
    
    // Apply voltage divider factor to get actual system voltage
    double sysVoltage = adcVoltage * VOLTAGE_DIVIDER_FACTOR;
    
    if (ENABLE_VERBOSE_SWEEP) {
        printf("Sys Voltage (ADC) = %.6f V, Actual Sys Voltage = %.6f V\n", adcVoltage, sysVoltage);
    }
    return sysVoltage;
}

/*
 * Stores metadata into data structure
 * Parameters:
 *   data_row: Pointer to GetAllValues structure to fill
 *   timestamp: Timestamp string
 *   state: Switch state value
 * Returns: 0 on success
 */
/*
 * Stores the current LO frequency in the sweep's frequency array
 * Parameters:
 *   input_struct: FITS_DATA structure containing frequency array
 *   index: Index in the frequency array (0-143)
 * Returns: 0 on success, -1 on error
 */
int STORE_FREQUENCY(FITS_DATA *input_struct, int index) {
    if (!input_struct) return -1;
    if (index < 0 || index >= TOTAL_STEPS) return -1;
    
    input_struct->frequencies[index] = LO_FREQ;
    return 0;
}

/*
 * Increments or resets the Local Oscillator frequency
 * Manages GPIO signals to Arduino for frequency control
 * Returns: 0 on success
 */
int INCREMENT_LO_FREQUENCY(void) {
    clock_t start_time, end_time;
    double cpu_time_used;
    
    start_time = clock();
    
    // Check if we can increment (allow incrementing up to and including FREQ_MAX)
    if (LO_FREQ < FREQ_MAX){
        // Increment to next frequency
        gpioWrite(GPIO_FREQ_INCREMENT, 0); // Falling edge triggers Arduino
        gpioDelay(PULSE_LOW_US);           // Short delay to ensure proper timing
        gpioWrite(GPIO_FREQ_INCREMENT, 1); // Return to idle HIGH state (ready for next trigger)
        gpioDelay(LO_SETTLE_US);           // Short delay to ensure proper timing
        LO_FREQ = LO_FREQ + FREQ_STEP;
    }
    else {
        // Reset to minimum frequency after reaching maximum
        gpioWrite(GPIO_FREQ_RESET, 0);     // Falling edge triggers Arduino reset
        gpioDelay(PULSE_LOW_US);           // Short delay to ensure proper timing
        gpioWrite(GPIO_FREQ_RESET, 1);     // Return to idle HIGH state (ready for next trigger)
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

/*
 * Main data collection function - orchestrates the measurement cycle
 * Parameters:
 *   input_struct: FITS_DATA structure containing data buffer
 *   i: Row index in the buffer where data will be stored (0-143)
 * Returns: 
 *   0 on success
 *   -1 on error
 */
int GET_DATA(FITS_DATA *input_struct, int i) {
    // Validate inputs
    if (!input_struct) return -1;
    if (i < 0 || i >= input_struct->nrows) return -1;
    if (!input_struct->data) return -1;
    
    if (ENABLE_VERBOSE_MEASUREMENT) {
        printf("##########################################\n");
        printf("MEASURING AT LO FREQ: %lf MHz\n", LO_FREQ);
        printf("##########################################\n");
    }

    // Collect ADC data from all three AD HATs at current frequency
    if (COLLECT_ADC_DATA(&input_struct->data[i]) != 0) {
        fprintf(stderr, "Error: Failed to collect ADC data\n");
        return -1;
    }
    
    // Store the current frequency in the sweep's frequency array
    if (STORE_FREQUENCY(input_struct, i) != 0) {
        fprintf(stderr, "Error: Failed to store frequency\n");
        return -1;
    }
    
    // Increment frequency for next measurement
    INCREMENT_LO_FREQUENCY();
    
    return 0;
}

/*
 * Saves collected data to FITS file format (Image Cube format)
 * Parameters:
 *   input_struct: FITS_DATA structure containing one complete sweep
 *   state: Current state value (for primary header)
 * Returns: 0 on success, -1 or FITS error code on failure
 */
/*
 * Saves collected sweep data to FITS file in cube format
 * Creates or appends to state-specific FITS file in cycle directory
 * File structure: /Data/MMDDYYYY/Cycle_XXX/state_Y.fits
 * 
 * Parameters:
 *   input_struct: FITS_DATA structure containing sweep data
 *   state: State value (0-7), used for informational purposes (state already in struct)
 * Returns:
 *   0 on success
 *   negative value on error
 */
int SAVE_OUTPUT(FITS_DATA* input_struct, int state) {
    if (!input_struct) return -1;

    fitsfile *fptr;
    int status = 0;
    const int num_channels = ChannelNumber * 3;  // 21 total channels (7 per hat × 3 hats)
    const int cube_size = TOTAL_STEPS * num_channels;  // 144 × 21 = 3024 values
    
    // Create cycle directory
    char *cycle_dir = CREATE_CYCLE_DIRECTORY(OUTPUT_DIR, input_struct->cycle_id);
    if (!cycle_dir) {
        fprintf(stderr, "Error: Failed to create cycle directory\n");
        return -1;
    }
    
    // Construct filename: {cycle_dir}/state_{state}.fits
    char filepath[512];
    snprintf(filepath, sizeof(filepath), "%s/state_%d.fits", cycle_dir, input_struct->state);
    
    // Check if file exists using stat (don't use ! prefix yet)
    struct stat st = {0};
    int file_exists = (stat(filepath, &st)== 0);
    
    int n_spectra_current = 0;
    long current_rows = 0;
    
    if (!file_exists) {
        // File doesn't exist - create new file
        char fits_filename[520];
        snprintf(fits_filename, sizeof(fits_filename), "!%s", filepath);  // ! forces overwrite
        
        if (fits_create_file(&fptr, fits_filename, &status)) {
            fprintf(stderr, "Error creating FITS file: %s\n", filepath);
            fits_report_error(stderr, status);
            free(cycle_dir);
            return status;
        }
        
        // Create null primary array (BITPIX=8, NAXIS=0)
        long naxes = 0;
        if (fits_create_img(fptr, BYTE_IMG, 0, &naxes, &status)) {
            fprintf(stderr, "Error creating primary HDU\n");
            fits_report_error(stderr, status);
            fits_close_file(fptr, &status);
            free(cycle_dir);
            return status;
        }
        
        // Write primary header keywords
        int n_spectra = 1;  // First sweep
        int n_lo_pts = TOTAL_STEPS;
        char data_fmt[] = "image_cube";
        char timezone[] = "EST (GMT-5)";
        char antenna[] = "Unknown";
        char ant_size[] = "Unknown";
        char ant_note[] = "See observation log";
        
        if (fits_update_key(fptr, TSTRING, "CYCLE_ID", input_struct->cycle_id, "Observation cycle identifier", &status) ||
            fits_update_key(fptr, TINT, "STATE", &input_struct->state, "Switch state", &status) ||
            fits_update_key(fptr, TINT, "N_FILTERS", (int*)&num_channels, "Number of filter channels", &status) ||
            fits_update_key(fptr, TINT, "N_LO_PTS", &n_lo_pts, "Number of LO frequency points", &status) ||
            fits_update_key(fptr, TINT, "N_SPECTRA", &n_spectra, "Number of spectra in this file", &status) ||
            fits_update_key(fptr, TSTRING, "DATA_FMT", data_fmt, "Data format type", &status) ||
            fits_update_key(fptr, TDOUBLE, "SYSVOLT", &input_struct->sys_voltage, "System voltage (V)", &status) ||
            fits_update_key(fptr, TSTRING, "TIMEZONE", timezone, "Local timezone", &status) ||
            fits_update_key(fptr, TSTRING, "ANTENNA", antenna, "Antenna identifier", &status) ||
            fits_update_key(fptr, TSTRING, "ANT_SIZE", ant_size, "Antenna size", &status) ||
            fits_update_key(fptr, TSTRING, "ANT_NOTE", ant_note, "Antenna notes", &status)) {
            fits_report_error(stderr, status);
            fits_close_file(fptr, &status);
            free(cycle_dir);
            return status;
        }
        
        // Create binary table extension
        char *ttype[] = {"DATA_CUBE", "SPECTRUM_TIMESTAMP", "SPECTRUM_INDEX", "SYSVOLT", "LO_FREQUENCIES"};
        char *tform[] = {"3024J", "25A", "1J", "1E", "144E"};
        char *tunit[] = {"", "", "", "volts", "MHz"};
        const char *extname = "IMAGE CUBE DATA";
        
        if (fits_create_tbl(fptr, BINARY_TBL, 0, 5, ttype, tform, tunit, extname, &status)) {
            fits_report_error(stderr, status);
            fits_close_file(fptr, &status);
            free(cycle_dir);
            return status;
        }
        
        printf("Created new FITS file: %s\n", filepath);
        current_rows = 0;  // No rows yet
        
    } else {
        // File exists - open for appending
        if (fits_open_file(&fptr, filepath, READWRITE, &status)) {
            fprintf(stderr, "Error opening existing FITS file: %s\n", filepath);
            fits_report_error(stderr, status);
            free(cycle_dir);
            return status;
        }
        
        // Read current N_SPECTRA
        if (fits_read_key(fptr, TINT, "N_SPECTRA", &n_spectra_current, NULL, &status)) {
            fprintf(stderr, "Error reading N_SPECTRA from header\n");
            fits_report_error(stderr, status);
            fits_close_file(fptr, &status);
            free(cycle_dir);
            return status;
        }
        
        // Move to binary table extension
        if (fits_movnam_hdu(fptr, BINARY_TBL, (char*)"IMAGE CUBE DATA", 0, &status)) {
            fprintf(stderr, "Error moving to binary table HDU\n");
            fits_report_error(stderr, status);
            fits_close_file(fptr, &status);
            free(cycle_dir);
            return status;
        }
        
        // Get current number of rows
        if (fits_get_num_rows(fptr, &current_rows, &status)) {
            fprintf(stderr, "Error getting number of rows\n");
            fits_report_error(stderr, status);
            fits_close_file(fptr, &status);
            free(cycle_dir);
            return status;
        }
        
        // Insert one new row at the end
        if (fits_insert_rows(fptr, current_rows, 1, &status)) {
            fprintf(stderr, "Error inserting new row\n");
            fits_report_error(stderr, status);
            fits_close_file(fptr, &status);
            free(cycle_dir);
            return status;
        }
        
        // Update N_SPECTRA in primary header
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
    
    // Allocate and populate DATA_CUBE (interleaved: all 21 channels for freq 1, then all 21 for freq 2, etc.)
    UDOUBLE *data_cube = malloc(sizeof(UDOUBLE) * cube_size);
    if (!data_cube) {
        fprintf(stderr, "Memory allocation failed for data cube\n");
        fits_close_file(fptr, &status);
        return -1;
    }
    
    // Fill data cube: for each frequency, pack all 21 channels
    for (int freq_idx = 0; freq_idx < TOTAL_STEPS; freq_idx++) {
        int cube_offset = freq_idx * num_channels;
        // Pack ADHAT_1 (channels 0-6)
        for (int ch = 0; ch < ChannelNumber; ch++) {
            data_cube[cube_offset + ch] = input_struct->data[freq_idx].ADHAT_1[ch];
        }
        // Pack ADHAT_2 (channels 7-13)
        for (int ch = 0; ch < ChannelNumber; ch++) {
            data_cube[cube_offset + ChannelNumber + ch] = input_struct->data[freq_idx].ADHAT_2[ch];
        }
        // Pack ADHAT_3 (channels 14-20)
        for (int ch = 0; ch < ChannelNumber; ch++) {
            data_cube[cube_offset + 2*ChannelNumber + ch] = input_struct->data[freq_idx].ADHAT_3[ch];
        }
    }
    
    // Convert frequencies from double to float for FITS
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
    
    // Write to the new row (current_rows + 1)
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
    
    // Clean up and close
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

// Clean shutdown - power down LO board and disconnect from pigpio
void CLEANUP_AND_SHUTDOWN(void)
{
    printf("\n========================================\n");
    printf("Starting cleanup procedure...\n");
    printf("========================================\n");
    
    // Return LO control pins to idle HIGH state (ready for next use)
    gpioWrite(GPIO_FREQ_INCREMENT, 1);
    gpioWrite(GPIO_FREQ_RESET, 1);
    gpioDelay(LO_SETTLE_US);
    printf("✓ LO control pins returned to idle HIGH\n");

    // Power down LO board (filterSweep requires LO board to be off)
    gpioWrite(GPIO_LO_POWER, 0);
    gpioDelay(LO_SETTLE_US);
    printf("✓ LO board powered down\n");
    
    // Release GPIO hardware access (allows next process to initialize)
    gpioTerminate();
    printf("✓ GPIO hardware released\n");
    
    // Close AD HAT GPIOs
    CLOSE_GPIO();
    printf("✓ AD HAT GPIOs closed\n");
    
    printf("========================================\n");
    printf("Cleanup complete\n");
    printf("========================================\n");
}

// Writer thread function now accepts struct with state and nrows
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
        if (exit_flag) {
            pthread_mutex_unlock(&buffer_mutex);
            break;
        }

        FITS_DATA *buf = NULL;
        if (buffer_to_write == 1) buf = bufferA;
        else if (buffer_to_write == 2) buf = bufferB;

        buffer_to_write = 0;
        pthread_mutex_unlock(&buffer_mutex);

        //printf("buffer ptr before if statement %p\n", (void *)buf);
        //printf("buffer itself before if statement %p\n", (void *)&buf);
        
        if (buf) {
            //printf("buffer ptr in if statement %p\n", (void *)buf);
            //printf("buffer itself in if statement %p\n", (void *)&buf);
            
            if (ENABLE_VERBOSE_SWEEP) {
                printf("ABOUT TO SAVE DATA...\n");
            }
            clock_t start_time, end_time;
            double cpu_time_used;
        
            start_time = clock();
                    
            int status = SAVE_OUTPUT(buf, state);
            
            end_time = clock();

            if (ENABLE_VERBOSE_SWEEP) {
                printf("STATUS: %d\n", status);
            }
            
            if (status != 0) {
                printf("Error saving FITS data: %d\n", status);
            }
            
            //printf("###################################################################################################################################################################");
                
            cpu_time_used = ((double) (end_time-start_time)) / CLOCKS_PER_SEC;
            //printf("TIME TAKEN TO SAVE DATA: %f\n", cpu_time_used);
            }
        }
    return NULL;
}

int main(int argc, char **argv) {
    // Parse command-line arguments
    if (argc != 4) {
        fprintf(stderr, "Usage: %s <cycle_id> <state> <num_spectra>\n", argv[0]);
        fprintf(stderr, "  <cycle_id>    : Cycle identifier (e.g., 'cycle_001')\n");
        fprintf(stderr, "  <state>       : State value (0-7)\n");
        fprintf(stderr, "                  0=Antenna, 1=Open, 2=Short, 3=Long Cable Open,\n");
        fprintf(stderr, "                  4=Black Body, 5=Ambient, 6=Noise Diode, 7=Long Cable Short\n");
        fprintf(stderr, "  <num_spectra> : Number of sweeps/spectra to collect (positive integer)\n");
        return 1;
    }
    
    // Parse cycle_id argument
    char cycle_id[32];
    strncpy(cycle_id, argv[1], 31);
    cycle_id[31] = '\0';
    
    // Parse state argument
    char *endptr;
    long state_long = strtol(argv[2], &endptr, 10);
    if (*endptr != '\0' || state_long < 0 || state_long > 7) {
        fprintf(stderr, "Error: Invalid state '%s'. Must be integer 0-7.\n", argv[2]);
        return 1;
    }
    int target_state = (int)state_long;
    
    // Parse num_spectra argument
    long num_spectra_long = strtol(argv[3], &endptr, 10);
    if (*endptr != '\0' || num_spectra_long <= 0) {
        fprintf(stderr, "Error: Invalid num_spectra '%s'. Must be positive integer.\n", argv[3]);
        return 1;
    }
    int num_spectra = (int)num_spectra_long;
    
    // State name lookup for display
    const char *state_names[] = {
        "Antenna", "Open Circuit", "Short Circuit", "Long Cable Open Circuit",
        "Black Body", "Ambient Temperature Load", "Noise Diode", "Long Cable Short Circuit"
    };
    
    // Use TOTAL_STEPS constant for nrows (calculated from FREQ_MIN, FREQ_MAX, FREQ_STEP)
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
    
    // Set cycle_id and state in both buffers
    strncpy(bufferA->cycle_id, cycle_id, 31);
    bufferA->cycle_id[31] = '\0';
    bufferA->state = target_state;
    
    strncpy(bufferB->cycle_id, cycle_id, 31);
    bufferB->cycle_id[31] = '\0';
    bufferB->state = target_state;
    
    INITIALIZE_ADS();
    
    // Initialize pigpio for direct GPIO hardware access
    // Note: Each process independently initializes/terminates GPIO access
    if (gpioInitialise() < 0) {
        fprintf(stderr, "Error: Failed to initialize pigpio for GPIO access.\n");
        fprintf(stderr, "Make sure no other process has locked the GPIO hardware.\n");
        return 1;
    }
    printf("✓ pigpio initialized for GPIO access\n");
    
    // Install signal handler for graceful shutdown on Ctrl+C
    signal(SIGINT, Handler);
    signal(SIGTERM, Handler);
    printf("✓ Signal handlers installed for Ctrl+C\n");
    
    // Configure GPIO pins for LO board control (BCM numbering)
    // Note: state_ctrl may have already configured these, but we ensure they're set correctly
    gpioSetMode(GPIO_FREQ_INCREMENT, PI_OUTPUT); // Increment frequency (falling edge trigger)
    gpioSetMode(GPIO_FREQ_RESET, PI_OUTPUT);     // Reset frequency sweep (falling edge trigger)
    gpioSetMode(GPIO_LO_POWER, PI_OUTPUT);       // LO board power control

    // Set LO control pins to idle HIGH state, LO_POWER LOW (board off initially)
    gpioWrite(GPIO_FREQ_INCREMENT, 1);
    gpioWrite(GPIO_FREQ_RESET, 1);
    gpioDelay(LO_SETTLE_US); // 5 ms settle
    
    // Turn LO board ON and reset frequency counter
    gpioWrite(GPIO_LO_POWER, 1);  // Power on LO board
    gpioDelay(LO_SETTLE_US); // 10 ms for LO board to stabilize
    
    // Reset frequency counter to starting position
    gpioWrite(GPIO_FREQ_RESET, 0);  // Falling edge to reset
    gpioDelay(PULSE_LOW_US); // 5 ms LOW pulse
    gpioWrite(GPIO_FREQ_RESET, 1);  // Return to idle HIGH
    gpioDelay(LO_SETTLE_US); // 5 ms settle

    sleep(1); // Additional 1 second delay to ensure LO stability

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
    
    // Sweep timing variables
    clock_t sweep_start_time, sweep_end_time, program_start_time;
    double sweep_time_used;
    int sweep_count = 0;
    double total_sweep_time = 0.0;
    double min_sweep_time = -1.0;
    double max_sweep_time = 0.0;
    
    // Start program timer
    program_start_time = clock();
    
    while (!exit_flag && sweeps_completed < num_spectra) {
        clock_t start_time, end_time;
        double cpu_time_used;
        
        start_time = clock();
        //printf("LOOP BEGAN: %ld\n", (long)start_time);
        FITS_DATA *active_buffer = (current_buffer == 1) ? bufferA : bufferB;
        
        // Read system voltage and set sweep metadata at the start of each sweep
        if (row_index == 0) {
            active_buffer->sys_voltage = READ_SYSTEM_VOLTAGE();
            
            // Generate timestamp for this sweep
            char *sweep_time = GET_TIME();
            if (!sweep_time) {
                fprintf(stderr, "Error: Failed to generate sweep timestamp\n");
                break;
            }
            snprintf(active_buffer->timestamp, sizeof(active_buffer->timestamp), "%s.fits", sweep_time);
            free(sweep_time);
            
            // Set spectrum index (0-based index for sweeps in this file)
            active_buffer->spectrum_index = sweeps_completed;
            
            // Start timing this sweep (always record time if timing enabled)
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
        
        // Check for interrupt signal immediately after GET_DATA
        if (exit_flag) {
            printf("\nExit signal detected. Breaking out of main loop...\n");
            break;
        }
        
        // Check for errors
        if (result != 0) {
            printf("Error occurred in GET_DATA. Exiting main loop...\n");
            break;
        }
        
        row_index++;

        // Check if sweep is complete
        if (row_index >= nrows) {
            // Calculate sweep timing and statistics
            sweep_end_time = clock();
            sweep_time_used = ((double) (sweep_end_time - sweep_start_time)) / CLOCKS_PER_SEC;
            sweep_count++;
            
            // Update statistics
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
            
            // Signal writer thread to save this buffer
            pthread_mutex_lock(&buffer_mutex);
            buffer_to_write = current_buffer;
            pthread_cond_signal(&buffer_ready_cond);
            pthread_mutex_unlock(&buffer_mutex);
            
            sweeps_completed++;
            
            // Check if we've collected the requested number of sweeps
            if (sweeps_completed >= num_spectra) {
                printf("\n========================================\n");
                printf("Target reached: Collected %d sweeps for State %d\n", sweeps_completed, target_state);
                printf("Exiting data acquisition...\n");
                printf("========================================\n");
                exit_flag = 1;
                break;  // Exit the main loop
            }

            current_buffer = (current_buffer == 1) ? 2 : 1;
            row_index = 0;
        }
        end_time = clock();
        //printf("LOOP ENDED: %ld\n", (long)end_time);
        
        cpu_time_used = ((double) (end_time-start_time)) / CLOCKS_PER_SEC;
        if (ENABLE_VERBOSE_MEASUREMENT) {
            printf("LOOP EXECUTION TIME: %f seconds\n", cpu_time_used);
        }
    }

    // Clean shutdown sequence - executed whether exiting normally or via Ctrl+C
    printf("\n========================================\n");
    printf("Beginning clean shutdown sequence...\n");
    printf("========================================\n");
    
    // Step 1: Signal writer thread to stop and wait for it to finish
    printf("Step 1/4: Signaling writer thread to stop...\n");
    pthread_mutex_lock(&buffer_mutex);
    exit_flag = 1;
    pthread_cond_signal(&buffer_ready_cond);
    pthread_mutex_unlock(&buffer_mutex);

    printf("Waiting for writer thread to complete...\n");
    pthread_join(global_writer_thread, NULL);
    printf("✓ Writer thread completed\n");

    // Step 2: Free allocated buffers
    printf("\nStep 2/4: Freeing data buffers...\n");
    FREE_DATA_ARRAY(&bufferA);
    FREE_DATA_ARRAY(&bufferB);
    printf("✓ Buffers freed\n");
    
    // Step 3: Clean shutdown of all hardware (GPIO, LO board, AD HATs)
    printf("\nStep 3/4: Shutting down hardware...\n");
    CLEANUP_AND_SHUTDOWN();
    
    // Step 4: Final summary with statistics
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