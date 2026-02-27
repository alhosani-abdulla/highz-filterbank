# Makefile for Highz Filterbank Spectrometer
# Compiles calibration and data acquisition programs

# ============================================================================
# Paths Configuration
# ============================================================================

# AD HAT driver location (now in organized highz directory)
ADHAT_DIR = /home/peterson/highz/High-Precision_AD_HAT/c

# Source directories
SRC_INSTRUMENT = src/instrument

# Output directory for binaries
BIN_DIR = bin

# ============================================================================
# Compiler Configuration
# ============================================================================

CC = gcc
CFLAGS = -g -Wall -I$(ADHAT_DIR)/lib/Config -I$(ADHAT_DIR)/lib/Driver -I./src

# Libraries required for compilation
LIBS = -lgpiod -lcfitsio -lpigpio -lrt -lpthread -lm

# AD HAT driver source files
ADHAT_SOURCES = $(ADHAT_DIR)/lib/Driver/ADS1263.c \
                $(ADHAT_DIR)/lib/Config/DEV_Config.c \
                $(ADHAT_DIR)/lib/Config/RPI_sysfs_gpio.c \
                $(ADHAT_DIR)/lib/Config/dev_hardware_SPI.c

# ============================================================================
# Target Binaries
# ============================================================================

CALIB_TARGET = $(BIN_DIR)/calib
ACQ_TARGET = $(BIN_DIR)/acq
MANUAL_STATE_TARGET = $(BIN_DIR)/state_manual
CYCLE_CTRL_TARGET = $(BIN_DIR)/cycle_control

# ============================================================================
# Build Rules
# ============================================================================

# Default target - build everything
all: $(BIN_DIR) $(CALIB_TARGET) $(ACQ_TARGET) $(MANUAL_STATE_TARGET) $(CYCLE_CTRL_TARGET)

# Create bin directory if it doesn't exist
$(BIN_DIR):
	@mkdir -p $(BIN_DIR)
	@echo "Created bin directory"

# Calibration program (filter sweep)
$(CALIB_TARGET): $(SRC_INSTRUMENT)/filterSweep.c $(ADHAT_SOURCES)
	@echo "Compiling filter sweep calibration program..."
	$(CC) $(CFLAGS) $^ -o $@ $(LIBS)
	@echo "✓ Calibration binary created: $(CALIB_TARGET)"

# Data acquisition program
$(ACQ_TARGET): $(SRC_INSTRUMENT)/continuous_acq.c $(ADHAT_SOURCES)
	@echo "Compiling data acquisition program..."
	$(CC) $(CFLAGS) $^ -o $@ $(LIBS)
	@echo "✓ Data acquisition binary created: $(ACQ_TARGET)"

# Manual state control program (diagnostic tool)
$(MANUAL_STATE_TARGET): $(SRC_INSTRUMENT)/manual_state_ctrl.c
	@echo "Compiling manual state control program..."
	$(CC) $(CFLAGS) $^ -o $@ $(LIBS)
	@echo "✓ Manual state control binary created: $(MANUAL_STATE_TARGET)"

# Automated cycle controller
$(CYCLE_CTRL_TARGET): $(SRC_INSTRUMENT)/cycle_control.c
	@echo "Compiling automated cycle controller..."
	$(CC) $(CFLAGS) $^ -o $@ $(LIBS)
	@echo "✓ Cycle controller binary created: $(CYCLE_CTRL_TARGET)"

# ============================================================================
# Utility Targets
# ============================================================================

# Build only calibration
calib: $(BIN_DIR) $(CALIB_TARGET)

# Build only data acquisition
acq: $(BIN_DIR) $(ACQ_TARGET)

# Build only manual state control
state_manual: $(BIN_DIR) $(MANUAL_STATE_TARGET)

# Build only cycle controller
cycle_control: $(BIN_DIR) $(CYCLE_CTRL_TARGET)

# Clean compiled binaries
clean:
	@echo "Cleaning up..."
	@rm -f $(CALIB_TARGET) $(ACQ_TARGET) $(MANUAL_STATE_TARGET) $(CYCLE_CTRL_TARGET)
	@if [ -d $(BIN_DIR) ] && [ -z "$$(ls -A $(BIN_DIR))" ]; then \
		rm -rf $(BIN_DIR); \
		echo "✓ Removed empty bin directory"; \
	fi
	@echo "✓ Clean complete"

# Clean and rebuild everything
rebuild: clean all

# Display help information
help:
	@echo "Highz Filterbank Spectrometer - Makefile"
	@echo ""
	@echo "Available targets:"
	@echo "  all          - Build all programs (default)"
	@echo "  calib        - Build only calibration program"
	@echo "  acq          - Build only data acquisition program"
	@echo "  state_manual - Build only manual state control (diagnostic)"
	@echo "  cycle_control - Build only automated cycle controller"
	@echo "  clean        - Remove compiled binaries"
	@echo "  rebuild   - Clean and rebuild everything"
	@echo "  help      - Display this help message"
	@echo ""
	@echo "Usage examples:"
	@echo "  make                # Build everything"
	@echo "  make calib          # Build calibration only"
	@echo "  make cycle_control  # Build cycle controller only"
	@echo "  make clean          # Remove binaries"
	@echo "  make rebuild        # Clean and rebuild"
	@echo ""
	@echo "Output binaries:"
	@echo "  $(CALIB_TARGET)"
	@echo "  $(ACQ_TARGET)"
	@echo "  $(MANUAL_STATE_TARGET)"
	@echo "  $(CYCLE_CTRL_TARGET)"
# ============================================================================
# Phony Targets (not actual files)
# ============================================================================

.PHONY: all calib acq state_manual cycle_control clean rebuild help
