#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <signal.h>
#include <unistd.h>
#include <fitsio.h>
#include <time.h>
#include <pigpio.h>

// AD HAT driver (now in organized highz directory structure)
#include "/home/peterson/highz/High-Precision_AD_HAT/c/lib/Driver/ADS1263.h"

// Types and constants
#define ChannelNumber 7

// GPIO pin definitions for Arduino Nano + Local Oscillator control (BCM numbering)
const int GPIO_FREQ_INCREMENT = 4;  // Increment frequency (falling edge trigger)
const int GPIO_FREQ_RESET = 5;      // Reset frequency sweep (falling edge trigger)
const int GPIO_LO_POWER = 6;        // LO board power control (HIGH=ON, LOW=OFF)

// Filter sweep Band B: 900-960 MHz, 0.2 MHz step (matches SweepFilter.ino)
const double FREQ_MIN = 900.0;
const double FREQ_MAX = 960.0;
const double FREQ_STEP = 0.2;
#define TOTAL_STEPS ((int)(((FREQ_MAX - FREQ_MIN) / FREQ_STEP) + 1))  // Dynamically calculated: (960-900)/0.2+1 = 301 measurements per sweep
double LO_FREQ = FREQ_MIN;          // Start frequency initialized to FREQ_MIN

typedef struct {
    UDOUBLE ADHAT_1[ChannelNumber];
    UDOUBLE ADHAT_2[ChannelNumber];
    UDOUBLE ADHAT_3[ChannelNumber];
    char TIME_RPI2[32];
    char STATE[32];
    char FREQUENCY[32];
    char FILENAME[32];
} GetAllValues;

typedef struct {
    GetAllValues *data;  // dynamically allocated array of GetAllValues
    int nrows;
} FITS_DATA;

// Global flag for signal handling
volatile int exit_flag = 0;

void Handler(int signo) {
    printf("\r\n\nInterrupt signal received. Cleaning up...\r\n");
    exit_flag = 1;
}

char *GET_TIME(void)
{
    char *buf = malloc(64);
    if (!buf) return NULL;
    
    time_t now = time(NULL);
    struct tm *t = localtime(&now);
    strftime(buf, 64, "%m%d%Y_%H%M%S.fits", t);
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
    
    if (!data->data) {
        printf("Memory allocation for data array failed!\n");
        free(data);
        return NULL;
    }
    memset(data->data, 0, sizeof(GetAllValues) * nrows);
    data->nrows = nrows;
    return data;
}

void FREE_DATA_ARRAY(FITS_DATA **ptr) {
    if (ptr && *ptr) {
        if ((*ptr)->data) free((*ptr)->data);
        free(*ptr);
        *ptr = NULL;
    }
}

int GET_DATA(FITS_DATA *input_struct, int i, int power_dbm) {
    clock_t start_time1, end_time1, start_time2, end_time2;
    double cpu_time_used1, cpu_time_used2;
    
    if (!input_struct || i >= input_struct->nrows) return -1;

    UBYTE ChannelList[ChannelNumber] = {0,1,2,3,4,5,6};
    
    char *MEASURED_TIME = GET_TIME();
    start_time1 = clock();
    
    // Advance frequency if not at max
    if (LO_FREQ < FREQ_MAX){
        // Falling edge on FREQ_INCREMENT: advance to next frequency
        gpioWrite(GPIO_FREQ_INCREMENT, 0);
        gpioDelay(3000);  // 3ms delay
        
        // Rising edge: complete the pulse
        gpioWrite(GPIO_FREQ_INCREMENT, 1);
        LO_FREQ = LO_FREQ + FREQ_STEP;
        gpioDelay(3000);  // 3ms delay
    }
    
    printf("========================================\n");
    printf("LO FREQ: %.1f MHz @ %+d dBm\n", LO_FREQ, power_dbm);   
    printf("========================================\n");
    
    usleep(50000); // 500ms settling time
    end_time1 = clock();
    
    cpu_time_used1 = ((double) (end_time1-start_time1)) / CLOCKS_PER_SEC;
    
    ADS1263_GetAll(ChannelList, input_struct->data[i].ADHAT_1, ChannelNumber, 12, get_DRDYPIN(12));
    ADS1263_GetAll(ChannelList, input_struct->data[i].ADHAT_2, ChannelNumber, 22, get_DRDYPIN(22));
    ADS1263_GetAll(ChannelList, input_struct->data[i].ADHAT_3, ChannelNumber, 23, get_DRDYPIN(23));
    
    start_time2 = clock();
    
    strncpy(input_struct->data[i].TIME_RPI2, MEASURED_TIME, 32);
    input_struct->data[i].TIME_RPI2[31] = '\0';
    
    // Store power level
    snprintf(input_struct->data[i].STATE, 32, "%+d", power_dbm);
    input_struct->data[i].STATE[31] = '\0';
    
    snprintf(input_struct->data[i].FREQUENCY, 32, "%.1f", LO_FREQ);
    
    strncpy(input_struct->data[i].FILENAME, MEASURED_TIME, 32);
    input_struct->data[i].FILENAME[31] = '\0';
    
    free(MEASURED_TIME);
    end_time2 = clock();
    
    cpu_time_used2 = ((double) (end_time2-start_time2)) / CLOCKS_PER_SEC;
    
    return 0;
}

int SAVE_OUTPUT(FITS_DATA* input_struct, int nrows, int power_dbm) {
    if (!input_struct) return -1;

    fitsfile *fptr;
    int status = 0;
    int num = ChannelNumber;
    
    char *ttype[] = { "ADHAT_1", "ADHAT_2", "ADHAT_3", "TIME_RPI2", "POWER_DBM", "FREQUENCY", "FILENAME" };
    char *tform[] = { "7K", "7K", "7K", "15A", "15A", "15A", "15A" };
    char *tunit[] = { "", "", "", "", "dBm", "MHz" , "" };
    
    char full_filename[256];
    char filename[64];
    
    // Get timestamp from first measurement
    char base_filename[32];
    strncpy(base_filename, input_struct->data[0].FILENAME, 31);
    base_filename[31] = '\0';
    
    // Remove .fits extension if present
    char *dot = strrchr(base_filename, '.');
    if (dot) *dot = '\0';
    
    // Create filename with power level
    snprintf(filename, sizeof(filename), "%s_%+ddBm.fits", base_filename, power_dbm);
    snprintf(full_filename, sizeof(full_filename), "!/home/peterson/FilterCalibrations/%s", filename);
    if (fits_create_file(&fptr, full_filename, &status))
    {
        fits_report_error(stderr, status);
        return status;
    }
    
    const char *extname = "FILTER BANK DATA";
    if (fits_create_tbl(fptr, BINARY_TBL, 0, 7, ttype, tform, tunit, extname, &status))
    {
        fits_report_error(stderr, status);
        return status;
    }
    
    printf("FITS file successfully created!\n");    
    
    UDOUBLE *col1_data = malloc(sizeof(UDOUBLE) * nrows * num);
    UDOUBLE *col2_data = malloc(sizeof(UDOUBLE) * nrows * num);
    UDOUBLE *col3_data = malloc(sizeof(UDOUBLE) * nrows * num);
    char *col4_data = malloc(nrows * 15 * sizeof(char));
    char *col5_data = malloc(nrows * 15 * sizeof(char));
    char *col6_data = malloc(nrows * 15 * sizeof(char));
    char *col7_data = malloc(nrows * 15 * sizeof(char));
    

    if (!col1_data || !col2_data || !col3_data || !col4_data || !col5_data || !col6_data || !col6_data || !col7_data) {
        printf("Memory allocation failed for column buffers\n");
        if (col1_data) free(col1_data);
        if (col2_data) free(col2_data);
        if (col3_data) free(col3_data);
        if (col4_data) free(col4_data);
        if (col5_data) free(col5_data);
        if (col6_data) free(col6_data);
        if (col7_data) free(col6_data);
        fits_close_file(fptr, &status);
        return -1;
    }

    for (int i = 0; i < nrows; i++) {
        for (int j = 0; j < num; j++) {
            col1_data[i * num + j] = input_struct->data[i].ADHAT_1[j];
            col2_data[i * num + j] = input_struct->data[i].ADHAT_2[j];
            col3_data[i * num + j] = input_struct->data[i].ADHAT_3[j];
        }
    }
    
    for (int i = 0; i < nrows; i++) {
        memset(&col4_data[i * 15], ' ', 15);
        if (input_struct->data[i].TIME_RPI2 == NULL){
            fprintf(stderr, "null pointer to rpi2 time at index %d\n", i);
        }
        printf("buffer: %p\n", (void *)&input_struct->data[i].TIME_RPI2);
        strncpy(&col4_data[i * 15], input_struct->data[i].TIME_RPI2, 15);
        col4_data[i * 15 + 14] = '\0';
        memset(&col5_data[i * 15], ' ', 15);
        strncpy(&col5_data[i * 15], input_struct->data[i].STATE, 15);
        col5_data[i * 15 + 14] = '\0';
        memset(&col6_data[i * 15], ' ', 15);
        strncpy(&col6_data[i * 15], input_struct->data[i].FREQUENCY, 15);
        col6_data[i * 15 + 14] = '\0';
        memset(&col7_data[i * 15], ' ', 15);
        strncpy(&col7_data[i * 15], input_struct->data[i].FILENAME, 15);
        col7_data[i * 15 + 14] = '\0';
    }
    
    char **col4_ptrs = malloc(nrows * num * sizeof(char *));
    char **col5_ptrs = malloc(nrows * num * sizeof(char *));
    char **col6_ptrs = malloc(nrows * num * sizeof(char *));
    char **col7_ptrs = malloc(nrows * num * sizeof(char *));
    for (int i = 0; i < nrows * num; i++) {
        col4_ptrs[i] = &col4_data[i * 15];
        col5_ptrs[i] = &col5_data[i * 15];
        col6_ptrs[i] = &col6_data[i * 15];
        col7_ptrs[i] = &col7_data[i * 15];
    }

    if (fits_write_col(fptr, TUINT, 1, 1, 1, nrows * num, col1_data, &status)) {
        fits_report_error(stderr, status);
        goto cleanup;
    }
    if (fits_write_col(fptr, TUINT, 2, 1, 1, nrows * num, col2_data, &status)) {
        fits_report_error(stderr, status);
        goto cleanup;
    }
    if (fits_write_col(fptr, TUINT, 3, 1, 1, nrows * num, col3_data, &status)) {
        fits_report_error(stderr, status);
        goto cleanup;
    }
    
    if (fits_write_col(fptr, TSTRING, 4, 1, 1, nrows, col4_ptrs, &status)) {
        fits_report_error(stderr, status);
        goto cleanup;
    }
    if (fits_write_col(fptr, TSTRING, 5, 1, 1, nrows, col5_ptrs, &status)) {
        fits_report_error(stderr, status);
        goto cleanup;
    }
    if (fits_write_col(fptr, TSTRING, 6, 1, 1, nrows, col6_ptrs, &status)) {
        fits_report_error(stderr, status);
        goto cleanup;
    }
    if (fits_write_col(fptr, TSTRING, 7, 1, 1, nrows, col7_ptrs, &status)) {
        fits_report_error(stderr, status);
        goto cleanup;
    }

    if (fits_flush_file(fptr, &status)) {
        fits_report_error(stderr, status);
        goto cleanup;
    }

    if (fits_close_file(fptr, &status)) {
        fits_report_error(stderr, status);
    }
    
    free(col1_data);
    free(col2_data);
    free(col3_data);
    free(col4_ptrs);
    free(col5_ptrs);
    free(col6_ptrs);
    free(col7_ptrs);

    return 0;

cleanup:
    free(col1_data);
    free(col2_data);
    free(col3_data);
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

int main(int argc, char **argv) {
    printf("\n=== Filter Calibration Sweep ===\n");
    printf("Frequency range: %.1f - %.1f MHz (step: %.1f MHz)\n", 
           FREQ_MIN, FREQ_MAX, FREQ_STEP);
    printf("Measurements per sweep: %d\n", TOTAL_STEPS);
    printf("Dual power sweep: +5 dBm → -4 dBm\n");
    printf("Output: 2 FITS files (one per power level)\n\n");

    signal(SIGINT, Handler);
    
    int nrows = TOTAL_STEPS;  // One measurement per frequency step

    // Allocate single buffer for one complete sweep
    FITS_DATA *sweep_data = MAKE_DATA_ARRAY(nrows);
    if (!sweep_data) {
        printf("Failed to allocate sweep buffer\n");
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
    gpioWrite(GPIO_LO_POWER, 0);  // LO board initially off
    gpioDelay(5000); // 5 ms settle
    
    printf("Initializing filter sweep (Band B: 900-960 MHz)...\n");
    printf("Dual power sweep: +5 dBm, then -4 dBm\n");
    
    // Turn LO board ON to enable sweep
    gpioWrite(GPIO_LO_POWER, 1);
    gpioDelay(10000); // 10 ms for LO board to stabilize
    printf("LO board powered on\n\n");

    // Perform two sweeps at different power levels
    int power_levels[] = {+5, -4};
    
    for (int sweep = 0; sweep < 2; sweep++) {
        int power_dbm = power_levels[sweep];
        printf("\n========================================\n");
        printf("Starting Sweep %d at %+d dBm\n", sweep + 1, power_dbm);
        printf("========================================\n\n");
        
        // Reset frequency to start
        LO_FREQ = FREQ_MIN;
        
        // Collect all measurements for this sweep
        for (int i = 0; i < nrows; i++) {
            GET_DATA(sweep_data, i, power_dbm);
            
            if (exit_flag) {
                printf("\nSweep interrupted by user\n");
                goto cleanup;
            }
        }
        
        // Save sweep data to FITS file
        printf("\nSaving sweep %d data...\n", sweep + 1);
        int save_status = SAVE_OUTPUT(sweep_data, nrows, power_dbm);
        if (save_status != 0) {
            printf("Error saving sweep %d: status %d\n", sweep + 1, save_status);
        } else {
            printf("✓ Sweep %d saved successfully\n", sweep + 1);
        }
        
        // If not the last sweep, reset for next power level
        if (sweep < 1) {
            printf("\nPreparing for sweep %d...\n", sweep + 2);
            
            // Send RESET signal to reset frequency sweep on Arduino
            gpioWrite(GPIO_FREQ_RESET, 0);
            gpioDelay(10000); // 10ms LOW pulse
            gpioWrite(GPIO_FREQ_RESET, 1);
            gpioDelay(10000); // 10ms settle
            
            printf("Frequency reset for %+d dBm sweep\n", power_levels[sweep + 1]);
            sleep(1); // Additional settling time
        }
    }
    
    printf("\n========================================\n");
    printf("Both sweeps completed successfully!\n");
    printf("========================================\n");

cleanup:
    FREE_DATA_ARRAY(&sweep_data);
    
    printf("\nShutting down...\n");
    
    // Reset Arduino to initial state (frequency counter reset)
    gpioWrite(GPIO_FREQ_RESET, 0);
    gpioDelay(10000);  // 10ms LOW pulse
    gpioWrite(GPIO_FREQ_RESET, 1);
    gpioDelay(5000);   // 5ms settle
    printf("Arduino reset\n");
    
    // Power down LO board
    gpioWrite(GPIO_LO_POWER, 0);
    gpioDelay(5000);
    printf("LO board powered down\n");
    
    gpioTerminate();
    CLOSE_GPIO();

    printf("\n========================================\n");
    printf("Filter sweep program terminated\n");
    printf("========================================\n");

    return 0;
}
