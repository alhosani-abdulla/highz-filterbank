/*
 * Interactive controller for the High-Z filterbank's two local oscillators.
 *
 * Mixer LO: GPIO 4 (increment), 5 (reset), 6 (power)
 * Tone  LO: GPIO 13 (increment), 19 (reset), 26 (power)
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

static volatile sig_atomic_t keep_running = 1;

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
}

static void print_help(void)
{
    printf("\nCommands:\n"
           "  800          Set mixer LO to 800 MHz (old behavior)\n"
           "  mixer 800    Set mixer LO to 800 MHz\n"
           "  tone 930     Set calibration/tone LO to 930 MHz\n"
           "  mixer off    Switch mixer LO OFF\n"
           "  tone off     Switch calibration/tone LO OFF\n"
           "  mixer on     Restore last mixer target after OFF\n"
           "  tone on      Restore last tone target after OFF\n"
           "  status       Show both oscillator states\n"
           "  help         Show commands\n"
           "  quit         Power down both and exit (Ctrl+C also works)\n");
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

    /* Preserve the original interactive shorthand: a number sets mixer. */
    if (n == 1) {
        double mhz;
        if (parse_mhz(verb, &mhz) == 0) {
            set_frequency(&mixer, mhz);
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
    signal(SIGINT, handle_signal);
    signal(SIGTERM, handle_signal);

    printf("High-Z dual oscillator controller\n");
    printf("Mixer: %.1f-%.1f MHz, %.1f MHz steps.\n",
           mixer.min_mhz, mixer.max_mhz, mixer.step_mhz);
    printf("Tone:  %.1f-%.1f MHz, %.1f MHz steps (VERIFY Arduino firmware).\n",
           tone.min_mhz, tone.max_mhz, tone.step_mhz);

    if (argc == 2 && set_frequency(&mixer, initial_mhz) != 0) {
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

    printf("\nShutting down both oscillators...\n");
    turn_off(&mixer);
    turn_off(&tone);
    gpioTerminate();
    printf("GPIO released. Done.\n");
    return 0;
}
