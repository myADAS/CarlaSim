import carla
import logging
import os
import csv
import time
import threading
import numpy as np
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any

class CarlaRecorder:
    """Coordinates recording from multiple vehicles in CARLA"""
    
    def __init__(self, client: carla.Client, world_manager, vehicle_manager, sensor_manager):
        """
        Initialize the recorder
        
        Args:
            client: Connected CARLA client
            world_manager: CarlaWorldManager instance
            vehicle_manager: CarlaVehicleManager instance
            sensor_manager: CarlaSensorManager instance
        """
        self.client = client
        self.world = client.get_world()
        self.world_manager = world_manager
        self.vehicle_manager = vehicle_manager
        self.sensor_manager = sensor_manager
        
        # Set up synchronous mode
        settings = self.world.get_settings()
        settings.synchronous_mode = True
        settings.fixed_delta_seconds = 0.05  # 20 FPS
        self.world.apply_settings(settings)
        
        # Recording state
        self.recording = False
        self.output_dir = None
        self.vehicle_data = {}  # name -> {csv_file, csv_writer, frame_count}
        
        # Threading
        self.stop_event = threading.Event()
        self.processing_threads = {}
    
    def setup_recording_vehicle(self, vehicle_name: str, sensors_config: Dict[str, Dict]):
        """
        Set up a vehicle for recording with specified sensors
        
        Args:
            vehicle_name: Name of the hero vehicle
            sensors_config: Dictionary of sensor configurations
                {
                    'rgb': {'position': (1.5, 0, 2.4), 'width': 1280, ...},
                    'depth': {...},
                    'lidar': {...}
                }
        """
        # Get vehicle
        vehicle = self.vehicle_manager.get_hero_vehicle(vehicle_name)
        if not vehicle:
            logging.error(f"Vehicle '{vehicle_name}' not found")
            return False
        
        # Set up sensors
        for sensor_type, config in sensors_config.items():
            if sensor_type in ['rgb', 'depth', 'semantic_segmentation']:
                self.sensor_manager.setup_camera(
                    vehicle, 
                    camera_type=sensor_type,
                    position=config.get('position', (1.5, 0, 2.4)),
                    rotation=config.get('rotation', (0, 0, 0)),
                    width=config.get('width', 1280),
                    height=config.get('height', 720),
                    fov=config.get('fov', 90.0)
                )
            elif sensor_type == 'lidar':
                self.sensor_manager.setup_lidar(
                    vehicle,
                    position=config.get('position', (0, 0, 2.4)),
                    rotation=config.get('rotation', (0, 0, 0)),
                    points_per_second=config.get('points_per_second', 100000),
                    channels=config.get('channels', 32),
                    range=config.get('range', 100.0)
                )
            elif sensor_type == 'collision':
                self.sensor_manager.setup_collision_sensor(vehicle)
            elif sensor_type == 'lane_invasion':
                self.sensor_manager.setup_lane_invasion_sensor(vehicle)
        
        logging.info(f"Vehicle '{vehicle_name}' set up for recording with {len(sensors_config)} sensors")
        return True
    
    def start_recording(self, output_dir: str):
        """
        Start recording data from all configured vehicles
        
        Args:
            output_dir: Directory to save recorded data
        """
        if self.recording:
            logging.warning("Recording already in progress")
            return
        
        try:
            # Create output directory
            self.output_dir = Path(output_dir)
            self.output_dir.mkdir(parents=True, exist_ok=True)
            
            # Set up recording for each hero vehicle
            for vehicle_name, vehicle in self.vehicle_manager.get_all_hero_vehicles().items():
                # Create vehicle directory
                vehicle_dir = self.output_dir / vehicle_name
                vehicle_dir.mkdir(exist_ok=True)
                
                # Create subdirectories for different sensor types
                (vehicle_dir / 'rgb').mkdir(exist_ok=True)
                (vehicle_dir / 'depth').mkdir(exist_ok=True)
                (vehicle_dir / 'lidar').mkdir(exist_ok=True)
                
                # Set up CSV file for metadata
                csv_path = vehicle_dir / 'metadata.csv'
                csv_file = open(csv_path, 'w', newline='')
                csv_writer = csv.writer(csv_file)
                
                # Write header
                csv_writer.writerow([
                    'frame', 'timestamp', 
                    'pos_x', 'pos_y', 'pos_z',
                    'rot_pitch', 'rot_yaw', 'rot_roll',
                    'vel_x', 'vel_y', 'vel_z',
                    'ang_vel_x', 'ang_vel_y', 'ang_vel_z',
                    'acc_x', 'acc_y', 'acc_z',
                    'throttle', 'steer', 'brake', 'handbrake', 'reverse',
                    'gear', 'rpm', 'speed_kmh'
                ])
                
                # Store vehicle data
                self.vehicle_data[vehicle_name] = {
                    'csv_file': csv_file,
                    'csv_writer': csv_writer,
                    'frame_count': 0
                }
                
                # Start processing threads for each sensor
                for sensor_type in ['rgb', 'depth', 'lidar']:
                    sensor_id = (vehicle.id, sensor_type)
                    if self.sensor_manager.get_sensor(*sensor_id):
                        processor_func = lambda data, v=vehicle_name, s=sensor_type: self._process_sensor_data(data, v, s)
                        self.sensor_manager.start_processing_thread(sensor_id, processor_func)
            
            # Set recording flag
            self.recording = True
            self.stop_event.clear()
            
            # Start metadata recording thread
            self._start_metadata_thread()
            
            logging.info(f"Recording started to {self.output_dir}")
            
        except Exception as e:
            logging.error(f"Error starting recording: {str(e)}")
            self.stop_recording()
    
    def stop_recording(self):
        """Stop recording data"""
        if not self.recording:
            return
            
        try:
            # Set flags to stop threads
            self.recording = False
            self.stop_event.set()
            
            # Wait for threads to finish
            time.sleep(1)
            
            # Close CSV files
            for vehicle_data in self.vehicle_data.values():
                if 'csv_file' in vehicle_data and vehicle_data['csv_file']:
                    vehicle_data['csv_file'].close()
            
            # Clear data
            self.vehicle_data.clear()
            
            logging.info("Recording stopped")
            
        except Exception as e:
            logging.error(f"Error stopping recording: {str(e)}")
    
    def _start_metadata_thread(self):
        """Start thread to record vehicle metadata"""
        def metadata_loop():
            while self.recording and not self.stop_event.is_set():
                try:
                    # Wait for world tick in synchronous mode
                    self.world.tick()
                    
                    # Record metadata for each vehicle
                    for vehicle_name, vehicle in self.vehicle_manager.get_all_hero_vehicles().items():
                        if vehicle_name not in self.vehicle_data:
                            continue
                            
                        # Get vehicle data
                        transform = vehicle.get_transform()
                        velocity = vehicle.get_velocity()
                        angular_velocity = vehicle.get_angular_velocity()
                        acceleration = vehicle.get_acceleration()
                        control = vehicle.get_control()
                        
                        # Get vehicle physics control
                        physics = vehicle.get_physics_control()
                        
                        # Increment frame count
                        self.vehicle_data[vehicle_name]['frame_count'] += 1
                        frame = self.vehicle_data[vehicle_name]['frame_count']
                        
                        # Write row to CSV
                        self.vehicle_data[vehicle_name]['csv_writer'].writerow([
                            frame, time.time(),
                            transform.location.x, transform.location.y, transform.location.z,
                            transform.rotation.pitch, transform.rotation.yaw, transform.rotation.roll,
                            velocity.x, velocity.y, velocity.z,
                            angular_velocity.x, angular_velocity.y, angular_velocity.z,
                            acceleration.x, acceleration.y, acceleration.z,
                            control.throttle, control.steer, control.brake, control.hand_brake, control.reverse,
                            control.gear, vehicle.get_vehicle_rpm(), 3.6 * np.sqrt(velocity.x**2 + velocity.y**2 + velocity.z**2)
                        ])
                        
                        # Flush periodically to avoid data loss
                        if frame % 10 == 0:
                            self.vehicle_data[vehicle_name]['csv_file'].flush()
                    
                except Exception as e:
                    logging.error(f"Error in metadata thread: {str(e)}")
                    time.sleep(0.5)  # Avoid tight loop on error
        
        # Start thread
        thread = threading.Thread(target=metadata_loop)
        thread.daemon = True
        thread.start()
        self.processing_threads['metadata'] = thread
    
    def _process_sensor_data(self, data, vehicle_name, sensor_type):
        """Process and save sensor data"""
        if not self.recording or self.stop_event.is_set():
            return
            
        try:
            # Get frame count
            if vehicle_name not in self.vehicle_data:
                return
                
            frame = self.vehicle_data[vehicle_name]['frame_count']
            
            # Get output directory
            vehicle_dir = self.output_dir / vehicle_name
            
            if sensor_type == 'rgb':
                # Convert image to numpy array
                array = np.frombuffer(data.raw_data, dtype=np.dtype("uint8"))
                array = np.reshape(array, (data.height, data.width, 4))
                array = array[:, :, :3]  # Remove alpha channel
                
                # Save image
                import cv2
                filename = vehicle_dir / 'rgb' / f'frame_{frame:06d}.jpg'
                cv2.imwrite(str(filename), array[:, :, ::-1])  # BGR to RGB
                
            elif sensor_type == 'depth':
                # Convert depth image to numpy array
                array = np.frombuffer(data.raw_data, dtype=np.dtype("uint8"))
                array = np.reshape(array, (data.height, data.width, 4))
                
                # Convert BGRA to depth map
                depth_map = array[:, :, 2] + array[:, :, 1] * 256 + array[:, :, 0] * 256 * 256
                depth_map = depth_map.astype(np.float32) / (256 * 256 * 256 - 1)
                depth_map = depth_map * 1000  # Convert to meters
                
                # Save depth map
                filename = vehicle_dir / 'depth' / f'frame_{frame:06d}.npy'
                np.save(str(filename), depth_map)
                
            elif sensor_type == 'lidar':
                # Get point cloud data
                points = np.frombuffer(data.raw_data, dtype=np.dtype('f4'))
                points = np.reshape(points, (-1, 4))
                
                # Save point cloud
                filename = vehicle_dir / 'lidar' / f'frame_{frame:06d}.npy'
                np.save(str(filename), points)
                
        except Exception as e:
            logging.error(f"Error processing {sensor_type} data: {str(e)}")
    
    def cleanup(self):
        """Clean up resources"""
        self.stop_recording()
        
        # Restore asynchronous mode
        settings = self.world.get_settings()
        settings.synchronous_mode = False
        settings.fixed_delta_seconds = None
        self.world.apply_settings(settings)
        
        # Clear any remaining threads
        self.stop_event.set()
        for thread in self.processing_threads.values():
            if thread.is_alive():
                thread.join(timeout=2.0)
        
        self.processing_threads.clear()

    def process_data(self, output_dir):
        """Process recorded data (convert to videos, etc.)"""
        try:
            logging.info(f"Processing data in {output_dir}")
            # Implement data processing logic here
            # For example, convert image sequences to videos
            
            # You could use the CarlaDataProcessor class here
            from .data import CarlaDataProcessor
            processor = CarlaDataProcessor(output_dir)
            processor.start_processing_threads()
            # Wait for processing to complete
            time.sleep(2)
            processor.stop()
            
            logging.info("Data processing complete")
        except Exception as e:
            logging.error(f"Error processing data: {str(e)}")