#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <signal.h>
#include <pthread.h>
#include <fitsio.h>
#include <time.h>
#include <pigpio.h>

// Your includes
#include "/home/peterson/High-Pricision_AD_HAT_1/c/lib/Driver/ADS1263.h"

// Types and constants
#define ChannelNumber 7

double LO_FREQ = 902.4;             //code architecture immediately increments

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

// Globals for buffers and synchronization
FITS_DATA *bufferA = NULL;
FITS_DATA *bufferB = NULL;

pthread_mutex_t buffer_mutex = PTHREAD_MUTEX_INITIALIZER;
pthread_cond_t buffer_ready_cond = PTHREAD_COND_INITIALIZER;

int buffer_to_write = 0;   // 0 = none, 1 = bufferA, 2 = bufferB
int exit_flag = 0;

// Struct to pass multiple parameters to writer thread
typedef struct {
    const char *filename;
    int nrows;
} writer_args_t;

void Handler(int signo) {
    printf("\r\n END \r\n");
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

// double *GET_FREQUENCIES(int start_value, int end_value, int nrows)
// {
//     double *return_buffer = (double *)malloc(nrows * sizeof(double));
//     if (!return_buffer) return NULL;
    
//     double end = (double)end_value;
//     double start = (double)start_value;

//     double step = (end_value - start_value) / nrows;
    
//     for (int i = 0; i < nrows; i++) {
//         return_buffer[i] = start_value + i * step;
//     }
    
//     return return_buffer;
// }

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

int GET_DATA(FITS_DATA *input_struct, int i) {
    clock_t start_time1, end_time1, start_time2, end_time2;
    double cpu_time_used1, cpu_time_used2;
    
    if (!input_struct || i >= input_struct->nrows) return -1;

    UBYTE ChannelList[ChannelNumber] = {0,1,2,3,4,5,6};
    
    char *MEASURED_TIME = GET_TIME();
    start_time1 = clock();
    
    
    // if (LO_FREQ < 956.0 + 2.7/2 - 0.2){
    if (LO_FREQ < 957.4){
        gpioWrite(4, 0);
        gpioDelay(3000);
        LO_FREQ = LO_FREQ + 0.2;
    }
    
    /*
    else {
        gpioWrite(5, 0);
        usleep(2000);
        gpioWrite(4, 0);
        LO_FREQ = 904.0;
    }
    */
    
    printf("###################################################################################################################################################################");
    printf("LO FREQ: %lf\n", LO_FREQ);   
    printf("###################################################################################################################################################################");
    
    usleep(500+1000000); //was 500
    end_time1 = clock();
    
    
    gpioWrite(4, 1);
    
    cpu_time_used1 = ((double) (end_time1-start_time1)) / CLOCKS_PER_SEC;
    
    ADS1263_GetAll(ChannelList, input_struct->data[i].ADHAT_1, ChannelNumber, 12, get_DRDYPIN(12));
    ADS1263_GetAll(ChannelList, input_struct->data[i].ADHAT_2, ChannelNumber, 22, get_DRDYPIN(22));
    ADS1263_GetAll(ChannelList, input_struct->data[i].ADHAT_3, ChannelNumber, 23, get_DRDYPIN(23));
    
    start_time2 = clock();
    
    strncpy(input_struct->data[i].TIME_RPI2, MEASURED_TIME, 32); //Time of local pi
    input_struct->data[i].TIME_RPI2[31] = '\0'; //Time of local pi
    
    strncpy(input_struct->data[i].STATE, "GPIOS_NOT_SET", 32); //State of rf box
    input_struct->data[i].STATE[31] = '\0'; //State sent from rpi1
    
    snprintf(input_struct->data[i].FREQUENCY, 32, "%f", LO_FREQ);
    
    //BELOW: filename should include time and state
    strncpy(input_struct->data[i].FILENAME, MEASURED_TIME, 32); //Time of rpi1
    input_struct->data[i].FILENAME[31] = '\0';
    
    free(MEASURED_TIME);
    end_time2 = clock();
    
    cpu_time_used2 = cpu_time_used1 = ((double) (end_time2-start_time2)) / CLOCKS_PER_SEC;
    
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
        
        if (buf) {
            
            printf("ABOUT TO SAVE DATA...\n");
            clock_t start_time, end_time;
            double cpu_time_used;
        
            start_time = clock();
            end_time = clock();
        
            int status = SAVE_OUTPUT(buf, nrows); //removed filename argument
            printf("STATUS: %d\n", status);
            
            if (status != 0) {
                printf("Error saving FITS data: %d\n", status);
            }
            
            cpu_time_used = ((double) (end_time-start_time)) / CLOCKS_PER_SEC;
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
    
    // BCM numbering
    gpioSetMode(4, PI_OUTPUT); // LOSET -> Arduino D6
    gpioSetMode(5, PI_OUTPUT); // RESET -> Arduino D7
    gpioSetMode(6, PI_OUTPUT); // CALIB -> Arduino D8

    // Idle HIGH
    gpioWrite(4, 1);
    gpioWrite(5, 1);
    gpioWrite(6, 1);
    gpioDelay(2000); // 2 ms settle
    
    // Toggle CALIB once to switch from low -> high band
    gpioWrite(6, 0);         // falling edge -> toggle band
    gpioDelay(3000);         // 3 ms
    gpioWrite(6, 1);
    gpioDelay(3000);

    // gpioWrite(6, 0);
    // sleep(0.5);
    
    // gpioWrite(5, 0);
    
    // sleep(2);

    writer_args_t writer_args = {
        .nrows = nrows
    };

    pthread_t writer_thread;
    pthread_create(&writer_thread, NULL, writer_thread_func, &writer_args);

    int current_buffer = 1;
    int row_index = 0;

    //Change to stop after one sweep
    // while (LO_FREQ < 956.0 + 2.7/2 - 0.2) {
    while (LO_FREQ < 957.6) {
        clock_t start_time, end_time;
        double cpu_time_used;
        
        start_time = clock();
        FITS_DATA *active_buffer = (current_buffer == 1) ? bufferA : bufferB;
        
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
    
    gpioWrite(4, 1);
    sleep(0.5);
    gpioWrite(5, 1);
    sleep(0.5);
    gpioWrite(6, 1);
    sleep(0.5);
    gpioWrite(5, 0);
    sleep(0.5);
    gpioWrite(5, 1);

    gpioTerminate();
    CLOSE_GPIO();

    printf("Program ended cleanly.\n");

    return 0;
}
