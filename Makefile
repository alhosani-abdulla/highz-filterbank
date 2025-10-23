# Makefile for Highz Filterbank Spectrometer
# Compiles calibration and data acquisition programs

# ============================================================================
# Paths Configuration
# ============================================================================

# AD HAT driver location (now in organized highz directory)
ADHAT_DIR = /home/peterson/highz/High-Precision_AD_HAT/c

# Source directories
SRC_CALIB = src/calibration
SRC_ACQ = src/data_aquisition

# Output directory for binaries
BIN_DIR = bin

# ============================================================================
# Compiler Configuration
# ============================================================================

CC = gcc
CFLAGS = -g -Wall -I$(ADHAT_DIR)/lib/Config -I$(ADHAT_DIR)/lib/Driver

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

# ============================================================================
# Build Rules
# ============================================================================

# Default target - build everything
all: $(BIN_DIR) $(CALIB_TARGET) $(ACQ_TARGET)

# Create bin directory if it doesn't exist
$(BIN_DIR):
	@mkdir -p $(BIN_DIR)
	@echo "Created bin directory"

# Calibration program (filter sweep)
$(CALIB_TARGET): $(SRC_CALIB)/filterSweep.c $(ADHAT_SOURCES)
	@echo "Compiling filter sweep calibration program..."
	$(CC) $(CFLAGS) $^ -o $@ $(LIBS)
	@echo "✓ Calibration binary created: $(CALIB_TARGET)"

# Data acquisition program
$(ACQ_TARGET): $(SRC_ACQ)/continuous_acq.c $(ADHAT_SOURCES)
	@echo "Compiling data acquisition program..."
	$(CC) $(CFLAGS) $^ -o $@ $(LIBS)
	@echo "✓ Data acquisition binary created: $(ACQ_TARGET)"

# ============================================================================
# Utility Targets
# ============================================================================

# Build only calibration
calib: $(BIN_DIR) $(CALIB_TARGET)

# Build only data acquisition
acq: $(BIN_DIR) $(ACQ_TARGET)

# Clean compiled binaries
clean:
	@echo "Cleaning up..."
	@rm -f $(CALIB_TARGET) $(ACQ_TARGET)
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
	@echo "  all       - Build both calibration and data acquisition programs (default)"
	@echo "  calib     - Build only calibration program"
	@echo "  acq       - Build only data acquisition program"
	@echo "  clean     - Remove compiled binaries"
	@echo "  rebuild   - Clean and rebuild everything"
	@echo "  help      - Display this help message"
	@echo ""
	@echo "Usage examples:"
	@echo "  make              # Build everything"
	@echo "  make calib        # Build calibration only"
	@echo "  make clean        # Remove binaries"
	@echo "  make rebuild      # Clean and rebuild"
	@echo ""
	@echo "Output binaries:"
	@echo "  $(CALIB_TARGET)"
	@echo "  $(ACQ_TARGET)"

# ============================================================================
# Phony Targets (not actual files)
# ============================================================================

.PHONY: all calib acq clean rebuild help
