/*=============================================================================
* HIGHZ AUTOMATED CYCLE CONTROLLER
* 
* Manages continuous cycle execution with persistent state tracking.
* Runs continuously on startup, executing state sequence 2→3→4→5→6→7→1→0
* for each cycle.
*
* Usage: sudo ./bin/cycle_control --timezone <offset> --spectra-calib <count> --spectra-antenna <count>
* Example: sudo ./bin/cycle_control --timezone -07:00 --spectra-calib 7 --spectra-antenna 300
*============================================================================*/

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <signal.h>
#include <time.h>
#include <sys/stat.h>
#include <errno.h>
#include <stdarg.h>
#include <pigpio.h>

// Common highz constants
#include "highz_common.h"

// GPIO pins for state control (active-low logic)
#define BIT_0 20
#define BIT_1 24
#define BIT_2 27

// File paths
#define STATE_FILE "/media/peterson/INDURANCE/Data/.cycle_state"
#define CONFIG_FILE "/media/peterson/INDURANCE/Data/.antenna_config"
#define BASE_DIR "/media/peterson/INDURANCE/Data"
#define LOG_DIR "/media/peterson/INDURANCE/Logs"

// State sequence: 2→3→4→5→6→7→1→0
static const int STATE_SEQUENCE[] = {2, 3, 4, 5, 6, 7, 1, 0};
static const int SEQUENCE_LENGTH = 8;

// Global variables
volatile sig_atomic_t running = 1;
char TIMEZONE_STRING[10];
int TIMEZONE_OFFSET_SECONDS = 0;
int SPECTRA_CALIB = 7;      // For states 1-7
int SPECTRA_ANTENNA = 300;  // For state 0
FILE* LOGFILE = NULL;
char RUN_LOG_DIR[768];      // Directory for this run's logs

// Data structures
typedef struct {
    char antenna_id[64];
    char site_name[64];
    char notes[256];
} AntennaConfig;

typedef struct {
    char date[16];        // MMDDYYYY
    int cycle_number;     // 001, 002, etc.
    int current_state;    // Last completed state
} PersistentState;

typedef struct {
    char cycle_id[32];
    char start_time[32];
    char end_time[32];
    char timezone[32];
    AntennaConfig antenna;
} CycleMetadata;

/*=============================================================================
* LOGGING FUNCTIONS
*============================================================================*/
void LOG_PRINT(const char* format, ...) {
    va_list args1, args2;
    
    // Print to console
    va_start(args1, format);
    vprintf(format, args1);
    va_end(args1);
    
    // Print to logfile if open
    if (LOGFILE) {
        va_start(args2, format);
        vfprintf(LOGFILE, format, args2);
        va_end(args2);
        fflush(LOGFILE);
    }
}

void OPEN_LOGFILE() {
    // Create base log directory if it doesn't exist
    mkdir(LOG_DIR, 0755);
    
    // Create run-specific directory with timestamp
    time_t raw_time = time(NULL) + TIMEZONE_OFFSET_SECONDS;
    struct tm* time_info = gmtime(&raw_time);
    
    strftime(RUN_LOG_DIR, sizeof(RUN_LOG_DIR), LOG_DIR "/run_%Y%m%d_%H%M%S", time_info);
    mkdir(RUN_LOG_DIR, 0755);
    
    // Create controller logfile in run directory
    char filename[1024];
    snprintf(filename, sizeof(filename), "%s/cycle_control.log", RUN_LOG_DIR);
    
    LOGFILE = fopen(filename, "w");
    if (!LOGFILE) {
        fprintf(stderr, "WARNING: Could not create logfile: %s\n", strerror(errno));
        fprintf(stderr, "Continuing without logging to file.\n");
    } else {
        LOG_PRINT("Logfile created: %s\n", filename);
        LOG_PRINT("Run log directory: %s\n", RUN_LOG_DIR);
    }
}

void CLOSE_LOGFILE() {
    if (LOGFILE) {
        LOG_PRINT("Closing logfile.\n");
        fclose(LOGFILE);
        LOGFILE = NULL;
    }
}

/*=============================================================================
* SIGNAL HANDLING
*============================================================================*/
void signal_handler(int signo) {
    if (signo == SIGINT || signo == SIGTERM) {
        const char msg[] = "\nShutdown signal received. Cleaning up...\n";
        write(STDERR_FILENO, msg, sizeof(msg) - 1);
        running = 0;
    }
}

/*=============================================================================
* GPIO CONTROL
*============================================================================*/
void set_gpio_state(int state) {
    if (state < 0 || state > 7) {
        LOG_PRINT("Invalid state: %d\n", state);
        return;
    }
    
    int inverted = 7 - state; // Active-low logic
    gpioWrite(BIT_0, (inverted >> 0) & 1);
    gpioWrite(BIT_1, (inverted >> 1) & 1);
    gpioWrite(BIT_2, (inverted >> 2) & 1);
    
    LOG_PRINT("State changed to: %d\n", state);
    sleep(1); // Allow state to stabilize
}

/*=============================================================================
* TIME FUNCTIONS
*============================================================================*/
int PARSE_TIMEZONE(const char* tz_string) {
    int sign = 1;
    int hours = 0;
    int minutes = 0;
    
    if (tz_string[0] == '-') {
        sign = -1;
    }
    
    if (sscanf(tz_string + 1, "%d:%d", &hours, &minutes) == 2) {
        return sign * (hours * 3600 + minutes * 60);
    } else if (sscanf(tz_string + 1, "%d", &hours) == 1) {
        return sign * (hours * 3600);
    }
    
    return 0;
}

void GET_TIME(char* buffer, size_t size) {
    time_t raw_time = time(NULL) + TIMEZONE_OFFSET_SECONDS;
    struct tm* time_info = gmtime(&raw_time);
    strftime(buffer, size, "%H:%M:%S", time_info);
}

void GET_DATE(char* buffer, size_t size) {
    time_t raw_time = time(NULL) + TIMEZONE_OFFSET_SECONDS;
    struct tm* time_info = gmtime(&raw_time);
    strftime(buffer, size, "%m%d%Y", time_info);
}

void GET_ISO_TIMESTAMP(char* buffer, size_t size) {
    time_t raw_time = time(NULL) + TIMEZONE_OFFSET_SECONDS;
    struct tm* time_info = gmtime(&raw_time);
    strftime(buffer, size, "%Y-%m-%dT%H:%M:%S", time_info);
}

/*=============================================================================
* CONFIG FILE HANDLING
*============================================================================*/
int READ_ANTENNA_CONFIG(AntennaConfig* config) {
    FILE* fp = fopen(CONFIG_FILE, "r");
    if (!fp) {
        // Set defaults if config doesn't exist
        strcpy(config->antenna_id, "Unknown");
        strcpy(config->site_name, "Unknown");
        strcpy(config->notes, "No configuration file found");
        return 0;
    }
    
    // Simple key=value parser
    char line[512];
    while (fgets(line, sizeof(line), fp)) {
        // Remove trailing newline
        line[strcspn(line, "\n")] = 0;
        
        // Skip comments and empty lines
        if (line[0] == '#' || line[0] == '\0') {
            continue;
        }
        
        // Parse key=value
        char* key = strtok(line, "=");
        char* value = strtok(NULL, "=");
        
        if (key && value) {
            if (strcmp(key, "antenna_id") == 0) {
                strncpy(config->antenna_id, value, sizeof(config->antenna_id) - 1);
            } else if (strcmp(key, "site_name") == 0) {
                strncpy(config->site_name, value, sizeof(config->site_name) - 1);
            } else if (strcmp(key, "notes") == 0) {
                strncpy(config->notes, value, sizeof(config->notes) - 1);
            }
        }
    }
    
    fclose(fp);
    return 1;
}

/*=============================================================================
* PERSISTENT STATE MANAGEMENT
*============================================================================*/
int READ_STATE_FILE(PersistentState* state) {
    FILE* fp = fopen(STATE_FILE, "r");
    if (!fp) {
        // No state file - initialize fresh
        GET_DATE(state->date, sizeof(state->date));
        state->cycle_number = 1;
        state->current_state = -1; // Start before first state
        return 0;
    }
    
    // Format: MMDDYYYY:cycle_num:state
    int result = fscanf(fp, "%15[^:]:%d:%d", state->date, &state->cycle_number, &state->current_state);
    fclose(fp);
    
    if (result != 3) {
        // Corrupted state - start fresh
        GET_DATE(state->date, sizeof(state->date));
        state->cycle_number = 1;
        state->current_state = -1;
        return 0;
    }
    
    return 1;
}

void WRITE_STATE_FILE(const PersistentState* state) {
    FILE* fp = fopen(STATE_FILE, "w");
    if (!fp) {
        fprintf(stderr, "ERROR: Could not write state file: %s\n", strerror(errno));
        return;
    }
    
    fprintf(fp, "%s:%d:%d\n", state->date, state->cycle_number, state->current_state);
    fclose(fp);
}

/*=============================================================================
* CYCLE ID GENERATION
*============================================================================*/
void GENERATE_CYCLE_ID(char* buffer, size_t size, const char* date, int cycle_num) {
    snprintf(buffer, size, "Cycle_%s_%03d", date, cycle_num);
}

/*=============================================================================
* METADATA FILE CREATION
*============================================================================*/
void CREATE_METADATA_FILE(const char* cycle_dir, const CycleMetadata* metadata) {
    char filepath[512];
    snprintf(filepath, sizeof(filepath), "%s/cycle_metadata.json", cycle_dir);
    
    FILE* fp = fopen(filepath, "w");
    if (!fp) {
        fprintf(stderr, "ERROR: Could not create metadata file: %s\n", strerror(errno));
        return;
    }
    
    fprintf(fp, "{\n");
    fprintf(fp, "  \"cycle_id\": \"%s\",\n", metadata->cycle_id);
    fprintf(fp, "  \"start_time\": \"%s\",\n", metadata->start_time);
    fprintf(fp, "  \"end_time\": \"%s\",\n", metadata->end_time);
    fprintf(fp, "  \"timezone\": \"%s\",\n", metadata->timezone);
    fprintf(fp, "  \"state_sequence\": [2, 3, 4, 5, 6, 7, 1, 0],\n");
    fprintf(fp, "  \"spectra_calib\": %d,\n", SPECTRA_CALIB);
    fprintf(fp, "  \"spectra_antenna\": %d,\n", SPECTRA_ANTENNA);
    fprintf(fp, "  \"adc_reference_voltage\": %.2f,\n", ADC_REFERENCE_VOLTAGE);
    fprintf(fp, "  \"antenna\": {\n");
    fprintf(fp, "    \"antenna_id\": \"%s\",\n", metadata->antenna.antenna_id);
    fprintf(fp, "    \"site_name\": \"%s\",\n", metadata->antenna.site_name);
    fprintf(fp, "    \"notes\": \"%s\"\n", metadata->antenna.notes);
    fprintf(fp, "  }\n");
    fprintf(fp, "}\n");
    
    fclose(fp);
    LOG_PRINT("Created metadata file: %s\n", filepath);
}

/*=============================================================================
* PROGRAM EXECUTION
*============================================================================*/
int EXECUTE_CONTINUOUS_ACQ(const char* cycle_id, int state, int num_spectra, const char* timezone) {
    // Redirect output to cycle-specific logfile
    char logfile[1024];
    snprintf(logfile, sizeof(logfile), "%s/%s.log", RUN_LOG_DIR, cycle_id);
    
    char command[2048];
    snprintf(command, sizeof(command), 
             "/home/peterson/highz/highz-filterbank/bin/acq %s %d %d %s >> %s 2>&1",
             cycle_id, state, num_spectra, timezone, logfile);
    
    LOG_PRINT("Executing: acq (state %d, %d spectra)\n", state, num_spectra);
    
    // Terminate GPIO to allow child program to access it
    gpioTerminate();
    
    int result = system(command);
    
    // Reinitialize GPIO
    if (gpioInitialise() < 0) {
        LOG_PRINT("ERROR: Failed to reinitialize GPIO after acq\n");
        return 0;
    }
    
    // Reconfigure GPIO pins
    gpioSetMode(BIT_0, PI_OUTPUT);
    gpioSetMode(BIT_1, PI_OUTPUT);
    gpioSetMode(BIT_2, PI_OUTPUT);
    
    // Restore the current state
    set_gpio_state(state);
    
    if (result != 0) {
        LOG_PRINT("ERROR: continuous_acq failed for state %d (exit code: %d)\n", state, result);
        return 0;
    }
    
    return 1;
}

int EXECUTE_FILTER_SWEEP(const char* cycle_id, const char* timezone, int state) {
    // Redirect output to cycle-specific logfile
    char logfile[1024];
    snprintf(logfile, sizeof(logfile), "%s/%s.log", RUN_LOG_DIR, cycle_id);
    
    char command[2048];
    snprintf(command, sizeof(command), 
             "/home/peterson/highz/highz-filterbank/bin/calib %s %s >> %s 2>&1",
             cycle_id, timezone, logfile);
    
    LOG_PRINT("Executing: calib (filter sweep)\n");
    
    // Terminate GPIO to allow child program to access it
    gpioTerminate();
    
    int result = system(command);
    
    // Reinitialize GPIO
    if (gpioInitialise() < 0) {
        LOG_PRINT("ERROR: Failed to reinitialize GPIO after calib\n");
        return 0;
    }
    
    // Reconfigure GPIO pins
    gpioSetMode(BIT_0, PI_OUTPUT);
    gpioSetMode(BIT_1, PI_OUTPUT);
    gpioSetMode(BIT_2, PI_OUTPUT);
    
    // Restore the current state
    set_gpio_state(state);
    
    if (result != 0) {
        LOG_PRINT("ERROR: filterSweep failed (exit code: %d)\n", result);
        return 0;
    }
    
    return 1;
}

/*=============================================================================
* CYCLE EXECUTION
*============================================================================*/
int EXECUTE_CYCLE(const char* cycle_id, const char* timezone, const AntennaConfig* antenna_config) {
    char current_date[16];
    GET_DATE(current_date, sizeof(current_date));
    
    // Create date directory if needed
    char date_dir[256];
    snprintf(date_dir, sizeof(date_dir), "%s/%s", BASE_DIR, current_date);
    mkdir(date_dir, 0755);
    
    // Create cycle directory
    char cycle_dir[512];
    snprintf(cycle_dir, sizeof(cycle_dir), "%s/%s", date_dir, cycle_id);
    mkdir(cycle_dir, 0755);
    
    LOG_PRINT("\n========================================\n");
    LOG_PRINT("Starting cycle: %s\n", cycle_id);
    LOG_PRINT("Directory: %s\n", cycle_dir);
    LOG_PRINT("========================================\n\n");
    
    // Initialize metadata
    CycleMetadata metadata;
    strcpy(metadata.cycle_id, cycle_id);
    GET_ISO_TIMESTAMP(metadata.start_time, sizeof(metadata.start_time));
    strcpy(metadata.timezone, timezone);
    metadata.antenna = *antenna_config;
    
    // Execute state sequence: 2→3→4→5→6→7→1→0
    for (int i = 0; i < SEQUENCE_LENGTH && running; i++) {
        int state = STATE_SEQUENCE[i];
        
        // Determine spectra count based on state
        int num_spectra = (state == 0) ? SPECTRA_ANTENNA : SPECTRA_CALIB;
        
        LOG_PRINT("\n--- State %d (%d spectra) ---\n", state, num_spectra);
        set_gpio_state(state);
        
        // State 2 needs filter sweep + data acquisition
        if (state == 2) {
            if (!EXECUTE_FILTER_SWEEP(cycle_id, timezone, state)) {
                LOG_PRINT("ERROR: Filter sweep failed for cycle %s\n", cycle_id);
                return 0;
            }
        }
        
        // All states get continuous acquisition
        if (!EXECUTE_CONTINUOUS_ACQ(cycle_id, state, num_spectra, timezone)) {
            LOG_PRINT("ERROR: Data acquisition failed for state %d in cycle %s\n", state, cycle_id);
            return 0;
        }
    }
    
    // Finalize metadata
    GET_ISO_TIMESTAMP(metadata.end_time, sizeof(metadata.end_time));
    CREATE_METADATA_FILE(cycle_dir, &metadata);
    
    LOG_PRINT("\n========================================\n");
    LOG_PRINT("Cycle %s completed successfully\n", cycle_id);
    LOG_PRINT("========================================\n\n");
    
    return 1;
}

/*=============================================================================
* MAIN PROGRAM
*============================================================================*/
int main(int argc, char* argv[]) {
    // Parse command-line arguments
    if (argc != 7 || 
        strcmp(argv[1], "--timezone") != 0 || 
        strcmp(argv[3], "--spectra-calib") != 0 || 
        strcmp(argv[5], "--spectra-antenna") != 0) {
        fprintf(stderr, "Usage: %s --timezone <offset> --spectra-calib <count> --spectra-antenna <count>\n", argv[0]);
        fprintf(stderr, "Example: %s --timezone -07:00 --spectra-calib 7 --spectra-antenna 300\n", argv[0]);
        return 1;
    }
    
    strcpy(TIMEZONE_STRING, argv[2]);
    TIMEZONE_OFFSET_SECONDS = PARSE_TIMEZONE(TIMEZONE_STRING);
    SPECTRA_CALIB = atoi(argv[4]);
    SPECTRA_ANTENNA = atoi(argv[6]);
    
    if (SPECTRA_CALIB <= 0 || SPECTRA_ANTENNA <= 0) {
        fprintf(stderr, "ERROR: Spectra counts must be positive\n");
        return 1;
    }
    
    // Open logfile
    OPEN_LOGFILE();
    
    LOG_PRINT("========================================\n");
    LOG_PRINT("HIGHZ AUTOMATED CYCLE CONTROLLER\n");
    LOG_PRINT("========================================\n");
    LOG_PRINT("Timezone: %s (offset: %d seconds)\n", TIMEZONE_STRING, TIMEZONE_OFFSET_SECONDS);
    LOG_PRINT("Spectra (calibration states 1-7): %d\n", SPECTRA_CALIB);
    LOG_PRINT("Spectra (antenna state 0): %d\n", SPECTRA_ANTENNA);
    LOG_PRINT("State sequence: 2→3→4→5→6→7→1→0\n");
    LOG_PRINT("========================================\n\n");
    
    // Initialize GPIO
    if (gpioInitialise() < 0) {
        fprintf(stderr, "ERROR: Failed to initialize GPIO\n");
        return 1;
    }
    
    gpioSetMode(BIT_0, PI_OUTPUT);
    gpioSetMode(BIT_1, PI_OUTPUT);
    gpioSetMode(BIT_2, PI_OUTPUT);
    
    // Set up signal handlers
    signal(SIGINT, signal_handler);
    signal(SIGTERM, signal_handler);
    
    // Read antenna configuration
    AntennaConfig antenna_config;
    READ_ANTENNA_CONFIG(&antenna_config);
    LOG_PRINT("Antenna: %s\n", antenna_config.antenna_id);
    LOG_PRINT("Site: %s\n", antenna_config.site_name);
    LOG_PRINT("Notes: %s\n\n", antenna_config.notes);
    
    // Read persistent state
    PersistentState state;
    int state_exists = READ_STATE_FILE(&state);
    
    char current_date[16];
    GET_DATE(current_date, sizeof(current_date));
    
    // Check if we need to start a new cycle
    if (state_exists) {
        LOG_PRINT("Found previous state:\n");
        LOG_PRINT("  Date: %s\n", state.date);
        LOG_PRINT("  Cycle: %d\n", state.cycle_number);
        LOG_PRINT("  Last state: %d\n\n", state.current_state);
        
        // If date changed or state was completed, increment cycle
        if (strcmp(state.date, current_date) != 0 || state.current_state == 0) {
            strcpy(state.date, current_date);
            state.cycle_number++;
        } else {
            // Restart interrupted cycle → move to next cycle
            state.cycle_number++;
        }
    }
    
    LOG_PRINT("Starting from cycle %d\n\n", state.cycle_number);
    
    // Main cycle loop
    while (running) {
        // Generate cycle ID
        char cycle_id[32];
        GENERATE_CYCLE_ID(cycle_id, sizeof(cycle_id), state.date, state.cycle_number);
        
        // Execute the cycle
        if (!EXECUTE_CYCLE(cycle_id, TIMEZONE_STRING, &antenna_config)) {
            LOG_PRINT("ERROR: Cycle execution failed\n");
            break;
        }
        
        // Update state for next cycle
        GET_DATE(state.date, sizeof(state.date)); // Update date in case we crossed midnight
        state.cycle_number++;
        state.current_state = 0; // Completed full cycle
        WRITE_STATE_FILE(&state);
        
        LOG_PRINT("State saved. Ready for next cycle.\n\n");
    }
    
    // Cleanup
    LOG_PRINT("\nShutting down...\n");
    set_gpio_state(5); // Return to safe state
    gpioTerminate();
    
    LOG_PRINT("Shutdown complete.\n");
    CLOSE_LOGFILE();
    return 0;
}
