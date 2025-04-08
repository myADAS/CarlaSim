import os
import socket
import psutil
import logging
import time
import numpy as np
import cv2
from pathlib import Path
from CarlaSuite.server import CarlaServerManager
from CarlaSuite.world import CarlaWorldManager
from CarlaSuite.vehicle import CarlaVehicleManager
from CarlaSuite.sensor import CarlaSensorManager
from CarlaSuite.recorder import CarlaRecorder

def is_carla_running():
    """Check if CARLA server is running"""
    for proc in psutil.process_iter(['pid', 'name']):
        try:
            if 'CarlaUE4' in proc.info['name']:
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return False

def is_port_available(port, host='localhost'):
    """Check if the given port is available and responding"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(1)
        result = s.connect_ex((host, port))
        s.close()
        return result == 0
    except:
        return False

def ensure_clean_environment():
    """Kill any existing CARLA processes"""
    try:
        if os.name == 'nt':  # Windows
            # Force kill any existing CARLA processes
            os.system('taskkill /f /im CarlaUE4.exe > nul 2>&1')
            os.system('taskkill /f /im CarlaUE4-Win64-Shipping.exe > nul 2>&1')
            
            # Also check and kill any zombie processes
            for proc in psutil.process_iter(['pid', 'name']):
                try:
                    if 'carla' in proc.name().lower():
                        proc.kill()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
        else:  # Linux/Mac
            os.system('pkill -f CarlaUE4-Linux > /dev/null 2>&1')
        
        # Wait for processes to fully close
        time.sleep(5)  # Increased from 2 to 5 seconds
        
        # Verify cleanup
        for proc in psutil.process_iter(['pid', 'name']):
            try:
                if 'carla' in proc.name().lower():
                    logging.warning(f"CARLA process still running: {proc.name()} (PID: {proc.pid})")
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
                
    except Exception as e:
        logging.error(f"Error during environment cleanup: {str(e)}")

def create_video_from_frames(frames_dir, output_file, fps=20):
    """Create a video from a directory of frames"""
    frames_path = Path(frames_dir)
    if not frames_path.exists():
        logging.error(f"Frames directory {frames_dir} does not exist")
        return False
    
    # Get all frame files
    frame_files = sorted([f for f in frames_path.glob('*.jpg')])
    if not frame_files:
        logging.error(f"No frames found in {frames_dir}")
        return False
    
    # Get frame dimensions from first frame
    first_frame = cv2.imread(str(frame_files[0]))
    height, width, _ = first_frame.shape
    
    # Create video writer
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    video = cv2.VideoWriter(output_file, fourcc, fps, (width, height))
    
    # Add frames to video
    for frame_file in frame_files:
        frame = cv2.imread(str(frame_file))
        video.write(frame)
    
    # Release video writer
    video.release()
    logging.info(f"Video created at {output_file}")
    return True

def visualize_lidar(lidar_points, image=None, width=800, height=600):
    """Visualize LiDAR points, optionally overlaid on an image"""
    # Create blank image if none provided
    if image is None:
        image = np.zeros((height, width, 3), dtype=np.uint8)
    else:
        # Resize image if needed
        if image.shape[0] != height or image.shape[1] != width:
            image = cv2.resize(image, (width, height))
    
    # Filter points (keep only points in front of the vehicle)
    points = lidar_points[lidar_points[:, 0] > 0]
    
    # Project 3D points to 2D image plane
    points_2d = np.zeros((points.shape[0], 2))
    points_2d[:, 0] = points[:, 1] / points[:, 0] * 100 + width / 2
    points_2d[:, 1] = -points[:, 2] / points[:, 0] * 100 + height / 2
    
    # Filter points outside image
    mask = (points_2d[:, 0] >= 0) & (points_2d[:, 0] < width) & \
           (points_2d[:, 1] >= 0) & (points_2d[:, 1] < height)
    points_2d = points_2d[mask].astype(np.int32)
    
    # Color points based on distance
    distances = np.sqrt(np.sum(points[mask, :3]**2, axis=1))
    max_distance = np.max(distances) if distances.size > 0 else 1.0
    
    # Draw points
    for i in range(points_2d.shape[0]):
        # Color based on distance (red=close, blue=far)
        distance = distances[i]
        color = (
            int(255 * (1 - distance / max_distance)),  # B
            0,                                         # G
            int(255 * distance / max_distance)         # R
        )
        cv2.circle(image, (points_2d[i, 0], points_2d[i, 1]), 2, color, -1)
    
    return image

def record_multi_vehicle_data(output_dir, duration=60):
    """Record data from multiple vehicles"""
    try:
        # Connect to running CARLA server
        with CarlaServerManager(port=2000) as server:
            # Set up world manager first with proper settings
            world_manager = CarlaWorldManager(server.client, sync_mode=True)
            
            try:
                # Set up other managers after world is configured
                vehicle_manager = CarlaVehicleManager(server.client, world_manager)
                sensor_manager = CarlaSensorManager(world_manager)
                
                # Create output directory with timestamp
                timestamp = time.strftime("%Y%m%d_%H%M%S")
                output_dir = Path(output_dir) / f"session_{timestamp}"
                output_dir.mkdir(parents=True, exist_ok=True)
                
                # Set weather after world is fully initialized
                try:
                    world_manager.set_weather('Clear')
                except Exception as e:
                    logging.warning(f"Failed to set weather: {str(e)}")
                
                # Spawn vehicles
                vehicle1 = vehicle_manager.spawn_hero_vehicle('main_car')
                vehicle2 = vehicle_manager.spawn_hero_vehicle('secondary_car')
                
                if not vehicle1 or not vehicle2:
                    raise RuntimeError("Failed to spawn hero vehicles")
                
                # Set up autopilot
                vehicle_manager.set_autopilot('main_car', True)
                vehicle_manager.set_autopilot('secondary_car', True)
                
                # Record data
                recorder = CarlaRecorder(server.client, world_manager, vehicle_manager, sensor_manager)
                recorder.start_recording(output_dir)
                
                # Run simulation
                start_time = time.time()
                while time.time() - start_time < duration:
                    world_manager.tick()
                    time.sleep(0.05)  # Prevent busy waiting
                
                # Stop recording
                recorder.stop_recording()
                
                return True
                
            finally:
                # Clean up in reverse order
                sensor_manager.cleanup()
                vehicle_manager.cleanup()
                
    except Exception as e:
        logging.error(f"Error during recording: {str(e)}")
        return False