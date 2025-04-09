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
            echo -e "\n${MAGENTA}STEP:${RESET}    ${MAGENTA}$message${RESET}"
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

# Check if conda is already installed
echo_status "step" "Checking Conda installation"

# Comprehensive check for existing conda installations
if command -v conda >/dev/null 2>&1 || 
   [ -d "$HOME/miniconda3" ] || 
   [ -d "$HOME/anaconda3" ] || 
   [ -d "$HOME/.conda" ] || 
   [ -f "$HOME/.bashrc" ] && grep -q "conda initialize" "$HOME/.bashrc"; then
    
    echo_status "success" "Conda is already installed."
    
    # Try to find and source conda initialization script
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
            # Try to find the conda executable
            CONDA_BIN=$(find "$HOME" -name conda -type f -executable 2>/dev/null | head -n 1)
            if [ -n "$CONDA_BIN" ]; then
                echo_status "info" "Found conda executable at $CONDA_BIN"
                CONDA_DIR=$(dirname "$CONDA_BIN")
                echo_status "info" "Adding $CONDA_DIR to PATH"
                export PATH="$CONDA_DIR:$PATH"
                
                # Initialize conda
                "$CONDA_BIN" init bash > /dev/null 2>&1
                
                if [ -f "$HOME/.bashrc" ]; then
                    source "$HOME/.bashrc"
                fi
            else
                echo_status "error" "Unable to find conda initialization script or executable."
                echo_status "warning" "Your conda installation might be incomplete or not in PATH."
                
                if confirm "Would you like to install Miniconda in your home directory?" "y"; then
                    INSTALL_CONDA=true
                else
                    echo_status "error" "Cannot proceed without working conda. Exiting."
                    exit 1
                fi
            fi
        fi
    fi
    
    # Verify conda is working
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
    mkdir -p ~/miniconda3
    wget -O ~/miniconda3/miniconda.sh https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh
    
    echo_status "info" "Installing Miniconda..."
    bash ~/miniconda3/miniconda.sh -b -u -p ~/miniconda3
    
    rm ~/miniconda3/miniconda.sh
    
    # Initialize conda
    echo_status "info" "Initializing conda..."
    source ~/miniconda3/bin/activate
    ~/miniconda3/bin/conda init bash
    
    # Add conda to PATH for this session
    export PATH="$HOME/miniconda3/bin:$PATH"
    
    # Add conda to PATH permanently in .bashrc
    if ! grep -q "export PATH=\"\$HOME/miniconda3/bin:\$PATH\"" ~/.bashrc; then
        echo 'export PATH="$HOME/miniconda3/bin:$PATH"' >> ~/.bashrc
    fi
    
    echo_status "success" "Conda installed and initialized successfully."
    echo_status "info" "For future sessions, you may need to run: source ~/.bashrc"
fi

echo_status "success" "Conda setup complete!" 