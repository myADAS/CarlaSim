#!/bin/bash

# Configuration
RECORDING_TIME=1800  # 30 minutes in seconds
HOST="127.0.0.1"
PORT=2000
RESOLUTION="1280x720"

# Arrays of parameters to iterate through
WEATHER_CONDITIONS=(
    "Clear Night" "Clear Noon" "Clear Sunset"
    "Cloudy Night" "Cloudy Noon" "Cloudy Sunset"
    "Default" "Dust Storm"
    "Hard Rain Night" "Hard Rain Noon" "Hard Rain Sunset"
    "Mid Rain Sunset" "Mid Rainy Night" "Mid Rainy Noon"
    "Soft Rain Night" "Soft Rain Noon" "Soft Rain Sunset"
    "Wet Cloudy Night" "Wet Cloudy Noon" "Wet Cloudy Sunset"
    "Wet Night" "Wet Noon" "Wet Sunset"
)

VEHICLE_COUNTS=(0 10 25 50 100)

# Function to get available maps
get_available_maps() {
    python3 -c "
import carla
client = carla.Client('$HOST', $PORT)
client.set_timeout(10.0)
print('\n'.join(client.get_available_maps()))
"
}

# Create results directory
RESULTS_DIR="simulation_results_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$RESULTS_DIR"

# Get available maps
echo "Fetching available maps..."
MAPS=($(get_available_maps))

# Main simulation loop
for map in "${MAPS[@]}"; do
    map_name=$(basename "$map" .xodr)
    echo "Processing map: $map_name"
    
    for weather in "${WEATHER_CONDITIONS[@]}"; do
        for vehicles in "${VEHICLE_COUNTS[@]}"; do
            # Create session directory
            SESSION_DIR="$RESULTS_DIR/${map_name}_${weather// /_}_${vehicles}vehicles"
            mkdir -p "$SESSION_DIR"
            
            echo "Starting simulation:"
            echo "  Map: $map_name"
            echo "  Weather: $weather"
            echo "  Vehicles: $vehicles"
            echo "  Recording time: $RECORDING_TIME seconds"
            
            # Run the simulation
            python3 og_manual.py \
                --host "$HOST" \
                --port "$PORT" \
                --res "$RESOLUTION" \
                --sync \
                --autopilot \
                --map "$map_name" \
                --weather "$weather" \
                --vehicles "$vehicles" \
                --record \
                --timer "$RECORDING_TIME" \
                --timer-quit \
                --traverse-map \
                > "$SESSION_DIR/simulation.log" 2>&1
            
            # Check if simulation completed successfully
            if [ $? -eq 0 ]; then
                echo "Simulation completed successfully"
            else
                echo "Simulation encountered an error"
            fi
            
            # Add a small delay between simulations
            sleep 5
        done
    done
done

echo "All simulations completed. Results are in: $RESULTS_DIR"
