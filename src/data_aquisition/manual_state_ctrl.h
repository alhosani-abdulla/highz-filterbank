/* Header file for state control functions */
#ifndef STATE_CTRL_H
#define STATE_CTRL_H

/* Standard C Libraries */
#include <stdio.h>    // Standard I/O operations
#include <stdlib.h>   // Memory allocation, random numbers
#include <string.h>   // String manipulation
#include <unistd.h>   // POSIX API (write, usleep)
#include <signal.h>  // Signal handling for graceful shutdown
#include <pthread.h>  // POSIX threading for potential future use

/* Hardware-Specific Libraries */
#include <pigpio.h>   // Raspberry Pi GPIO control

// GPIO Pin Configuration
const int BIT_0 = 21;
const int BIT_1 = 24;
const int BIT_2 = 27;

void set_gpio_state(int state);
void* input_thread(void* arg);
void signal_handler(int signo);

#endif
