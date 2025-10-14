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

/* Custom Hardware Driver */
#include "/home/peterson/High-Pricision_AD_HAT_1/c/lib/Driver/ADS1263.h"  // AD HAT driver

/* ============= Types and Constants ============= */

/* Number of ADC channels to read from each AD HAT */
#define ChannelNumber 7

/* Global Variables for Frequency Control */
double LO_FREQ = 648.0;     // Local Oscillator starting frequency
int sweepsOfFive = 0;       // Counter for completed frequency sweeps

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

/*
 * Generates array of frequency values for sweep
 * Parameters:
 *   start_value: Starting frequency
 *   end_value: Ending frequency
 *   nrows: Number of frequency steps
 * Returns:
 *   double*: Array of frequency values
 *   NULL: If memory allocation fails
 * Note: Caller must free the returned array
 */
double *GET_FREQUENCIES(int start_value, int end_value, int nrows)
{
    double *return_buffer = (double *)malloc(nrows * sizeof(double));
    if (!return_buffer) return NULL;
    
    // double end = (double)end_value;
    // double start = (double)start_value;

    double step = (end_value - start_value) / nrows;
    
    for (int i = 0; i < nrows; i++) {
        return_buffer[i] = start_value + i * step;
    }
    
    return return_buffer;
}

/*
void PIPE_WRITE(double freq) {
    FILE *pipe = fopen("/tmp/freqpipe", "w");
    if (pipe == NULL) {
        perror("Failed to open freqpipe");
        return;
    }
    
    printf("FREQUENCY: %f\n", freq);
    printf("What's being written: %.10f\n", freq);
    
    fprintf(pipe, "%.10f\n", freq);
    fflush(pipe);
    fclose(pipe);
}

void OPEN_FREQ_SERVER(void) {
    int ret = system("python /home/peterson/LIB_HOLDER/frequency_server_oneshot.py");
    if (ret != 0) {
        fprintf(stderr, "LO programming failed. Exit code: %d\n", ret);
    }
}

void SET_LOCAL_OSCILLATOR(double freq) {
    PIPE_WRITE(freq);
    //OPEN_FREQ_SERVER();
    // Optional: sleep briefly to ensure SPI bus settles
    usleep(100000); // 100ms
}

int RUN_COMMAND(void)
{
    printf("TRYING TO RUN COMMAND\n");
	char command[100];
	snprintf(command, sizeof(command), "python /home/peterson/LIB_HOLDER/frequency_server.py > /tmp/freqserver.log 2>&1 &");
	int didItRun = system(command);
	printf("RAN COMMAND\n");
	if (didItRun == 0)
	{
		printf("PyPipe successfully executed, waiting for frequencies!\n");
	}
	else
	{
		printf("PyPipe failed...\n");
	}
	
	return 0;
}
* */

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
    return data;
}

void FREE_DATA_ARRAY(FITS_DATA **ptr) {
    if (ptr && *ptr) {
        if ((*ptr)->data) free((*ptr)->data);
        free(*ptr);
        *ptr = NULL;
    }
}

int GET_DATA(FITS_DATA *input_struct, int i) {
    clock_t start_time1, end_time1, start_time2, end_time2;
    double cpu_time_used1, cpu_time_used2;
    
    if (!input_struct) return -1; // Check pointer validity
    if (i < 0 || i >= input_struct->nrows) return -1; // Check index bounds
    if (!input_struct->data) return -1;  // Check if data array exists

    UBYTE ChannelList[ChannelNumber] = {0,1,2,3,4,5,6};
    
    char *MEASURED_TIME = GET_TIME(); // Get current time (formatted as "MMDDYYYY_HHMMSS.fits")
    //char *MEASURED_STATE = GET_STATE(); //this will be in ADS1263.c, defined in ADS1263.h
    start_time1 = clock(); // Records the current processor time (in clock ticks)
    //SET_LOCAL_OSCILLATOR(freq);
    
    // Sweeps the Local Oscillator frequency from 648 MHz to 850 MHz in 2 MHz steps
    if (LO_FREQ < 850.0 - 2.0){
        gpioWrite(4, 0); // Sets GPIO pin 4 low, falling edge triggers arduino to increment frequency?
        //usleep(500000);
        LO_FREQ = LO_FREQ + 2.0;
    }
    // Resets the LO sweep back to 648 MHz after reaching 850 MHz
    else {
        gpioWrite(5, 0); // Sets GPIO pin 5 low, falling edge triggers arduino to reset frequency?
        usleep(2000); // Waits 2 milliseconds
        gpioWrite(4, 0); // Sets GPIO pin 4 low again to start new sweep?
        LO_FREQ = 650.0;
    }
    printf("###################################################################################################################################################################");
    printf("LO FREQ: %lf\n", LO_FREQ);
    printf("###################################################################################################################################################################");
    
    usleep(500); // Waits 0.5 milliseconds to allow LO to stabilize
    end_time1 = clock();
    
    
    gpioWrite(4, 1);
    gpioWrite(5, 1);
    
    
    cpu_time_used1 = ((double) (end_time1-start_time1)) / CLOCKS_PER_SEC;
    
    printf("TIME TAKEN TO SET LO: %f\n", cpu_time_used1);
    
    ADS1263_GetAll(ChannelList, input_struct->data[i].ADHAT_1, ChannelNumber, 12, get_DRDYPIN(12));
    ADS1263_GetAll(ChannelList, input_struct->data[i].ADHAT_2, ChannelNumber, 22, get_DRDYPIN(22));
    ADS1263_GetAll(ChannelList, input_struct->data[i].ADHAT_3, ChannelNumber, 23, get_DRDYPIN(23));
    
    int state = 0;
    
    
    for(int i = 7; i < 10; i++) {
        UDOUBLE value = ADS1263_GetChannalValue(i, 12, get_DRDYPIN(12));
        double voltage;
        if ((value >> 31) == 1){
            voltage = 5 * 2 - value/2147483648.0 * 5;
        }
        else {
            voltage = value/2147483647.8 * 5;
        }
        
        int on_or_off;
        
        if (value < 3){
            on_or_off = 0;
        }
        else {
            on_or_off = 1;
        }
        double exponentiation = exp2(i-7);
        state = state + on_or_off * exponentiation;

        // Print out the voltage for this pin
        printf("Pin %d: ADC value = %llu, Voltage = %.6f V\n", i, value, voltage);
    }
    
    //ISSUE WITH THE CODE BELOW: WHY DOES IT PASS HERE OCCASIONALLY, BUT SOMETIMES NO?
    
    if (state == 0 && LO_FREQ == 848.0){
        sweepsOfFive = sweepsOfFive + 1;
        if (sweepsOfFive == 4){
            exit(0);
        }
    }
    
    
    
    char STATE[32];
    snprintf(STATE, sizeof(STATE), "%d", state);
    
    printf("STATE: %d\n", state);
    
    //ADD STATE SAVING HERE!!!!!!!!!!!!!!!!!!!
    
    start_time2 = clock();
    //char *BUFFER = COMBINE_TELEMETRY(MEASURED_TIME, 'MEASURED_STATE', 'MEASURED_FREQUENCY');
    
    strncpy(input_struct->data[i].TIME_RPI2, MEASURED_TIME, 32); //Time of local pi
    input_struct->data[i].TIME_RPI2[31] = '\0'; //Time of local pi
    
    strncpy(input_struct->data[i].STATE, STATE, 32); //State of rf box
    input_struct->data[i].STATE[31] = '\0'; //State sent from rpi1
    
    snprintf(input_struct->data[i].FREQUENCY, 32, "%f", LO_FREQ);
    
    //BELOW: filename should include time and state
    strncpy(input_struct->data[i].FILENAME, MEASURED_TIME, 32); //Time of rpi1
    input_struct->data[i].FILENAME[31] = '\0';
    
    free(MEASURED_TIME);
    end_time2 = clock();
    
    cpu_time_used2 = cpu_time_used1 = ((double) (end_time2-start_time2)) / CLOCKS_PER_SEC;
    
    //printf("TIME TAKEN TO SET VALUES IN DATA STRUCTURE: %f\n", cpu_time_used2);
    //free(MEASURED_STATE);
    //free(BUFFER);
    
    return 0;
}

int SAVE_OUTPUT(FITS_DATA* input_struct, int nrows) { //removed char *filename argument
    if (!input_struct) return -1; //removed || !filename in boolean

    fitsfile *fptr;
    int status = 0;
    int num = ChannelNumber;
    
    char *ttype[] = { "ADHAT_1", "ADHAT_2", "ADHAT_3", "TIME_RPI2", "SWITCH STATE", "FREQUENCY", "FILENAME" }; //removed TIME_RPI1
    char *tform[] = { "7K", "7K", "7K", "15A", "15A", "15A", "15A" }; //removed extra 15A
    char *tunit[] = { "", "", "", "", "", "" , "" }; //removed extra ""
    
    char full_filename[256];
    char filename[32];
    strncpy(filename, input_struct->data[0].FILENAME, 31);
    filename[31] = '\0';  // Ensure null-termination
    
    snprintf(full_filename, sizeof(full_filename), "!/home/peterson/Continuous_Sweep/%s", filename);
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

    //just make all of the empty columns & add the time, switch state and frequency FROM get data. all of this is data!!!!!!!!!!!!
    //UDOUBLE *col1_data = malloc(sizeof(UDOUBLE) * nrows);
    //UDOUBLE *col2_data = malloc(sizeof(UDOUBLE) * nrows);
    //UDOUBLE *col3_data = malloc(sizeof(UDOUBLE) * nrows);
    //char *col4_data = malloc(nrows * 15 * sizeof(char));
    //char *col5_data = malloc(nrows * 15 * sizeof(char));
    //char *col6_data = malloc(nrows * 15 * sizeof(char));
    //char *col7_data = malloc(nrows * 15 * sizeof(char));
    
    
    
    
    
    
    
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
    
    //printf("NROWS VALUEEEEEEEEEEEEEEEEEEE %d\n", nrows);
    
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
        return status;
    }

    printf("Buffer saved successfully.\n");

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
    
    
    gpioSetMode(4, PI_OUTPUT);
    
    gpioWrite(4, 1);
    
    gpioSetMode(5, PI_OUTPUT);
    gpioWrite(5, 1);
    
    gpioSetMode(6, PI_OUTPUT);
    gpioWrite(6, 1);
    sleep(1);
    gpioWrite(6, 0);
    sleep(1);
    gpioWrite(6, 1);
    sleep(1);
    gpioWrite(5, 0);
    sleep(1);
    gpioWrite(5, 1);
    
    
    
    /*
    wiringPiSetup();
    pinMode(13, OUTPUT);
    pinMode(19, OUTPUT);
    digitalWrite(13, HIGH);
    digitalWrite(19, HIGH);
    */
    
    sleep(5);
    //RUN_COMMAND(); //Sets up PyPipe to listen for frequencies, should severely reduce time...

    writer_args_t writer_args = {
        .nrows = nrows
    };

    pthread_t writer_thread;
    pthread_create(&writer_thread, NULL, writer_thread_func, &writer_args);

    int current_buffer = 1;
    int row_index = 0;
    
    //double *FREQ_VALUES = GET_FREQUENCIES(start_freq, end_freq, nrows);

    while (!exit_flag) {
        clock_t start_time, end_time;
        double cpu_time_used;
        
        start_time = clock();
        //printf("LOOP BEGAN: %ld\n", (long)start_time);
        FITS_DATA *active_buffer = (current_buffer == 1) ? bufferA : bufferB;
        
        //i think what i should do is ensure the number of frequencies to sweep thru matches the row index, generate the freq list, and then pass freq[row_index] value INTO GET_DATA
        //i think unfortunately it might be better to just calculate the regs and set them in get_data :(
        
        GET_DATA(active_buffer, row_index);
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

    pthread_mutex_lock(&buffer_mutex);
    exit_flag = 1;
    pthread_cond_signal(&buffer_ready_cond);
    pthread_mutex_unlock(&buffer_mutex);

    pthread_join(writer_thread, NULL);

    FREE_DATA_ARRAY(&bufferA);
    FREE_DATA_ARRAY(&bufferB);
    
    //free(FREQ_VALUES);

    gpioTerminate();
    CLOSE_GPIO();

    printf("Program ended cleanly.\n");

    return 0;
}
