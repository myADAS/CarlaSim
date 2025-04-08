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

# Check if conda is already installed - IMPROVED VERSION
echo_status "step" "Checking Conda installation"

# More comprehensive check for existing conda installations
if command -v conda >/dev/null 2>&1 || 
   [ -d "$HOME/miniconda3" ] || 
   [ -d "$HOME/anaconda3" ] || 
   [ -d "$HOME/.conda" ] || 
   [ -f "$HOME/.bashrc" ] && grep -q "conda initialize" "$HOME/.bashrc"; then
    
    echo_status "success" "Conda is already installed."
    
    # Try to find and source conda initialization script from multiple locations
    if [ -f "$HOME/miniconda3/etc/profile.d/conda.sh" ]; then
        echo_status "info" "Initializing conda from $HOME/miniconda3"
        source "$HOME/miniconda3/etc/profile.d/conda.sh"
    elif [ -f "$HOME/anaconda3/etc/profile.d/conda.sh" ]; then
        echo_status "info" "Initializing conda from $HOME/anaconda3"
        source "$HOME/anaconda3/etc/profile.d/conda.sh"
    elif [ -f "/opt/conda/etc/profile.d/conda.sh" ]; then
        echo_status "info" "Initializing conda from /opt/conda"
        source "/opt/conda/etc/profile.d/conda.sh"
    else
        echo_status "warning" "Conda installation found but initialization script not found. Searching..."
        CONDA_SH=$(find "$HOME" -name conda.sh 2>/dev/null | head -n 1)
        if [ -n "$CONDA_SH" ]; then
            echo_status "info" "Found conda.sh at $CONDA_SH"
            source "$CONDA_SH"
        else
            # Try to find the conda executable and add its directory to PATH
            CONDA_BIN=$(find "$HOME" -name conda -type f -executable 2>/dev/null | head -n 1)
            if [ -n "$CONDA_BIN" ]; then
                echo_status "info" "Found conda executable at $CONDA_BIN"
                CONDA_DIR=$(dirname "$CONDA_BIN")
                echo_status "info" "Adding $CONDA_DIR to PATH"
                export PATH="$CONDA_DIR:$PATH"
                
                # Try to initialize conda with the found executable
                "$CONDA_BIN" init bash > /dev/null 2>&1
                
                # Source the bashrc to get the initialization
                if [ -f "$HOME/.bashrc" ]; then
                    source "$HOME/.bashrc"
                fi
            else
                echo_status "error" "Unable to find conda initialization script or executable."
                echo_status "warning" "Your conda installation might be incomplete or not in PATH."
                
                if confirm "Would you like to install Miniconda in your home directory?" "y"; then
                    # Proceed with fresh installation in home directory
                    INSTALL_CONDA=true
                else
                    echo_status "error" "Cannot proceed without working conda. Exiting."
                    exit 1
                fi
            fi
        fi
    fi
    
    # Verify conda is actually working now
    if ! command -v conda >/dev/null 2>&1; then
        echo_status "error" "Conda is still not accessible after initialization attempts."
        
        if confirm "Would you like to install a fresh copy of Miniconda in your home directory?" "y"; then
            INSTALL_CONDA=true
        else
            echo_status "error" "Cannot proceed without working conda. Exiting."
            exit 1
        fi
    else
        echo_status "success" "Conda is now initialized and ready to use."
        INSTALL_CONDA=false
    fi
else
    echo_status "info" "Conda not found. Preparing to install..."
    INSTALL_CONDA=true
fi

# Install conda if needed
if [ "$INSTALL_CONDA" = true ]; then
    # Install Miniconda in home directory
    echo_status "info" "Installing conda in your home directory at ~/miniconda3"
    
    echo_status "info" "Downloading Miniconda installer..."
    wget --show-progress -O ~/miniconda3/miniconda.sh https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh &
    spinner $! "Downloading Miniconda installer"
    
    echo_status "info" "Installing Miniconda..."
    bash ~/miniconda3/miniconda.sh -b -u -p ~/miniconda3 > /dev/null 2>&1 &
    spinner $! "Installing Miniconda"
    
    rm ~/miniconda3/miniconda.sh
    
    # Initialize conda
    echo_status "info" "Initializing conda..."
    source ~/miniconda3/bin/activate
    ~/miniconda3/bin/conda init bash > /dev/null 2>&1 &
    spinner $! "Initializing conda"
    
    # Add conda to PATH for this session
    export PATH="$HOME/miniconda3/bin:$PATH"
    
    # Add conda to PATH permanently in .bashrc
    if ! grep -q "export PATH=\"\$HOME/miniconda3/bin:\$PATH\"" ~/.bashrc; then
        echo 'export PATH="$HOME/miniconda3/bin:$PATH"' >> ~/.bashrc
    fi
    
    echo_status "success" "Conda installed and initialized successfully."
    echo_status "info" "For future sessions, you may need to run: source ~/.bashrc"
fi

# Check if ADAS environment already exists
echo_status "step" "Setting up ADAS conda environment"

if conda env list | grep -q "ADAS"; then
    echo_status "info" "ADAS environment already exists."
    
    if confirm "Would you like to recreate the ADAS environment? (This will delete the existing one)" "n"; then
        echo_status "warning" "Removing existing ADAS environment..."
        conda env remove -n ADAS -y > /dev/null 2>&1 &
        spinner $! "Removing existing ADAS environment"
        
        echo_status "info" "Creating fresh ADAS environment..."
        conda create -n ADAS python=3.8 -y > /dev/null 2>&1 &
        spinner $! "Creating ADAS environment"
    else
        echo_status "info" "Using existing ADAS environment."
    fi
else
    # Create environment
    echo_status "info" "Creating conda environment 'ADAS'..."
    conda create -n ADAS python=3.8 -y > /dev/null 2>&1 &
    spinner $! "Creating ADAS environment"
fi

# Activate the environment
echo_status "info" "Activating ADAS environment..."
conda activate ADAS || { echo_status "error" "Failed to activate ADAS environment."; exit 1; }
echo_status "success" "ADAS environment activated."

# Install required packages
echo_status "step" "Installing required packages"

echo_status "info" "Installing conda packages..."
conda install -c conda-forge libstdcxx-ng -y > /dev/null 2>&1 &
spinner $! "Installing conda packages"

echo_status "info" "Installing pip packages..."
pip install future numpy pygame matplotlib open3d Pillow > /dev/null 2>&1 &
spinner $! "Installing pip packages"

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
    
    echo_status "info" "Extracting additional maps..."
    tar -xzf AdditionalMaps_Latest.tar.gz -C carla > /dev/null 2>&1 &
    spinner $! "Extracting additional maps"
    
    echo_status "info" "Cleaning up downloaded archives..."
    rm CARLA_Latest.tar.gz AdditionalMaps_Latest.tar.gz
    
    echo_status "success" "CARLA extraction complete."
fi

# Check if CARLA Python API is already installed
echo_status "step" "Installing CARLA Python API"

if pip list | grep -q "carla"; then
    echo_status "info" "CARLA Python API already installed."
    if confirm "Would you like to reinstall the CARLA Python API?" "n"; then
        echo_status "info" "Reinstalling CARLA Python API..."
        pip install  carla/PythonAPI/carla/dist/carla-0.9.15-cp38-cp38-linux_x86_64.whl > /dev/null 2>&1 &
        spinner $! "Reinstalling CARLA Python API"
    fi
else
    # Install CARLA Python API
    echo_status "info" "Installing CARLA Python API..."
    pip install carla/PythonAPI/carla/dist/carla-0.9.15-cp38-cp38-linux_x86_64.whl > /dev/null 2>&1 &
    spinner $! "Installing CARLA Python API"
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
    cd carla && ./CarlaUE4.sh
fi
