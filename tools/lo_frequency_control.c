#include <stdio.h>
#include <stdlib.h>
#include <signal.h>
#include <math.h>
#include <unistd.h>
#include <pigpio.h>

#include "../src/instrument/highz_common.h"

/* Use the same LO settings as continuous_acq.c */
#define FREQ_MIN   ACQ_FREQ_MIN
#define FREQ_MAX   ACQ_FREQ_MAX
#define FREQ_STEP  ACQ_FREQ_STEP

/*
 * Give the Arduino enough time to process each LO change.
 * continuous_acq naturally has a measurement between pulses;
 * this standalone program does not.
 */
#define ARDUINO_STEP_DELAY_US  50000   // 50 ms between frequency steps
#define RESET_LOW_US           10000   // 10 ms reset pulse
#define RESET_SETTLE_US        50000   // 50 ms after reset
#define POWER_SETTLE_US       100000   // 100 ms after power-on

static volatile sig_atomic_t keep_running = 1;


/*---------------------------------------------------------
 * Ctrl+C handler
 *---------------------------------------------------------*/
static void handle_signal(int sig)
{
    (void)sig;
    keep_running = 0;
}


/*---------------------------------------------------------
 * Send one LOW -> HIGH pulse to an Arduino control pin
 *---------------------------------------------------------*/
static void increment_lo_once(void)
{
    /*
     * Arduino programs the LO on the rising edge:
     *
     * HIGH -> LOW
     * wait
     * LOW -> HIGH  <-- Arduino reacts here
     */

    gpioWrite(ACQ_GPIO_FREQ_INCREMENT, 0);
    gpioDelay(DEFAULT_PULSE_LOW_US);

    gpioWrite(ACQ_GPIO_FREQ_INCREMENT, 1);

    /*
     * IMPORTANT:
     * Give Arduino time to program the LO before
     * sending another increment.
     */
    gpioDelay(ARDUINO_STEP_DELAY_US);
}


/*---------------------------------------------------------
 * Initialize Raspberry Pi GPIO pins
 *---------------------------------------------------------*/
static int initialize_lo_gpio(void)
{
    if (gpioInitialise() < 0) {
        fprintf(stderr, "Error: failed to initialize pigpio.\n");
        return -1;
    }

    gpioSetMode(ACQ_GPIO_FREQ_INCREMENT, PI_OUTPUT);
    gpioSetMode(ACQ_GPIO_FREQ_RESET, PI_OUTPUT);
    gpioSetMode(ACQ_GPIO_LO_POWER, PI_OUTPUT);

    /* Control pins idle HIGH */
    gpioWrite(ACQ_GPIO_FREQ_INCREMENT, 1);
    gpioWrite(ACQ_GPIO_FREQ_RESET, 1);

    /* Turn LO board ON */
    gpioWrite(ACQ_GPIO_LO_POWER, 1);

    printf("LO board powered ON.\n");

    /* Give hardware time to power up */
    gpioDelay(POWER_SETTLE_US);

    return 0;
}


/*---------------------------------------------------------
 * Turn LO board off and release GPIO
 *---------------------------------------------------------*/
static void shutdown_lo(void)
{
    printf("\nShutting down LO...\n");

    /*
     * Make sure frequency increment is sitting
     * in its normal idle HIGH state.
     */
    gpioWrite(ACQ_GPIO_FREQ_INCREMENT, 1);


    /*
     * Reset the Arduino frequency controller.
     *
     * Use two reset pulses because the existing
     * filterSweep.c code uses two pulses for a
     * reliable reset back to the initial state.
     */
    for (int i = 0; i < 2; i++) {

        gpioWrite(ACQ_GPIO_FREQ_RESET, 0);
        gpioDelay(10000);  // LOW for 10 ms

        gpioWrite(ACQ_GPIO_FREQ_RESET, 1);
        gpioDelay(5000);   // wait 5 ms
    }

    printf("Frequency controller reset.\n");


    /*
     * Turn the LO board OFF.
     */
    gpioWrite(ACQ_GPIO_LO_POWER, 0);
    gpioDelay(5000);

    printf("LO power OFF.\n");


    /*
     * Release Raspberry Pi GPIO resources.
     */
    gpioTerminate();

    printf("GPIO released.\n");
}


/*---------------------------------------------------------
 * Reset Arduino frequency counter to 650 MHz
 *---------------------------------------------------------*/
static void reset_lo_frequency(void)
{
    printf("Resetting frequency counter to %.1f MHz...\n",
           FREQ_MIN);

    gpioWrite(ACQ_GPIO_FREQ_RESET, 0);
    gpioDelay(RESET_LOW_US);

    gpioWrite(ACQ_GPIO_FREQ_RESET, 1);
    gpioDelay(RESET_SETTLE_US);
}


/*---------------------------------------------------------
 * Move LO to requested frequency
 *---------------------------------------------------------*/
static int set_lo_frequency(double target_mhz)
{
    double raw_steps;
    long steps_from_min;
    double valid_frequency;
    long pulses;

    /*
     * Determine how many 2 MHz steps the target is
     * above 650 MHz.
     */
    raw_steps = (target_mhz - FREQ_MIN) / FREQ_STEP;

    steps_from_min = lround(raw_steps);

    valid_frequency =
        FREQ_MIN + steps_from_min * FREQ_STEP;


    /* Check frequency range */
    if (target_mhz < FREQ_MIN ||
        target_mhz > FREQ_MAX) {

        fprintf(stderr,
                "Error: frequency must be between %.1f and %.1f MHz.\n",
                FREQ_MIN,
                FREQ_MAX);

        return -1;
    }


    /* Check that frequency lies on the 2 MHz grid */
    if (fabs(target_mhz - valid_frequency) > 1e-6) {

        fprintf(stderr,
                "Error: frequency must use %.1f MHz steps.\n",
                FREQ_STEP);

        fprintf(stderr,
                "Examples: 650, 652, 654, 656, ...\n");

        return -1;
    }


    /*
     * First reset Arduino's internal frequency
     * counter back to 650 MHz.
     */
    reset_lo_frequency();

    sleep(1);


    /*
     * IMPORTANT:
     *
     * Reset sets Arduino curFreq = 650 MHz,
     * but does NOT program the actual LO yet.
     *
     * First increment pulse programs 650 MHz.
     *
     * Therefore:
     *
     * pulses = number of steps + 1
     */
    pulses = steps_from_min + 1;


    printf("\n");
    printf("LO Frequency Controller\n");
    printf("-----------------------\n");

    printf("Starting frequency: %.1f MHz\n",
           FREQ_MIN);

    printf("Requested frequency: %.1f MHz\n",
           target_mhz);

    printf("Steps above minimum: %ld\n",
           steps_from_min);

    printf("Sending %ld increment pulses...\n",
           pulses);


    /* Send increment pulses */
    for (long i = 0; i < pulses; i++) {

        if (!keep_running) {
            printf("\nFrequency change interrupted.\n");
            return -1;
        }

        increment_lo_once();
    }


    printf("\n");
    printf("LO should now be at %.1f MHz.\n",
           target_mhz);

    return 0;
}


/*---------------------------------------------------------
 * Main
 *---------------------------------------------------------*/
int main(int argc, char *argv[])
{
    char *endptr = NULL;
    double target_mhz;


    /* User must provide one frequency */
    if (argc != 2) {

        fprintf(stderr,
                "Usage: %s <frequency_MHz>\n",
                argv[0]);

        fprintf(stderr,
                "Example: %s 900\n",
                argv[0]);

        return 1;
    }


    /* Convert command-line input to number */
    target_mhz = strtod(argv[1], &endptr);


    if (endptr == argv[1] ||
        *endptr != '\0' ||
        !isfinite(target_mhz)) {

        fprintf(stderr,
                "Error: '%s' is not a valid frequency.\n",
                argv[1]);

        return 1;
    }




    /* Initialize GPIO and turn LO on */
    if (initialize_lo_gpio() != 0) {

        return 1;
    }

    /*
    * Install our signal handlers AFTER gpioInitialise().
    * pigpio installs its own signal handler during initialization,
    * so ours needs to be installed afterward.
    */
    signal(SIGINT, handle_signal);
    signal(SIGTERM, handle_signal);


    /* Move to requested frequency */
    if (set_lo_frequency(target_mhz) != 0) {

        shutdown_lo();

        return 1;
    }


    printf("\n");
    printf("LO power is ON.\n");
    printf("Frequency will remain fixed.\n");
    printf("Press Ctrl+C when finished.\n");


    /*
     * Nothing changes while we sit here.
     * LO remains powered and at the selected frequency.
     */
    while (keep_running) {

        sleep(1);
    }


    printf("\nTurning LO power OFF...\n");

    shutdown_lo();

    printf("Done.\n");

    return 0;
}