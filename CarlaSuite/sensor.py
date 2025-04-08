import carla
import logging
import queue
import threading
import weakref
import time
from typing import Dict, List, Optional, Callable, Any, Tuple

class CarlaSensorManager:
    """Manages sensors for multiple vehicles in CARLA"""
    
    def __init__(self, world_manager):
        """
        Initialize the sensor manager
        
        Args:
            world_manager: CarlaWorldManager instance
        """
        self.world = world_manager.client.get_world()
        self.world_manager = world_manager
        self.blueprint_library = self.world.get_blueprint_library()
        
        # Sensor tracking
        self.sensors = {}  # (vehicle_id, sensor_type) -> sensor object
        self.sensor_queues = {}  # (vehicle_id, sensor_type) -> queue
        self.sensor_callbacks = {}  # (vehicle_id, sensor_type) -> callback
        
        # Threading
        self.stop_event = threading.Event()
        self.processing_threads = {}
    
    def setup_camera(self, vehicle, camera_type: str = 'rgb', 
                    position: Tuple[float, float, float] = (1.5, 0, 2.4),
                    rotation: Tuple[float, float, float] = (0, 0, 0),
                    width: int = 1280, height: int = 720, fov: float = 90.0,
                    callback: Optional[Callable] = None) -> Optional[carla.Sensor]:
        """
        Set up a camera sensor on a vehicle
        
        Args:
            vehicle: Vehicle to attach camera to
            camera_type: Type of camera ('rgb', 'depth', 'semantic_segmentation')
            position: Camera position relative to vehicle (x, y, z)
            rotation: Camera rotation (pitch, yaw, roll)
            width: Image width
            height: Image height
            fov: Field of view
            callback: Custom callback function for sensor data
            
        Returns:
            Camera sensor object or None if failed
        """
        try:
            # Create blueprint
            camera_bp = self.blueprint_library.find(f'sensor.camera.{camera_type}')
            camera_bp.set_attribute('image_size_x', str(width))
            camera_bp.set_attribute('image_size_y', str(height))
            camera_bp.set_attribute('fov', str(fov))
            
            # Set up transform
            camera_transform = carla.Transform(
                carla.Location(x=position[0], y=position[1], z=position[2]),
                carla.Rotation(pitch=rotation[0], yaw=rotation[1], roll=rotation[2])
            )
            
            # Spawn camera
            camera = self.world.spawn_actor(camera_bp, camera_transform, attach_to=vehicle)
            
            # Set up data queue and callback
            sensor_id = (vehicle.id, camera_type)
            self.sensor_queues[sensor_id] = queue.Queue(maxsize=30)
            
            # Set up callback
            if callback:
                self.sensor_callbacks[sensor_id] = callback
                camera.listen(lambda data: self._sensor_callback(sensor_id, data, callback))
            else:
                camera.listen(lambda data: self._sensor_callback(sensor_id, data))
            
            # Store sensor
            self.sensors[sensor_id] = camera
            
            logging.info(f"Camera {camera_type} set up on vehicle {vehicle.id}")
            return camera
            
        except Exception as e:
            logging.error(f"Error setting up camera: {str(e)}")
            return None
    
    def setup_lidar(self, vehicle, 
                   position: Tuple[float, float, float] = (0, 0, 2.4),
                   rotation: Tuple[float, float, float] = (0, 0, 0),
                   points_per_second: int = 100000, 
                   channels: int = 32,
                   range: float = 100.0,
                   callback: Optional[Callable] = None) -> Optional[carla.Sensor]:
        """
        Set up a LiDAR sensor on a vehicle
        
        Args:
            vehicle: Vehicle to attach LiDAR to
            position: LiDAR position relative to vehicle (x, y, z)
            rotation: LiDAR rotation (pitch, yaw, roll)
            points_per_second: Points captured per second
            channels: Number of channels
            range: Maximum range in meters
            callback: Custom callback function for sensor data
            
        Returns:
            LiDAR sensor object or None if failed
        """
        try:
            # Create blueprint
            lidar_bp = self.blueprint_library.find('sensor.lidar.ray_cast')
            lidar_bp.set_attribute('points_per_second', str(points_per_second))
            lidar_bp.set_attribute('channels', str(channels))
            lidar_bp.set_attribute('range', str(range))
            
            # Set up transform
            lidar_transform = carla.Transform(
                carla.Location(x=position[0], y=position[1], z=position[2]),
                carla.Rotation(pitch=rotation[0], yaw=rotation[1], roll=rotation[2])
            )
            
            # Spawn LiDAR
            lidar = self.world.spawn_actor(lidar_bp, lidar_transform, attach_to=vehicle)
            
            # Set up data queue and callback
            sensor_id = (vehicle.id, 'lidar')
            self.sensor_queues[sensor_id] = queue.Queue(maxsize=30)
            
            # Set up callback
            if callback:
                self.sensor_callbacks[sensor_id] = callback
                lidar.listen(lambda data: self._sensor_callback(sensor_id, data, callback))
            else:
                lidar.listen(lambda data: self._sensor_callback(sensor_id, data))
            
            # Store sensor
            self.sensors[sensor_id] = lidar
            
            logging.info(f"LiDAR set up on vehicle {vehicle.id}")
            return lidar
            
        except Exception as e:
            logging.error(f"Error setting up LiDAR: {str(e)}")
            return None
    
    def _sensor_callback(self, sensor_id, data, custom_callback=None):
        """Process sensor data"""
        try:
            # Put data in queue
            if sensor_id in self.sensor_queues:
                # Don't block if queue is full (drop oldest data)
                if self.sensor_queues[sensor_id].full():
                    try:
                        self.sensor_queues[sensor_id].get_nowait()
                    except queue.Empty:
                        pass
                self.sensor_queues[sensor_id].put(data)
            
            # Call custom callback if provided
            if custom_callback:
                custom_callback(data)
                
        except Exception as e:
            logging.error(f"Error in sensor callback: {str(e)}")
    
    def start_processing_thread(self, sensor_id, processor_func):
        """Start a thread to process sensor data"""
        if sensor_id in self.processing_threads and self.processing_threads[sensor_id].is_alive():
            logging.warning(f"Processing thread for sensor {sensor_id} already running")
            return
            
        def process_loop():
            while not self.stop_event.is_set():
                try:
                    # Get data with timeout
                    data = self.sensor_queues[sensor_id].get(timeout=1.0)
                    processor_func(data)
                    self.sensor_queues[sensor_id].task_done()
                except queue.Empty:
                    continue
                except Exception as e:
                    logging.error(f"Error processing sensor data: {str(e)}")
        
        # Start thread
        thread = threading.Thread(target=process_loop)
        thread.daemon = True
        thread.start()
        self.processing_threads[sensor_id] = thread
        logging.info(f"Started processing thread for sensor {sensor_id}")
    
    def get_sensor(self, vehicle_id, sensor_type):
        """Get sensor by vehicle ID and type"""
        return self.sensors.get((vehicle_id, sensor_type))
    
    def get_latest_data(self, vehicle_id, sensor_type, timeout=1.0):
        """Get latest data from sensor queue"""
        sensor_id = (vehicle_id, sensor_type)
        if sensor_id not in self.sensor_queues:
            return None
            
        try:
            # Get latest data (clear queue first)
            while self.sensor_queues[sensor_id].qsize() > 1:
                self.sensor_queues[sensor_id].get_nowait()
                self.sensor_queues[sensor_id].task_done()
                
            return self.sensor_queues[sensor_id].get(timeout=timeout)
        except queue.Empty:
            return None
    
    def cleanup(self):
        """Clean up all sensors"""
        try:
            # Stop processing threads
            self.stop_event.set()
            for thread in self.processing_threads.values():
                if thread.is_alive():
                    thread.join(timeout=2.0)
            
            # Destroy all sensors
            for sensor_id, sensor in list(self.sensors.items()):
                if sensor.is_alive:
                    sensor.stop()
                    sensor.destroy()
            
            # Clear data structures
            self.sensors.clear()
            self.sensor_queues.clear()
            self.sensor_callbacks.clear()
            self.processing_threads.clear()
            
            logging.info("All sensors cleaned up")
            
        except Exception as e:
            logging.error(f"Error cleaning up sensors: {str(e)}")