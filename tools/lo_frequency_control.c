/*
 * Interactive controller for the High-Z filterbank's two local oscillators.
 *
 * Mixer LO: GPIO 4 (increment), 5 (reset), 6 (power)
 * Tone  LO: GPIO 13 (increment), 19 (reset), 26 (power)
 * RF state: GPIO 20 (bit 0), 24 (bit 1), 27 (bit 2) - active LOW.
 *
 * IMPORTANT: Tone frequency values below come from highz_common.h's
 * CALIB_* settings (900-960 MHz, 0.2 MHz increments). Confirm these
 * match the firmware actually loaded on the SECOND Arduino before use.
 * The second controller's edge and first-pulse behavior must also be
 * verified against a spectrum analyzer.
 *
 * Only one program should own/control these GPIOs at a time.
 */
#include <errno.h>
#include <ctype.h>
#include <math.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <pigpio.h>

#include "../src/instrument/highz_common.h"

#define ARDUINO_STEP_DELAY_US 50000  /* Allow Arduino 50 ms per pulse */
#define RESET_LOW_US          10000
#define RESET_SETTLE_US       50000
#define POWER_SETTLE_US      100000

/* Match Pins.txt and cycle_control.c; manual_state_ctrl.h erroneously has bit 0 = 21. */
#define RF_BIT0_GPIO 20
#define RF_BIT1_GPIO 24
#define RF_BIT2_GPIO 27
#define RF_SAFE_STATE 5 /* Same shutdown state used by cycle_control.c */

static volatile sig_atomic_t keep_running = 1;

/* The names here match continuous_acq.c's state_names array. */
static const char *rf_names[8] = {
    "Antenna", "Open Circuit", "Short Circuit", "Long Cable Open Circuit",
    "Black Body", "Ambient Temperature Load", "Noise Diode", "Long Cable Short Circuit"
};
static const int rf_pins[3] = { RF_BIT0_GPIO, RF_BIT1_GPIO, RF_BIT2_GPIO };
static int rf_current_state = -1;  /* Unknown until explicitly written. */


typedef struct {
    const char *name;
    int increment_pin;
    int reset_pin;
    int power_pin;
    double min_mhz;
    double max_mhz;
    double step_mhz;
    double last_mhz;
    int has_frequency;
    int power_on;
} Oscillator;

static Oscillator mixer = {
    .name = "Mixer LO",
    .increment_pin = ACQ_GPIO_FREQ_INCREMENT,
    .reset_pin = ACQ_GPIO_FREQ_RESET,
    .power_pin = ACQ_GPIO_LO_POWER,
    .min_mhz = ACQ_FREQ_MIN,
    .max_mhz = ACQ_FREQ_MAX,
    .step_mhz = ACQ_FREQ_STEP
};

static Oscillator tone = {
    .name = "Tone LO",
    .increment_pin = CALIB_GPIO_FREQ_INCREMENT,
    .reset_pin = CALIB_GPIO_FREQ_RESET,
    .power_pin = CALIB_GPIO_LO_POWER,
    .min_mhz = CALIB_FREQ_MIN,
    .max_mhz = CALIB_FREQ_MAX,
    .step_mhz = CALIB_FREQ_STEP
};

static void handle_signal(int sig)
{
    (void)sig;
    keep_running = 0;
}

static int write_pin(int pin, int level)
{
    int rc = gpioWrite(pin, level);
    if (rc != 0) {
        fprintf(stderr, "GPIO %d write failed (pigpio code %d).\n", pin, rc);
        return -1;
    }
    return 0;
}

/* Reject junk such as 700abc, NaN, or 700 800. */
static int parse_mhz(const char *value, double *mhz)
{
    char *end = NULL;
    errno = 0;
    double result = strtod(value, &end);
    if (value == end || *end != '\0' || errno == ERANGE || !isfinite(result)) {
        return -1;
    }
    *mhz = result;
    return 0;
}

/* Validate before touching hardware. Returns pulse-grid step count. */
static int frequency_steps(const Oscillator *lo, double target, long *steps)
{
    if (!isfinite(target) || target < lo->min_mhz - 1e-6 ||
        target > lo->max_mhz + 1e-6) {
        fprintf(stderr, "%s: frequency must be %.1f to %.1f MHz.\n",
                lo->name, lo->min_mhz, lo->max_mhz);
        return -1;
    }

    double raw_steps = (target - lo->min_mhz) / lo->step_mhz;
    long count = lround(raw_steps);
    double nearest = lo->min_mhz + count * lo->step_mhz;
    if (fabs(target - nearest) > 1e-5) {
        fprintf(stderr, "%s: use %.1f MHz steps (starting at %.1f).\n",
                lo->name, lo->step_mhz, lo->min_mhz);
        return -1;
    }
    *steps = count;
    return 0;
}

static int initialize_gpio(void)
{
    if (gpioInitialise() < 0) {
        fprintf(stderr, "Error: failed to initialize pigpio.\n");
        return -1;
    }
    Oscillator *los[] = {&mixer, &tone};
    for (size_t i = 0; i < 2; ++i) {
        Oscillator *lo = los[i];
        if (gpioSetMode(lo->power_pin, PI_OUTPUT) != 0 ||
            gpioSetMode(lo->increment_pin, PI_OUTPUT) != 0 ||
            gpioSetMode(lo->reset_pin, PI_OUTPUT) != 0 ||
            write_pin(lo->power_pin, 0) != 0 ||
            write_pin(lo->increment_pin, 1) != 0 ||
            write_pin(lo->reset_pin, 1) != 0) {
            fprintf(stderr, "Error: could not initialize %s GPIO.\n", lo->name);
            /* Make a best effort to turn both outputs off. */
            gpioWrite(mixer.power_pin, 0);
            gpioWrite(tone.power_pin, 0);
            gpioTerminate();
            return -1;
        }
    }
    gpioDelay(POWER_SETTLE_US);
    return 0;
}

static int pulse_reset(Oscillator *lo)
{
    if (write_pin(lo->reset_pin, 0) != 0) return -1;
    gpioDelay(RESET_LOW_US);
    if (write_pin(lo->reset_pin, 1) != 0) return -1;
    gpioDelay(RESET_SETTLE_US);
    return 0;
}

static int pulse_increment(Oscillator *lo)
{
    /* LOW then HIGH: first oscillator's firmware programs on rising edge. */
    if (write_pin(lo->increment_pin, 0) != 0) return -1;
    gpioDelay(DEFAULT_PULSE_LOW_US);
    if (write_pin(lo->increment_pin, 1) != 0) return -1;
    gpioDelay(ARDUINO_STEP_DELAY_US);
    return 0;
}

static void turn_off(Oscillator *lo)
{
    /* Same double reset used by the original controller at shutdown. */
    write_pin(lo->increment_pin, 1);
    for (int i = 0; i < 2; ++i) {
        write_pin(lo->reset_pin, 0);
        gpioDelay(10000);
        write_pin(lo->reset_pin, 1);
        gpioDelay(5000);
    }
    write_pin(lo->power_pin, 0);
    gpioDelay(5000);
    lo->power_on = 0;
    printf("%s power OFF.\n", lo->name);
}

static int set_frequency(Oscillator *lo, double target)
{
    long steps;
    if (frequency_steps(lo, target, &steps) != 0) return -1;

    if (!lo->power_on) {
        if (write_pin(lo->power_pin, 1) != 0) return -1;
        lo->power_on = 1;
        gpioDelay(POWER_SETTLE_US);
        printf("%s powered ON.\n", lo->name);
    }

    printf("Resetting %s frequency counter to %.1f MHz...\n",
           lo->name, lo->min_mhz);
    if (pulse_reset(lo) != 0) goto fail;
    sleep(1); /* Preserve delay from the original working controller. */

    /*
     * The original mixer Arduino: reset establishes min_mhz internally,
     * and first increment pulse PROGRAMS min_mhz. Hence steps + 1.
     * VERIFY this is also true for the second Arduino's firmware.
     */
    long pulses = steps + 1;
    printf("%s: requested %.1f MHz; %ld steps; sending %ld pulses...\n",
           lo->name, target, steps, pulses);

    for (long i = 0; i < pulses; ++i) {
        if (!keep_running || pulse_increment(lo) != 0) goto fail;
    }
    lo->last_mhz = target;
    lo->has_frequency = 1;
    printf("%s commanded to %.1f MHz. Verify actual RF frequency.\n",
           lo->name, target);
    return 0;

fail:
    fprintf(stderr, "%s: frequency change interrupted or failed.\n", lo->name);
    lo->has_frequency = 0;
    turn_off(lo);
    return -1;
}

/*
 * RF box state, not a pulse protocol:
 * Logical state bits 2:1:0 -> physical active-low GPIO levels 2:1:0.
 * e.g. state 5 (101) -> gpio bit0=LOW, bit1=HIGH, bit2=LOW.
 */
static int rf_gpio_level(int state, int bit)
{
    return 1 - ((state >> bit) & 1);
}

static const char *rf_assertion(int level)
{
    return level == 0 ? "LOW (asserted)" : "HIGH (not asserted)";
}

static void print_rf_state(void)
{
    if (rf_current_state < 0) {
        printf("RF box: state UNKNOWN (not initialized).\n");
        return;
    }

    int state = rf_current_state;
    printf("RF box: state %d (%s)\n", state, rf_names[state]);
    printf("  Logical state bits [2 1 0]: %d %d %d\n",
           (state >> 2) & 1, (state >> 1) & 1, state & 1);
    for (int bit = 0; bit < 3; bit++) {
        int expected = rf_gpio_level(state, bit);
        int observed = gpioRead(rf_pins[bit]);
        printf("  Bit %d / GPIO %d: commanded %s",
               bit, rf_pins[bit], rf_assertion(expected));
        if (observed == 0 || observed == 1) {
            printf(" | GPIO reads %s%s", observed ? "HIGH" : "LOW",
                   observed == expected ? "" : " (MISMATCH!)");
        } else {
            printf(" | GPIO read error: %d", observed);
        }
        printf("\n");
    }
}

/* Print a list of names and actual GPIO levels for all 8 states. */
static void print_rf_states(void)
{
    printf("\nRF states (GPIO 20 / 24 / 27, active-LOW):\n");
    printf(" #  State name                     State bits   GPIO levels [2 1 0]\n");
    for (int state = 0; state < 8; state++) {
        printf(" %d  %-30s   %d%d%d          %d%d%d%s\n",
               state, rf_names[state],
               (state >> 2) & 1, (state >> 1) & 1, state & 1,
               rf_gpio_level(state, 2), rf_gpio_level(state, 1),
               rf_gpio_level(state, 0),
               state == rf_current_state ? "  <-- current" : "");
    }
    printf("GPIO level 0 = active/asserted; 1 = inactive/not asserted.\n");
}

static int set_rf_state(int state)
{
    if (state < 0 || state > 7) {
        fprintf(stderr, "RF state must be an integer from 0 to 7.\n");
        return -1;
    }

    int previous = rf_current_state;
    for (int bit = 0; bit < 3; ++bit) {
        if (write_pin(rf_pins[bit], rf_gpio_level(state, bit)) != 0) {
            fprintf(stderr, "RF state write failed. Actual state may be unknown.\n");
            rf_current_state = -1;
            return -1;
        }
    }
    /* cycle_control.c allows a second for RF switch state to settle. */
    gpioDelay(1000000);
    rf_current_state = state;

    printf("\nRF state set to %d (%s).\n", state, rf_names[state]);
    if (previous >= 0 && previous != state) {
        for (int bit = 0; bit < 3; bit++) {
            int before = rf_gpio_level(previous, bit);
            int after = rf_gpio_level(state, bit);
            if (before != after) {
                printf("  Bit %d: %s -> %s (GPIO %d: %s -> %s)\n",
                       bit, before ? "OFF" : "ON", after ? "OFF" : "ON",
                       rf_pins[bit], before ? "HIGH" : "LOW", after ? "HIGH" : "LOW");
            }
        }
    }
    print_rf_state();
    return 0;
}

static int initialize_rf_gpio(void)
{
    /* Both oscillator power GPIOs are OFF when this is called. */
    for (int bit = 0; bit < 3; bit++) {
        if (gpioSetMode(rf_pins[bit], PI_OUTPUT) != 0) {
            fprintf(stderr, "Cannot initialize RF box GPIO %d.\n", rf_pins[bit]);
            return -1;
        }
    }
    printf("Initializing RF box to state %d (%s).\n",
           RF_SAFE_STATE, rf_names[RF_SAFE_STATE]);
    return set_rf_state(RF_SAFE_STATE);
}

/* Accept state numbers, exact names, and a few convenient aliases. */
static int parse_rf_state(const char *text, int *result)
{
    char key[128];
    size_t length = 0;
    for (; *text; ++text) {
        unsigned char c = (unsigned char)*text;
        if (isalnum(c)) {
            if (length + 1 >= sizeof(key)) return -1;
            key[length++] = (char)tolower(c);
        } else if (!isspace(c) && c != '-' && c != '_') {
            return -1;
        }
    }
    key[length] = '\0';
    if (length == 1 && key[0] >= '0' && key[0] <= '7') {
        *result = key[0] - '0';
        return 0;
    }
    /* Official names, simplified as lowercase letters with no spaces. */
    static const char *normalized[8] = {
        "antenna", "opencircuit", "shortcircuit", "longcableopencircuit",
        "blackbody", "ambienttemperatureload", "noisediode", "longcableshortcircuit"
    };
    for (int state = 0; state < 8; state++) {
        if (!strcmp(key, normalized[state])) { *result = state; return 0; }
    }
    static const struct { const char *alias; int state; } aliases[] = {
        {"open", 1}, {"short", 2}, {"longopen", 3},
        {"black", 4}, {"ambient", 5}, {"ambientload", 5},
        {"noise", 6}, {"longshort", 7}, {"sky", 0}
    };
    for (size_t i = 0; i < sizeof(aliases) / sizeof(aliases[0]); i++) {
        if (!strcmp(key, aliases[i].alias)) {
            *result = aliases[i].state;
            return 0;
        }
    }
    return -1;
}

static void print_status(void)
{
    Oscillator *los[] = {&mixer, &tone};
    printf("\nOscillator status (commanded, not measured):\n");
    for (size_t i = 0; i < 2; ++i) {
        Oscillator *lo = los[i];
        printf("  %-9s: %s", lo->name,
               lo->power_on ? "ON " : "OFF");
        if (lo->has_frequency) printf(" | last target: %.1f MHz", lo->last_mhz);
        printf("\n");
    }
    printf("\nRF box state (commanded GPIO, not measured RF path):\n");
    print_rf_state();
}

static void print_help(void)
{
    printf("\nCommands:\n"
           "  mixer 800    Set mixer LO to 800 MHz\n"
           "  tone 930     Set calibration/tone LO to 930 MHz\n"
           "  mixer off    Switch mixer LO OFF\n"
           "  tone off     Switch calibration/tone LO OFF\n"
           "  mixer on     Restore last mixer target after OFF\n"
           "  tone on      Restore last tone target after OFF\n"
           "  rf 0         RF box state 0 (Antenna)\n"
           "  rf ambient   RF box state 5 (Ambient Temperature Load)\n"
           "  rf noise diode  RF box state 6 (Noise Diode)\n"
           "  state 7      Alternate RF command; 0-7 or full names work\n"
           "  5            Bare 0-7 also selects RF state\n"
           "  antenna      Bare RF names also work\n"
           "  states       List RF states, names, and GPIO levels\n"
           "  status       Show both oscillators and RF box\n"
           "  help         Show commands\n"
           "  quit         Power down both, return RF to state 5, and exit\n");
}

static void run_command(const char *line)
{
    char verb[32], arg[128], extra[32];
    int n = sscanf(line, " %31s %127s %31s", verb, arg, extra);
    if (n <= 0) return;

    if (n == 1 && (!strcmp(verb, "quit") || !strcmp(verb, "exit"))) {
        keep_running = 0;
        return;
    }
    if (n == 1 && !strcmp(verb, "help")) { print_help(); return; }
    if (n == 1 && !strcmp(verb, "status")) { print_status(); return; }
    if (n == 1 && !strcmp(verb, "states")) { print_rf_states(); return; }

    /* Read the ENTIRE remainder of the line as a name, including spaces. */
    if (!strcmp(verb, "rf") || !strcmp(verb, "state")) {
        const char *value = line;
        while (isspace((unsigned char)*value)) value++;
        while (*value && !isspace((unsigned char)*value)) value++;
        while (isspace((unsigned char)*value)) value++;
        int state;
        if (parse_rf_state(value, &state) != 0) {
            printf("Invalid RF state. Use 0-7 or a name from 'states'.\n");
            return;
        }
        set_rf_state(state);
        return;
    }

    Oscillator *lo = NULL;
    if (!strcmp(verb, "mixer") || !strcmp(verb, "lo1")) lo = &mixer;
    if (!strcmp(verb, "tone") || !strcmp(verb, "lo2")) lo = &tone;

    if (lo != NULL && n == 2) {
        if (!strcmp(arg, "off")) { turn_off(lo); return; }
        if (!strcmp(arg, "on")) {
            if (lo->power_on) {
                printf("%s is already ON.\n", lo->name);
            } else if (lo->has_frequency) {
                set_frequency(lo, lo->last_mhz);
            } else {
                printf("No previous target for %s. Use '%s <MHz>' first.\n",
                       lo->name, lo == &mixer ? "mixer" : "tone");
            }
            return;
        }
        double mhz;
        if (parse_mhz(arg, &mhz) == 0) {
            set_frequency(lo, mhz);
            return;
        }
    }

    /* Bare 0-7 selects RF state, and bare full names are supported too. */
    if (lo == NULL) {
        int rf_state;
        if (parse_rf_state(line, &rf_state) == 0) {
            set_rf_state(rf_state);
            return;
        }
    }

    printf("Unrecognized command. Type 'help' for examples.\n");
}

int main(int argc, char **argv)
{
    double initial_mhz = 0;
    if (argc > 2 || (argc == 2 && parse_mhz(argv[1], &initial_mhz) != 0)) {
        fprintf(stderr, "Usage: %s [initial_mixer_MHz]\n", argv[0]);
        return 1;
    }
    if (argc == 2) {
        long steps;
        if (frequency_steps(&mixer, initial_mhz, &steps) != 0) return 1;
    }

    if (initialize_gpio() != 0) return 1;
    if (initialize_rf_gpio() != 0) {
        fprintf(stderr, "Could not initialize RF box; powering off oscillators.\n");
        turn_off(&mixer);
        turn_off(&tone);
        gpioTerminate();
        return 1;
    }
    signal(SIGINT, handle_signal);
    signal(SIGTERM, handle_signal);

    printf("High-Z dual oscillator controller\n");
    printf("Mixer: %.1f-%.1f MHz, %.1f MHz steps.\n",
           mixer.min_mhz, mixer.max_mhz, mixer.step_mhz);
    printf("Tone:  %.1f-%.1f MHz, %.1f MHz steps (VERIFY Arduino firmware).\n",
           tone.min_mhz, tone.max_mhz, tone.step_mhz);

    if (argc == 2 && set_frequency(&mixer, initial_mhz) != 0) {
        set_rf_state(RF_SAFE_STATE);
        turn_off(&mixer);
        turn_off(&tone);
        gpioTerminate();
        return 1;
    }

    print_help();
    char line[256];
    while (keep_running) {
        printf("\nEnter command: ");
        fflush(stdout);
        if (fgets(line, sizeof line, stdin) == NULL) {
            if (!keep_running || feof(stdin)) break;
            clearerr(stdin);
            continue;
        }
        run_command(line);
    }

    printf("\nReturning RF box to state %d (%s)...\n",
           RF_SAFE_STATE, rf_names[RF_SAFE_STATE]);
    if (set_rf_state(RF_SAFE_STATE) != 0)
        fprintf(stderr, "WARNING: Could not confirm RF box return to state 5!\n");
    printf("\nShutting down both oscillators...\n");
    turn_off(&mixer);
    turn_off(&tone);
    gpioTerminate();
    printf("GPIO released. Done.\n");
    return 0;
}
