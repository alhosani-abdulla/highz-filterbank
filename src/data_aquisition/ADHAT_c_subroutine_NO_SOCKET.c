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

/* Hardware-Specific Libraries */
#include <fitsio.h>   // FITS file format handling
#include <pigpio.h>   // Raspberry Pi GPIO control

/* Custom Hardware Driver - Updated path for organized highz directory structure */
#include "/home/peterson/highz/High-Precision_AD_HAT/c/lib/Driver/ADS1263.h"  // AD HAT driver

/* ============= Types and Constants ============= */

/* Number of ADC channels to read from each AD HAT */
#define ChannelNumber 7

/* GPIO pin definitions for Arduino Nano control (BCM numbering) */
const int GPIO_FREQ_INCREMENT = 4;  // Increment frequency (falling edge trigger)
const int GPIO_FREQ_RESET = 5;      // Reset frequency sweep (falling edge trigger)
const int GPIO_LO_POWER = 6;        // LO board power control (HIGH=ON, LOW=OFF)

/* Frequency Sweep Parameters - Data Acquisition: 650-850 MHz, 2 MHz steps */
const double FREQ_MIN = 650.0;      // Starting frequency (MHz)
const double FREQ_MAX = 850.0;      // Ending frequency (MHz)
const double FREQ_STEP = 2.0;       // Frequency increment per step (MHz)
#define TOTAL_STEPS ((int)(((FREQ_MAX - FREQ_MIN) / FREQ_STEP) + 1))  // Dynamically calculated: (850-650)/2+1 = 101 measurements per sweep

/* Output Directory Configuration */
const char *OUTPUT_DIR = "/home/peterson/Continuous_Sweep";  // Directory for saving FITS files

/* Global Variables for Frequency Control */
double LO_FREQ = FREQ_MIN;     // Local Oscillator starting frequency (initialized to FREQ_MIN)

/* 
 * Structure to hold data from all three AD HATs plus metadata
 * Each instance represents one sample point in time
 */
typedef struct {
    UDOUBLE ADHAT_1[ChannelNumber];  // Data from first AD HAT
    UDOUBLE ADHAT_2[ChannelNumber];  // Data from second AD HAT
    UDOUBLE ADHAT_3[ChannelNumber];  // Data from third AD HAT
    char TIME_RPI2[32];              // Timestamp from local Raspberry Pi
    char STATE[32];                  // Current state of the system
    char FREQUENCY[32];              // Current LO frequency
    char FILENAME[32];               // Output filename for this data
} GetAllValues;

/* 
 * Structure for managing FITS file data
 * Contains an array of samples and the number of rows
 */
typedef struct {
    GetAllValues *data;  // Dynamically allocated array of samples
    int nrows;          // Number of rows in the data array
    double sys_voltage; // System voltage (read once per sweep)
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
int exit_flag = 0;         // Program termination flag
int state2_sweeps_collected = 0;  // Counter for sweeps collected on state 2
const int STATE2_MAX_SWEEPS = 3;   // Number of sweeps to collect on state 2 before transitioning to calib

/* 
 * Structure for passing parameters to writer thread
 * Contains information needed for FITS file creation
 */
typedef struct {
    const char *filename;  // Output filename
    int nrows;            // Number of rows to write
} writer_args_t;

/* ============= Helper Functions ============= */

/*
 * Signal handler for clean program termination
 * Parameters:
 *   signo: Signal number received
 * Returns: void
 */
void Handler(int signo) {
    printf("\r\n END \r\n");
    exit_flag = 1;
}

/*
 * Buffer combination function (placeholder)
 * Returns: char pointer to combined buffer
 */
char* COMBINE_BUFFERS(void)
{
    
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
    
    if (strftime(buf, 64, "%m%d%Y_%H%M%S.fits", t) == 0) {
        fprintf(stderr, "Error: Failed to format time string\n");
        free(buf);  // Clean up allocated memory
        return NULL;
    }

    return buf;
}

// Allocate FITS_DATA with dynamic array
FITS_DATA* MAKE_DATA_ARRAY(int nrows) {
    FITS_DATA *data = malloc(sizeof(FITS_DATA));
    if (!data) {
        printf("Memory allocation for FITS_DATA failed!\n");
        return NULL;
    }
    data->data = malloc(sizeof(GetAllValues) * nrows);
    //data->data = malloc(nrows);
    
    if (!data->data) {
        printf("Memory allocation for data array failed!\n");
        free(data);
        return NULL;
    }
    memset(data->data, 0, sizeof(GetAllValues) * nrows);
    //memset(data->data, 0, nrows);
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
    
    ADS1263_GetAll(ChannelList, data_row->ADHAT_1, ChannelNumber, 12, get_DRDYPIN(12));
    ADS1263_GetAll(ChannelList, data_row->ADHAT_2, ChannelNumber, 22, get_DRDYPIN(22));
    ADS1263_GetAll(ChannelList, data_row->ADHAT_3, ChannelNumber, 23, get_DRDYPIN(23));
    
    return 0;
}

/*
 * Reads RF switch state from ADC pins 7-9 on HAT 12
 * Returns: State value (0-7) representing 3-bit switch position
 */
int READ_SWITCH_STATE(void) {
    int state = 0;
    
    for(int i = 7; i < 10; i++) {
        UDOUBLE value = ADS1263_GetChannalValue(i, 12, get_DRDYPIN(12));
        double vlt;
        
        // Convert ADC value to voltage
        if ((value >> 31) == 1){
            vlt = 5 * 2 - value/2147483648.0 * 5;
        }
        else {
            vlt = value/2147483647.8 * 5;
        }
        
        // Determine bit state (HIGH or LOW)
        int on_or_off = (vlt < 3) ? 0 : 1;
        
        // Calculate state bit contribution
        double exponentiation = exp2(i-7);
        state = state + on_or_off * exponentiation;

        // Print diagnostic information
        printf("Pin %d: ADC value = %llu, Voltage = %.6f V\n", i, value, vlt);
    }
    
    printf("STATE: %d\n", state);
    return state;
}

/*
 * Reads system voltage from ADC channel 7 on HAT 23
 * Returns: Voltage value in volts
 */
double READ_SYSTEM_VOLTAGE(void) {
    UDOUBLE vltReading = ADS1263_GetChannalValue(7, 23, get_DRDYPIN(23));
    double sysVoltage;
    
    if ((vltReading >> 31) == 1){
        sysVoltage = 5 * 2 - vltReading/2147483648.0 * 5;
    }
    else {
        sysVoltage = vltReading/2147483647.8 * 5;
    }
    
    printf("Sys Voltage = %.6f V\n", sysVoltage);
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
int STORE_METADATA(GetAllValues *data_row, const char *timestamp, int state) {
    if (!data_row || !timestamp) return -1;
    
    // Store timestamp
    strncpy(data_row->TIME_RPI2, timestamp, 31);
    data_row->TIME_RPI2[31] = '\0';
    
    // Store state
    snprintf(data_row->STATE, 32, "%d", state);
    data_row->STATE[31] = '\0';
    
    // Store frequency
    snprintf(data_row->FREQUENCY, 32, "%f", LO_FREQ);
    
    // Store filename
    strncpy(data_row->FILENAME, timestamp, 31);
    data_row->FILENAME[31] = '\0';
    
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
    
    if (LO_FREQ < FREQ_MAX - FREQ_STEP){
        // Increment to next frequency
        gpioWrite(GPIO_FREQ_INCREMENT, 0); // Falling edge triggers Arduino
        LO_FREQ = LO_FREQ + FREQ_STEP;
    }
    else {
        // Reset to minimum frequency after reaching maximum
        gpioWrite(GPIO_FREQ_RESET, 0); // Falling edge triggers Arduino reset
        usleep(2000); // Wait 2ms for reset
        LO_FREQ = FREQ_MIN;
    }
    
    usleep(500); // Wait 0.5ms for LO to stabilize
    
    // Return GPIO pins to idle HIGH state
    gpioWrite(GPIO_FREQ_INCREMENT, 1);
    gpioWrite(GPIO_FREQ_RESET, 1);
    
    end_time = clock();
    cpu_time_used = ((double) (end_time - start_time)) / CLOCKS_PER_SEC;
    printf("TIME TAKEN TO SET NEXT LO FREQ: %f\n", cpu_time_used);
    
    return 0;
}

/*
 * Main data collection function - orchestrates the measurement cycle
 * Parameters:
 *   input_struct: FITS_DATA structure containing data buffer
 *   i: Row index in the buffer where data will be stored
 * Returns: 
 *   0 on success
 *   -1 on error
 *   0 with exit_flag=1 if state 2 detected
 */
int GET_DATA(FITS_DATA *input_struct, int i) {
    // Validate inputs
    if (!input_struct) return -1;
    if (i < 0 || i >= input_struct->nrows) return -1;
    if (!input_struct->data) return -1;
    
    // Step 1: Check RF switch state FIRST (before collecting ADC data)
    int state = READ_SWITCH_STATE();
    
    // Step 2: Handle state 2 (collect data, then exit after enough sweeps)
    if (state == 2){
        state2_sweeps_collected++;
        printf("\n========================================\n");
        printf("STATE 2 DETECTED - Collecting sweep %d/%d\n", 
               state2_sweeps_collected, STATE2_MAX_SWEEPS);
        printf("========================================\n");
        
        // Check if we've collected enough sweeps on state 2
        if (state2_sweeps_collected >= STATE2_MAX_SWEEPS) {
            printf("\n========================================\n");
            printf("STATE 2: Collected %d sweeps - Transitioning to filter calibration\n", 
                   state2_sweeps_collected);
            printf("========================================\n");
            exit_flag = 1;  // Signal threads to stop after this sweep completes
            state2_sweeps_collected = 0;  // Reset counter for next time
        }
        // Continue to collect data on this sweep (don't return early)
    }
    
    // Get timestamp for this measurement
    char *timestamp = GET_TIME();
    if (!timestamp) {
        fprintf(stderr, "Error: Failed to get timestamp\n");
        return -1;
    }
    
    printf("##########################################\n");
    printf("MEASURING AT LO FREQ: %lf MHz\n", LO_FREQ);
    printf("##########################################\n");

    // Step 3: Collect ADC data from all three AD HATs at current frequency
    if (COLLECT_ADC_DATA(&input_struct->data[i]) != 0) {
        fprintf(stderr, "Error: Failed to collect ADC data\n");
        free(timestamp);
        return -1;
    }
    
    // Step 4: Store all metadata in buffer
    if (STORE_METADATA(&input_struct->data[i], timestamp, state) != 0) {
        fprintf(stderr, "Error: Failed to store metadata\n");
        free(timestamp);
        return -1;
    }
    
    free(timestamp);
    
    // Step 5: Increment frequency for next measurement
    INCREMENT_LO_FREQUENCY();
    
    return 0;
}

/*
 * Saves collected data to FITS file format
 * Parameters:
 *   input_struct: FITS_DATA structure containing the data buffer
 *   nrows: Number of rows to save
 * Returns: 0 on success, -1 or FITS error code on failure
 */
int SAVE_OUTPUT(FITS_DATA* input_struct, int nrows) {
    if (!input_struct) return -1;

    fitsfile *fptr;
    int status = 0;
    int num = ChannelNumber;
    
    // FITS column definitions (removed SYSTEM VOLTAGE column)
    char *ttype[] = { "ADHAT_1", "ADHAT_2", "ADHAT_3", "TIME_RPI2", "SWITCH STATE", "FREQUENCY", "FILENAME"};
    char *tform[] = { "7K", "7K", "7K", "25A", "15A", "15A", "25A"};
    char *tunit[] = { "", "", "", "", "", "", ""};
    
    // Get filename from first data row
    char full_filename[256];
    char filename[32];
    strncpy(filename, input_struct->data[0].FILENAME, 31);
    filename[31] = '\0';
    
    // Create FITS file (! prefix forces overwrite if exists)
    snprintf(full_filename, sizeof(full_filename), "!%s/%s", OUTPUT_DIR, filename);
    if (fits_create_file(&fptr, full_filename, &status)) {
        fits_report_error(stderr, status);
        return status;
    }
    
    // Create binary table extension
    const char *extname = "FILTER BANK DATA";
    if (fits_create_tbl(fptr, BINARY_TBL, 0, 7, ttype, tform, tunit, extname, &status)) {
        fits_report_error(stderr, status);
        fits_close_file(fptr, &status);
        return status;
    }
    
    // Write system voltage to FITS header (read once per sweep)
    if (fits_update_key(fptr, TDOUBLE, "SYSVOLT", &input_struct->sys_voltage, 
                        "System voltage (V) at sweep start", &status)) {
        fits_report_error(stderr, status);
        fits_close_file(fptr, &status);
        return status;
    }
    
    printf("FITS file successfully created!\n");
    
    // Allocate memory for column data
    UDOUBLE *col1_data = malloc(sizeof(UDOUBLE) * nrows * num);
    UDOUBLE *col2_data = malloc(sizeof(UDOUBLE) * nrows * num);
    UDOUBLE *col3_data = malloc(sizeof(UDOUBLE) * nrows * num);
    char *col4_data = malloc(nrows * 25 * sizeof(char));  // TIME_RPI2 - needs 21+ chars for timestamp
    char *col5_data = malloc(nrows * 15 * sizeof(char));  // STATE - 1 digit
    char *col6_data = malloc(nrows * 15 * sizeof(char));  // FREQUENCY - ~10 chars
    char *col7_data = malloc(nrows * 25 * sizeof(char));  // FILENAME - needs 21+ chars for timestamp.fits
    
    // Check all allocations
    if (!col1_data || !col2_data || !col3_data || !col4_data || 
        !col5_data || !col6_data || !col7_data) {
        fprintf(stderr, "Memory allocation failed for column buffers\n");
        // Free any successful allocations
        free(col1_data);
        free(col2_data);
        free(col3_data);
        free(col4_data);
        free(col5_data);
        free(col6_data);
        free(col7_data);
        fits_close_file(fptr, &status);
        return -1;
    }

    // Copy ADC data from structure to column arrays
    for (int i = 0; i < nrows; i++) {
        for (int j = 0; j < num; j++) {
            col1_data[i * num + j] = input_struct->data[i].ADHAT_1[j];
            col2_data[i * num + j] = input_struct->data[i].ADHAT_2[j];
            col3_data[i * num + j] = input_struct->data[i].ADHAT_3[j];
        }
    }
    
    // Copy string data (timestamp, state, frequency, filename)
    for (int i = 0; i < nrows; i++) {
        // Fill with spaces and copy each string field
        memset(&col4_data[i * 25], ' ', 25);
        strncpy(&col4_data[i * 25], input_struct->data[i].TIME_RPI2, 24);
        col4_data[i * 25 + 24] = '\0';
        
        memset(&col5_data[i * 15], ' ', 15);
        strncpy(&col5_data[i * 15], input_struct->data[i].STATE, 14);
        col5_data[i * 15 + 14] = '\0';
        
        memset(&col6_data[i * 15], ' ', 15);
        strncpy(&col6_data[i * 15], input_struct->data[i].FREQUENCY, 14);
        col6_data[i * 15 + 14] = '\0';
        
        memset(&col7_data[i * 25], ' ', 25);
        strncpy(&col7_data[i * 25], input_struct->data[i].FILENAME, 24);
        col7_data[i * 25 + 24] = '\0';
    }
    
    // Create pointer arrays for string columns
    char **col4_ptrs = malloc(nrows * sizeof(char *));
    char **col5_ptrs = malloc(nrows * sizeof(char *));
    char **col6_ptrs = malloc(nrows * sizeof(char *));
    char **col7_ptrs = malloc(nrows * sizeof(char *));
    
    // Check pointer array allocations
    if (!col4_ptrs || !col5_ptrs || !col6_ptrs || !col7_ptrs) {
        fprintf(stderr, "Memory allocation failed for pointer arrays\n");
        goto cleanup;
    }
    
    // Set up pointer arrays
    for (int i = 0; i < nrows; i++) {
        col4_ptrs[i] = &col4_data[i * 25];
        col5_ptrs[i] = &col5_data[i * 15];
        col6_ptrs[i] = &col6_data[i * 15];
        col7_ptrs[i] = &col7_data[i * 25];
    }

    // Write all columns to FITS file (removed col8 for voltage)
    if (fits_write_col(fptr, TUINT, 1, 1, 1, nrows * num, col1_data, &status) ||
        fits_write_col(fptr, TUINT, 2, 1, 1, nrows * num, col2_data, &status) ||
        fits_write_col(fptr, TUINT, 3, 1, 1, nrows * num, col3_data, &status) ||
        fits_write_col(fptr, TSTRING, 4, 1, 1, nrows, col4_ptrs, &status) ||
        fits_write_col(fptr, TSTRING, 5, 1, 1, nrows, col5_ptrs, &status) ||
        fits_write_col(fptr, TSTRING, 6, 1, 1, nrows, col6_ptrs, &status) ||
        fits_write_col(fptr, TSTRING, 7, 1, 1, nrows, col7_ptrs, &status)) {
        fits_report_error(stderr, status);
        goto cleanup;
    }

    // Flush and close FITS file
    if (fits_flush_file(fptr, &status)) {
        fits_report_error(stderr, status);
        goto cleanup;
    }

    if (fits_close_file(fptr, &status)) {
        fits_report_error(stderr, status);
        // Don't goto cleanup since file is already closed
        free(col1_data);
        free(col2_data);
        free(col3_data);
        free(col4_data);
        free(col5_data);
        free(col6_data);
        free(col7_data);
        free(col4_ptrs);
        free(col5_ptrs);
        free(col6_ptrs);
        free(col7_ptrs);
        return status;
    }

    printf("Buffer saved successfully.\n");

    // Clean up all allocated memory
    free(col1_data);
    free(col2_data);
    free(col3_data);
    free(col4_data);
    free(col5_data);
    free(col6_data);
    free(col7_data);
    free(col4_ptrs);
    free(col5_ptrs);
    free(col6_ptrs);
    free(col7_ptrs);

    return 0;

cleanup:
    // Error path - clean up and close file
    free(col1_data);
    free(col2_data);
    free(col3_data);
    free(col4_data);
    free(col5_data);
    free(col6_data);
    free(col7_data);
    free(col4_ptrs);
    free(col5_ptrs);
    free(col6_ptrs);
    free(col7_ptrs);
    fits_close_file(fptr, &status);
    return status;
}

int INITIALIZE_ADS(void)
{
    printf("Initializing High Precision AD HAT...\n");
    SYSFS_GPIO_Init();
    
    printf("GPIO Initialized.\n");
    printf("Initializing SPI Interface...\n");
    
    DEV_Module_Init(18, 12, get_DRDYPIN(12));
    DEV_Module_Init(18, 22, get_DRDYPIN(22));
    DEV_Module_Init(18, 23, get_DRDYPIN(23));
    ADS1263_reset(18);
    
    printf("SPI Interface initialized. Initializing AD HATs...\n");
    
    if(ADS1263_init_ADC1(ADS1263_38400SPS, 12) == 1) {
        printf("\r\n END \r\n");
        DEV_Module_Exit(12, get_DRDYPIN(12));
        exit(0);
    }
    
    if(ADS1263_init_ADC1(ADS1263_38400SPS, 22) == 1) {
        printf("\r\n END \r\n");
        DEV_Module_Exit(22, get_DRDYPIN(22));
        exit(0);
    }
    
    if(ADS1263_init_ADC1(ADS1263_38400SPS, 23) == 1) {
        printf("\r\n END \r\n");
        DEV_Module_Exit(23, get_DRDYPIN(23));
        exit(0);
    }
    
    ADS1263_SetMode(0);
    
    printf("All AD HATS successfully initialized.\n");

    return 0;
}

int CLOSE_GPIO(void)
{
    printf("Shutting down all GPIOs...\n");
    DEV_Module_Exit(18, 12);
    DEV_Module_Exit(18, 22);
    DEV_Module_Exit(18, 23);
    SYSFS_GPIO_Release();
    printf("Shutdown complete.\n");
    return 0;
}

// Clean shutdown of GPIO and LO board
void CLEANUP_AND_SHUTDOWN(void)
{
    printf("\n========================================\n");
    printf("Starting cleanup procedure...\n");
    printf("========================================\n");
    
    // Reset GPIO pins to idle state
    gpioWrite(GPIO_FREQ_INCREMENT, 1);
    gpioWrite(GPIO_FREQ_RESET, 1);
    gpioDelay(5000);
    printf("✓ GPIO pins reset to idle state\n");

    // Power down LO board
    gpioWrite(GPIO_LO_POWER, 0);
    gpioDelay(5000);
    printf("✓ LO board powered down\n");
    
    // Terminate pigpio
    gpioTerminate();
    printf("✓ pigpio terminated\n");
    
    // Close AD HAT GPIOs
    CLOSE_GPIO();
    printf("✓ AD HAT GPIOs closed\n");
    
    printf("========================================\n");
    printf("Cleanup complete\n");
    printf("========================================\n");
}

// Writer thread function now accepts struct with filename and nrows
void* writer_thread_func(void *arg) {
    writer_args_t *args = (writer_args_t*)arg;
    int nrows = args->nrows;

    while (1) {
        printf("NOT SAVING YET...\n");
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
            
            printf("ABOUT TO SAVE DATA...\n");
            clock_t start_time, end_time;
            double cpu_time_used;
        
            start_time = clock();
            end_time = clock();
            
            //usleep(1000000);
        
            int status = SAVE_OUTPUT(buf, nrows); //removed filename argument
            printf("STATUS: %d\n", status);
            
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
    if (argc < 4) {
        printf("Usage: %s <nrows> %s <start_freq> %s <end_freq>\n", argv[0]);
        return 1;
    }

    int nrows = atoi(argv[1]);
    
    printf("nrows: ######################### %d\n", nrows);
    
    if (nrows <= 0) {
        printf("Invalid nrows value.\n");
        return 1;
    }
    
    int start_freq = atoi(argv[2]);
    if (start_freq <= 0) {
        printf("Invalid start_freq value.\n");
        return 1;
    }
    
    int end_freq = atoi(argv[3]);
    if (end_freq <= 0) {
        printf("Invalid end_freq value.\n");
        return 1;
    }

    signal(SIGINT, Handler);

    bufferA = MAKE_DATA_ARRAY(nrows);
    bufferB = MAKE_DATA_ARRAY(nrows);

    if (!bufferA || !bufferB) {
        printf("Failed to allocate buffers\n");
        return 1;
    }
    
    INITIALIZE_ADS();
    
    if (gpioInitialise() < 0){
        printf("initialization of pigpio failed\n");
        return 1;
    }
    
    // BCM numbering - Arduino Nano GPIO connections
    gpioSetMode(GPIO_FREQ_INCREMENT, PI_OUTPUT); // Increment frequency (falling edge)
    gpioSetMode(GPIO_FREQ_RESET, PI_OUTPUT);     // Reset frequency sweep (falling edge)
    gpioSetMode(GPIO_LO_POWER, PI_OUTPUT);       // LO board power control

    // Initialize: FREQ_INCREMENT and FREQ_RESET idle HIGH, LO_POWER LOW (board off)
    gpioWrite(GPIO_FREQ_INCREMENT, 1);
    gpioWrite(GPIO_FREQ_RESET, 1);
    gpioDelay(5000); // 5 ms settle
    
    // Turn LO board ON and reset frequency counter
    gpioWrite(GPIO_LO_POWER, 1);  // Power on LO board
    gpioDelay(10000); // 10 ms for LO board to stabilize
    
    // Reset frequency counter to starting position
    gpioWrite(GPIO_FREQ_RESET, 0);  // Falling edge to reset
    gpioDelay(5000); // 5 ms LOW pulse
    gpioWrite(GPIO_FREQ_RESET, 1);  // Return to idle HIGH
    gpioDelay(5000); // 5 ms settle
    
    sleep(1); // Additional 1 second delay to ensure LO stability

    printf("Starting main data acquisition loop...\n");

    writer_args_t writer_args = {
        .nrows = nrows
    };

    pthread_t writer_thread;
    pthread_create(&writer_thread, NULL, writer_thread_func, &writer_args);

    int current_buffer = 1;
    int row_index = 0;
    
    while (!exit_flag) {
        clock_t start_time, end_time;
        double cpu_time_used;
        
        start_time = clock();
        //printf("LOOP BEGAN: %ld\n", (long)start_time);
        FITS_DATA *active_buffer = (current_buffer == 1) ? bufferA : bufferB;
        
        // Read system voltage once at the start of each sweep (row_index == 0)
        if (row_index == 0) {
            active_buffer->sys_voltage = READ_SYSTEM_VOLTAGE();
        }
        
        int result = GET_DATA(active_buffer, row_index);
        
        // If GET_DATA returned early due to state 2, break the loop immediately
        if (result != 0 || exit_flag) {
            printf("State 2 detected or error occurred. Exiting main loop...\n");
            break;
        }
        
        row_index++;

        if (row_index >= nrows) {
            pthread_mutex_lock(&buffer_mutex);
            buffer_to_write = current_buffer;
            pthread_cond_signal(&buffer_ready_cond);
            pthread_mutex_unlock(&buffer_mutex);

            current_buffer = (current_buffer == 1) ? 2 : 1;
            row_index = 0;
        }
        end_time = clock();
        //printf("LOOP ENDED: %ld\n", (long)end_time);
        
        cpu_time_used = ((double) (end_time-start_time)) / CLOCKS_PER_SEC;
        printf("LOOP EXECUTION TIME: %f seconds\n", cpu_time_used);
    }

    // Signal writer thread to stop and wait for it to finish
    printf("\nMain loop exited. Signaling writer thread...\n");
    pthread_mutex_lock(&buffer_mutex);
    exit_flag = 1;
    pthread_cond_signal(&buffer_ready_cond);
    pthread_mutex_unlock(&buffer_mutex);

    printf("Waiting for writer thread to complete...\n");
    pthread_join(writer_thread, NULL);
    printf("✓ Writer thread completed\n");

    // Free allocated buffers
    printf("Freeing data buffers...\n");
    FREE_DATA_ARRAY(&bufferA);
    FREE_DATA_ARRAY(&bufferB);
    printf("✓ Buffers freed\n");
    
    //free(FREQ_VALUES);

    // Clean shutdown of all hardware
    CLEANUP_AND_SHUTDOWN();

    printf("\n========================================\n");
    printf("Program ended cleanly.\n");
    printf("========================================\n");

    return 0;
}
