#include "manual_state_ctrl.h"

volatile sig_atomic_t running = 1;
volatile int current_state = 5;
pthread_mutex_t state_mutex = PTHREAD_MUTEX_INITIALIZER;

// Sets GPIO pins according to the given state (0-7)
void signal_handler(int signo) {
    if (signo == SIGINT) {
        const char msg[] = "\nInterrupt signal received. Exiting gracefully...\n";
        write(STDERR_FILENO, msg, sizeof(msg) - 1);
        running = 0;
    }
}

void set_gpio_state(int state) {
    if (state < 0 || state > 7) {
        printf("Invalid state: %d. Must be between 0 and 7.\n", state);
        return;
    }

    int inverted = 7 - state; // Invert the state for active-low logic
    gpioWrite(BIT_0, (inverted >> 0) & 1);
    gpioWrite(BIT_1, (inverted >> 1) & 1);
    gpioWrite(BIT_2, (inverted >> 2) & 1);
}

// Thread function to read user input
void* input_thread(void* arg) {
    char input[10];
    while (running) {
        printf("Enter new state (0-7): ");
        fflush(stdout);
        
        if (fgets(input, sizeof(input), stdin) != NULL) {
            int new_state = atoi(input);
            if (new_state >= 0 && new_state <= 7) {
                pthread_mutex_lock(&state_mutex);
                current_state = new_state;
                set_gpio_state(current_state);
                pthread_mutex_unlock(&state_mutex);
                printf("State changed to: %d\n", current_state);
            } else {
                printf("Invalid state. Must be between 0 and 7.\n");
            }
        }
    }
    return NULL;
}

int main(int argc, char *argv[]) {
    // Initialize GPIO
    if (gpioInitialise() < 0){
        printf("initialization of pigpio failed\n");
        return 1;
    }
    
    // Set GPIO modes
    gpioSetMode(BIT_0, PI_OUTPUT);
    gpioSetMode(BIT_1, PI_OUTPUT);
    gpioSetMode(BIT_2, PI_OUTPUT);
    
    current_state = (argc > 1) ? atoi(argv[1]) : 5;
    set_gpio_state(current_state);
    printf("Initial state set to: %d\n", current_state);
    
    signal(SIGINT, signal_handler);
    
    // Create input thread
    pthread_t input_tid;
    pthread_create(&input_tid, NULL, input_thread, NULL);
    
    while (running) {
        sleep(1);
    }
    
    // Cleanup
    pthread_cancel(input_tid);
    pthread_join(input_tid, NULL);
    pthread_mutex_destroy(&state_mutex);
    
    gpioTerminate();
    return 0;
}


