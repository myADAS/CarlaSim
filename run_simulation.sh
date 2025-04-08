#!/bin/bash

# Configuration
RECORDING_TIME=1800  # 30 minutes in seconds
COVERAGE_THRESHOLD=85.0  # Stop at 85% coverage
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

# Function to monitor simulation progress
monitor_simulation() {
    local session_dir="$1"
    local start_time=$(date +%s)
    local coverage=0.0
    local last_progress_time=$(date +%s)
    local stall_duration=0
    local last_coverage=0.0
    
    echo "Monitoring simulation progress..."
    
    while true; do
        # Check if coverage file exists and read it
        if [ -f "current_coverage.txt" ]; then
            coverage=$(cat current_coverage.txt)
            
            # Update progress
            current_time=$(date +%s)
            elapsed=$((current_time - start_time))
            
            # Check for completion conditions
            if (( $(echo "$coverage >= $COVERAGE_THRESHOLD" | bc -l) )); then
                echo "Coverage threshold reached: $coverage%"
                echo "Final coverage: $coverage%" >> "$session_dir/completion_info.txt"
                echo "Time taken: $elapsed seconds" >> "$session_dir/completion_info.txt"
                return 0
            fi
            
            # Check for progress stall
            if (( $(echo "$coverage == $last_coverage" | bc -l) )); then
                stall_duration=$((current_time - last_progress_time))
                if [ $stall_duration -gt 300 ]; then  # 5 minutes stall
                    echo "Simulation stalled (no progress for 5 minutes)"
                    echo "Stalled at coverage: $coverage%" >> "$session_dir/completion_info.txt"
                    echo "Time taken: $elapsed seconds" >> "$session_dir/completion_info.txt"
                    return 1
                fi
            else
                last_progress_time=$current_time
                last_coverage=$coverage
                stall_duration=0
            fi
            
            # Check for timeout
            if [ $elapsed -ge $RECORDING_TIME ]; then
                echo "Time limit reached"
                echo "Final coverage: $coverage%" >> "$session_dir/completion_info.txt"
                echo "Time taken: $elapsed seconds (time limit reached)" >> "$session_dir/completion_info.txt"
                return 2
            fi
        fi
        
        sleep 5
    done
}

# Create results directory
RESULTS_DIR="simulation_results_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$RESULTS_DIR"

# Create summary file
SUMMARY_FILE="$RESULTS_DIR/summary.csv"
echo "Map,Weather,Vehicles,Coverage,Time,Status" > "$SUMMARY_FILE"

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
            echo "  Coverage threshold: $COVERAGE_THRESHOLD%"
            echo "  Max time: $RECORDING_TIME seconds"
            
            # Run the simulation in background
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
                --coverage "$COVERAGE_THRESHOLD" \
                > "$SESSION_DIR/simulation.log" 2>&1 &
            
            # Store the PID
            SIM_PID=$!
            
            # Monitor the simulation
            monitor_simulation "$SESSION_DIR"
            MONITOR_STATUS=$?
            
            # Kill the simulation if it's still running
            if kill -0 $SIM_PID 2>/dev/null; then
                kill $SIM_PID
                sleep 2
                # Force kill if still running
                kill -9 $SIM_PID 2>/dev/null || true
            fi
            
            # Get final coverage
            FINAL_COVERAGE=0
            if [ -f "current_coverage.txt" ]; then
                FINAL_COVERAGE=$(cat current_coverage.txt)
            fi
            
            # Determine status
            case $MONITOR_STATUS in
                0) STATUS="Coverage reached" ;;
                1) STATUS="Stalled" ;;
                2) STATUS="Time limit" ;;
                *) STATUS="Unknown" ;;
            esac
            
            # Add to summary
            echo "$map_name,$weather,$vehicles,$FINAL_COVERAGE,$(cat "$SESSION_DIR/completion_info.txt" | grep "Time taken" | cut -d' ' -f3),$STATUS" >> "$SUMMARY_FILE"
            
            # Remove coverage file
            rm -f current_coverage.txt
            
            # Add a small delay between simulations
            sleep 5
        done
    done
done

echo "All simulations completed. Results are in: $RESULTS_DIR"
echo "Summary available in: $SUMMARY_FILE" 