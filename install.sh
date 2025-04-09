#!/bin/bash

# Set terminal colors
RESET="\033[0m"
BOLD="\033[1m"
GREEN="\033[0;32m"
BLUE="\033[0;34m"
YELLOW="\033[0;33m"
CYAN="\033[0;36m"
RED="\033[0;31m"
MAGENTA="\033[0;35m"

# Get terminal width for progress bars (with fallback)
TERM_WIDTH=80
if command -v tput >/dev/null 2>&1; then
  COLS=$(tput cols)
  if [ -n "$COLS" ] && [ "$COLS" -gt 0 ]; then
    TERM_WIDTH=$COLS
  fi
fi
if [ $TERM_WIDTH -gt 100 ]; then
  TERM_WIDTH=100
fi

# Function to display a spinner animation
spinner() {
    local pid=$1
    local message=$2
    local spin='-\|/'
    local i=0
    
    # Print the message first
    echo -n -e "${CYAN}$message${RESET} "
    
    # Use an invisible temp file to coordinate between processes
    local tmpfile=$(mktemp)
    
    # Start a background process to update the spinner
    (
        while [ -f "$tmpfile" ]; do
            echo -n -e "\b${spin:i++%4:1}"
            sleep 0.2
        done
    ) &
    local spinner_pid=$!
    
    # Wait for original process to complete
    wait $pid
    local exit_status=$?
    
    # Stop the spinner
    rm -f "$tmpfile"
    wait $spinner_pid 2>/dev/null
    
    # Print completion status
    echo -e "\b${GREEN}✓${RESET}"
    
    return $exit_status
}

# Function to display a styled message
echo_status() {
    local type=$1
    local message=$2
    
    case $type in
        "info")
            echo -e "${BLUE}INFO:${RESET}    ${CYAN}$message${RESET}"
            ;;
        "success")
            echo -e "${GREEN}SUCCESS:${RESET} ${GREEN}$message${RESET}"
            ;;
        "warning")
            echo -e "${YELLOW}WARNING:${RESET} ${YELLOW}$message${RESET}"
            ;;
        "error")
            echo -e "${RED}ERROR:${RESET}   ${RED}$message${RESET}"
            ;;
        "step")
            echo ""
            echo -e "${MAGENTA}STEP:${RESET}    ${MAGENTA}$message${RESET}"
            echo -e "${MAGENTA}$(printf '%*s' "$TERM_WIDTH" '' | tr ' ' '-')${RESET}"
            ;;
    esac
}

# Function to ask for confirmation
confirm() {
    local message=$1
    local default=${2:-"y"}
    local prompt
    
    if [[ $default == "y" ]]; then
        prompt="$message [Y/n] "
    else
        prompt="$message [y/N] "
    fi
    
    echo -e -n "${YELLOW}$prompt${RESET}"
    read response
    response=${response:-$default}
    
    if [[ $response =~ ^[Yy] ]]; then
        return 0
    else
        return 1
    fi
}

# Function to print a divider
divider() {
    echo -e "${BLUE}$(printf '%*s' "$TERM_WIDTH" '' | tr ' ' '=')${RESET}"
}

# Detect if running as sudo/root and get the real user's home
REAL_USER=$(logname 2>/dev/null || echo $SUDO_USER || echo $USER)
REAL_HOME=$(eval echo ~$REAL_USER)
MINICONDA_PATH="$REAL_HOME/miniconda3"

echo_status "info" "Detected real user: $REAL_USER"
echo_status "info" "Using home directory: $REAL_HOME"
echo_status "info" "Miniconda path: $MINICONDA_PATH"

# Print welcome message
clear
divider
echo ""
echo -e "${GREEN}${BOLD}               CARLA + Conda Installation Script               ${RESET}"
echo -e "${CYAN}${BOLD}          Interactive Installer with Enhanced Visuals          ${RESET}"
echo ""
divider
echo ""

# Wait for user to start
echo_status "info" "This script will install Conda (if not present), create an ADAS environment,"
echo_status "info" "and set up CARLA with all dependencies including libtiff5."
echo ""
confirm "Ready to begin?" || { echo_status "error" "Installation cancelled."; exit 1; }

# Install libtiff5 packages
echo_status "step" "Installing libtiff5 packages"

if [[ -f "./libtiff5_4.3.0-6ubuntu0.10_amd64.deb" && 
      -f "./libtiffxx5_4.3.0-6ubuntu0.10_amd64.deb" && 
      -f "./libtiff5-dev_4.3.0-6ubuntu0.10_amd64.deb" ]]; then
    echo_status "info" "libtiff5 packages already downloaded."
else
    echo_status "info" "Downloading libtiff5 packages..."
    wget --show-progress http://security.ubuntu.com/ubuntu/pool/main/t/tiff/libtiff5_4.3.0-6ubuntu0.10_amd64.deb \
         http://mirrors.kernel.org/ubuntu/pool/main/t/tiff/libtiffxx5_4.3.0-6ubuntu0.10_amd64.deb \
         http://security.ubuntu.com/ubuntu/pool/main/t/tiff/libtiff5-dev_4.3.0-6ubuntu0.10_amd64.deb &
    spinner $! "Downloading libtiff5 packages"
fi

echo_status "info" "Installing libtiff5 packages..."
sudo apt install -y ./libtiff5_4.3.0-6ubuntu0.10_amd64.deb \
                    ./libtiffxx5_4.3.0-6ubuntu0.10_amd64.deb \
                    ./libtiff5-dev_4.3.0-6ubuntu0.10_amd64.deb > /dev/null 2>&1 &
spinner $! "Installing libtiff5 packages"

# Check if conda is already installed
echo_status "step" "Checking Conda installation"

# Check for existing conda installations in user's home directory
if [ -d "$MINICONDA_PATH" ] || command -v conda >/dev/null 2>&1; then
    echo_status "success" "Found existing Conda installation."
    
    # Try to initialize conda
    if [ -f "$MINICONDA_PATH/etc/profile.d/conda.sh" ]; then
        echo_status "info" "Initializing conda from $MINICONDA_PATH..."
        source "$MINICONDA_PATH/etc/profile.d/conda.sh"
    elif command -v conda >/dev/null 2>&1; then
        echo_status "info" "Conda is in PATH, trying to initialize..."
        # Try to find conda.sh
        CONDA_PREFIX=$(conda info --base 2>/dev/null)
        if [ -n "$CONDA_PREFIX" ] && [ -f "$CONDA_PREFIX/etc/profile.d/conda.sh" ]; then
            source "$CONDA_PREFIX/etc/profile.d/conda.sh"
        fi
    fi
    
    # Verify conda is working now
    if ! command -v conda >/dev/null 2>&1; then
        echo_status "error" "Conda found but not accessible. Please check your installation."
        exit 1
    else
        echo_status "success" "Conda initialized and ready to use."
        INSTALL_CONDA=false
    fi
else
    echo_status "info" "Conda not found. Preparing to install..."
    INSTALL_CONDA=true
fi

# Install conda if needed
if [ "$INSTALL_CONDA" = true ]; then
    # Install Miniconda in user's home directory
    echo_status "info" "Installing Miniconda in $REAL_USER's home directory"
    
    # Create miniconda directory first (with appropriate permissions)
    mkdir -p "$MINICONDA_PATH"
    if [ "$USER" = "root" ]; then
        chown $REAL_USER:$REAL_USER "$MINICONDA_PATH"
    fi
    
    echo_status "info" "Downloading Miniconda installer..."
    INSTALLER_PATH="$REAL_HOME/miniconda_installer.sh"
    wget --show-progress -O "$INSTALLER_PATH" https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh &
    spinner $! "Downloading Miniconda installer"
    
    # Set appropriate permissions for the installer
    if [ "$USER" = "root" ]; then
        chown $REAL_USER:$REAL_USER "$INSTALLER_PATH"
    fi
    
    echo_status "info" "Installing Miniconda..."
    if [ "$USER" = "root" ]; then
        # Run as the real user if we're root
        su - $REAL_USER -c "bash $INSTALLER_PATH -b -u -p $MINICONDA_PATH" > /dev/null 2>&1 &
    else
        bash "$INSTALLER_PATH" -b -u -p "$MINICONDA_PATH" > /dev/null 2>&1 &
    fi
    spinner $! "Installing Miniconda"
    
    # Clean up installer
    rm -f "$INSTALLER_PATH"
    
    # Initialize conda
    echo_status "info" "Initializing conda..."
    if [ "$USER" = "root" ]; then
        su - $REAL_USER -c "$MINICONDA_PATH/bin/conda init bash" > /dev/null 2>&1 &
    else
        "$MINICONDA_PATH/bin/conda" init bash > /dev/null 2>&1 &
    fi
    spinner $! "Initializing conda"
    
    # Source conda.sh
    if [ -f "$MINICONDA_PATH/etc/profile.d/conda.sh" ]; then
        source "$MINICONDA_PATH/etc/profile.d/conda.sh"
    fi
    
    # Add to PATH for this session
    export PATH="$MINICONDA_PATH/bin:$PATH"
    
    echo_status "success" "Conda installed and initialized successfully."
    echo_status "info" "For future sessions, you may need to run: source ~/.bashrc"
    
    # Verify conda is working
    if ! command -v conda >/dev/null 2>&1; then
        echo_status "error" "Conda was installed but is not accessible. Try running the script without sudo."
        exit 1
    fi
fi

# Function to run conda commands (as real user if needed)
run_conda_command() {
    command=$1
    message=$2
    
    if [ "$USER" = "root" ]; then
        # Run as the real user if we're root
        su - $REAL_USER -c "source $MINICONDA_PATH/etc/profile.d/conda.sh && $command" > /dev/null 2>&1 &
    else
        eval "$command" > /dev/null 2>&1 &
    fi
    spinner $! "$message"
}

# Check if ADAS environment already exists
echo_status "step" "Setting up ADAS conda environment"

if conda env list | grep -q "ADAS"; then
    echo_status "info" "ADAS environment already exists."
    
    if confirm "Would you like to recreate the ADAS environment? (This will delete the existing one)" "n"; then
        echo_status "warning" "Removing existing ADAS environment..."
        run_conda_command "conda env remove -n ADAS -y" "Removing existing ADAS environment"
        
        echo_status "info" "Creating fresh ADAS environment..."
        run_conda_command "conda create -n ADAS python=3.8 -y" "Creating ADAS environment"
    else
        echo_status "info" "Using existing ADAS environment."
    fi
else
    # Create environment
    echo_status "info" "Creating conda environment 'ADAS'..."
    run_conda_command "conda create -n ADAS python=3.8 -y" "Creating ADAS environment"
fi

# Activate the environment
echo_status "info" "Activating ADAS environment..."
if [ "$USER" = "root" ]; then
    # For sudo sessions, we'll use a slightly different approach
    source "$MINICONDA_PATH/etc/profile.d/conda.sh" 2>/dev/null
    conda activate ADAS 2>/dev/null || { 
        echo_status "warning" "Cannot fully activate ADAS environment as root user."
        echo_status "warning" "Will continue installation but some steps may need manual intervention later."
    }
else
    conda activate ADAS || { 
        echo_status "warning" "Failed to activate with conda activate. Trying alternative method..."
        source activate ADAS || {
            echo_status "error" "Failed to activate ADAS environment. Script will continue but may have issues."
        }
    }
fi
echo_status "success" "ADAS environment prepared."

# Install required packages - use run_conda_command
echo_status "step" "Installing required packages"

echo_status "info" "Installing conda packages..."
run_conda_command "conda activate ADAS && conda install -c conda-forge libstdcxx-ng -y" "Installing conda packages"

echo_status "info" "Installing pip packages..."
run_conda_command "conda activate ADAS && pip install future numpy pygame matplotlib open3d Pillow" "Installing pip packages"

# Install system dependencies
echo_status "step" "Installing system dependencies"

echo_status "info" "Updating package list..."
sudo apt-get update > /dev/null 2>&1 &
spinner $! "Updating package list"

echo_status "info" "Installing system dependencies..."
sudo apt-get install -y libtiff5 > /dev/null 2>&1 &
spinner $! "Installing system dependencies"

# Check if CARLA folder already exists
echo_status "step" "Setting up CARLA"

if [ -d "carla" ]; then
    echo_status "info" "CARLA folder already exists."
    if confirm "Would you like to reinstall CARLA? (This will replace the existing installation)" "n"; then
        echo_status "warning" "Removing existing CARLA installation..."
        rm -rf carla
        INSTALL_CARLA=true
    else
        echo_status "info" "Keeping existing CARLA installation."
        INSTALL_CARLA=false
    fi
else
    INSTALL_CARLA=true
fi

if [ "$INSTALL_CARLA" = true ]; then
    # Download and extract CARLA and additional maps
    echo_status "info" "Downloading CARLA..."
    wget --show-progress -O CARLA_Latest.tar.gz https://carla-releases.s3.us-east-005.backblazeb2.com/Linux/Dev/CARLA_Latest.tar.gz &
    spinner $! "Downloading CARLA"
    
    echo_status "info" "Downloading additional maps..."
    wget --show-progress -O AdditionalMaps_Latest.tar.gz https://carla-releases.s3.us-east-005.backblazeb2.com/Linux/Dev/AdditionalMaps_Latest.tar.gz &
    spinner $! "Downloading additional maps"
    
    echo_status "info" "Creating CARLA directory..."
    mkdir -p carla
    
    echo_status "info" "Extracting CARLA files (this may take a while)..."
    tar -xzf CARLA_Latest.tar.gz -C carla > /dev/null 2>&1 &
    spinner $! "Extracting CARLA files"
    
    echo_status "info" "Moving additional maps to CARLA Import directory..."
    mv AdditionalMaps_Latest.tar.gz carla/Import/
    
    echo_status "info" "Importing additional maps using ImportAssets.sh..."
    (cd carla && ./ImportAssets.sh) > /dev/null 2>&1 &
    spinner $! "Importing additional maps"
    
    echo_status "info" "Cleaning up downloaded archives..."
    rm -f CARLA_Latest.tar.gz
    
    echo_status "success" "CARLA extraction and map import complete."
    
    # Ensure proper permissions if running as root
    if [ "$USER" = "root" ]; then
        echo_status "info" "Setting proper permissions for CARLA directory..."
        chown -R $REAL_USER:$REAL_USER carla
    fi
fi

# Check if CARLA Python API is already installed
echo_status "step" "Installing CARLA Python API"

# Need to run pip list through the run_conda_command function
CARLA_ALREADY_INSTALLED=false
if [ "$USER" = "root" ]; then
    if su - $REAL_USER -c "source $MINICONDA_PATH/etc/profile.d/conda.sh && conda activate ADAS && pip list | grep -q carla"; then
        CARLA_ALREADY_INSTALLED=true
    fi
else
    if pip list | grep -q "carla"; then
        CARLA_ALREADY_INSTALLED=true
    fi
fi

if [ "$CARLA_ALREADY_INSTALLED" = true ]; then
    echo_status "info" "CARLA Python API already installed."
    if confirm "Would you like to reinstall the CARLA Python API?" "n"; then
        echo_status "info" "Reinstalling CARLA Python API..."
        run_conda_command "conda activate ADAS && pip install $(pwd)/carla/PythonAPI/carla/dist/carla-0.9.15-cp38-cp38-linux_x86_64.whl" "Reinstalling CARLA Python API"
    fi
else
    # Install CARLA Python API - only if carla directory exists
    if [ -d "carla" ] && [ -f "carla/PythonAPI/carla/dist/carla-0.9.15-cp38-cp38-linux_x86_64.whl" ]; then
        echo_status "info" "Installing CARLA Python API..."
        run_conda_command "conda activate ADAS && pip install $(pwd)/carla/PythonAPI/carla/dist/carla-0.9.15-cp38-cp38-linux_x86_64.whl" "Installing CARLA Python API"
    else
        echo_status "error" "CARLA Python wheel not found. Cannot install Python API."
    fi
fi

# Final message
echo_status "step" "Installation complete"

# Print a fancy completion message
divider
echo ""
echo -e "${GREEN}${BOLD}                    🎉 Installation Complete! 🎉                    ${RESET}"
echo ""
echo_status "success" "CARLA and all dependencies have been installed successfully."
echo_status "info" "To use CARLA, activate the ADAS environment with: conda activate ADAS"
echo_status "info" "Then run CARLA from the carla directory."
echo ""
divider

# Ask if user wants to start CARLA now
if confirm "Would you like to start CARLA now?" "n"; then
    echo_status "info" "Starting CARLA..."
    if [ "$USER" = "root" ]; then
        su - $REAL_USER -c "cd $(pwd)/carla && ./CarlaUE4.sh"
    else
        cd carla && ./CarlaUE4.sh
    fi
fi