import carla
import logging
import time
import random
from typing import Dict, Any, Optional

class CarlaWorldManager:
    """Manages CARLA world settings, weather, and maps"""
    
    # Weather presets
    WEATHER_PRESETS = {
        'Clear': {
            'cloudiness': 10.0,
            'precipitation': 0.0,
            'precipitation_deposits': 0.0,
            'wind_intensity': 0.35,
            'sun_azimuth_angle': 0.0,
            'sun_altitude_angle': 70.0,
            'fog_density': 0.0,
            'fog_distance': 0.0,
            'wetness': 0.0
        },
        'Cloudy': {
            'cloudiness': 80.0,
            'precipitation': 0.0,
            'precipitation_deposits': 0.0,
            'wind_intensity': 0.35,
            'sun_azimuth_angle': 0.0,
            'sun_altitude_angle': 70.0,
            'fog_density': 0.0,
            'fog_distance': 0.0,
            'wetness': 0.0
        },
        'Rain': {
            'cloudiness': 100.0,
            'precipitation': 60.0,
            'precipitation_deposits': 40.0,
            'wind_intensity': 0.7,
            'sun_azimuth_angle': 0.0,
            'sun_altitude_angle': 45.0,
            'fog_density': 10.0,
            'fog_distance': 0.0,
            'wetness': 80.0
        },
        'Night': {
            'cloudiness': 60.0,
            'precipitation': 0.0,
            'precipitation_deposits': 0.0,
            'wind_intensity': 0.35,
            'sun_azimuth_angle': 0.0,
            'sun_altitude_angle': -30.0,
            'fog_density': 0.0,
            'fog_distance': 0.0,
            'wetness': 0.0
        }
    }
    
    def __init__(self, client: carla.Client, fps: int = 20, sync_mode: bool = True):
        """
        Initialize the world manager
        
        Args:
            client: Connected CARLA client
            fps: Simulation FPS (default: 20)
            sync_mode: Whether to use synchronous mode (default: True)
        """
        self.client = client
        self.world = client.get_world()
        self.fps = fps
        self.sync_mode = sync_mode
        self.original_settings = None
        self.traffic_manager = None
        self.tm_port = random.randint(8000, 8100)
        
        # Initialize world
        self._setup_world()
    
    def _setup_world(self):
        """Configure initial world settings"""
        try:
            # Store original settings
            self.original_settings = self.world.get_settings()
            
            # Configure world settings
            settings = self.world.get_settings()
            settings.synchronous_mode = self.sync_mode
            settings.fixed_delta_seconds = 1.0 / self.fps
            self.world.apply_settings(settings)
            
            # Set up traffic manager
            self.traffic_manager = self.client.get_trafficmanager(self.tm_port)
            self.traffic_manager.set_synchronous_mode(self.sync_mode)
            
            logging.info(f"World initialized with FPS={self.fps}, sync_mode={self.sync_mode}")
        except Exception as e:
            logging.error(f"Error setting up world: {str(e)}")
            raise
    
    def set_weather(self, preset: str = 'Clear', custom_params: Optional[Dict[str, float]] = None):
        """
        Set weather conditions
        
        Args:
            preset: Weather preset name (Clear, Cloudy, Rain, Night)
            custom_params: Custom weather parameters to override preset
        """
        try:
            # Get current weather
            weather = self.world.get_weather()
            
            # Apply preset if valid
            if preset in self.WEATHER_PRESETS:
                params = self.WEATHER_PRESETS[preset]
                for param, value in params.items():
                    setattr(weather, param, value)
                    
                # Override with custom parameters if provided
                if custom_params:
                    for param, value in custom_params.items():
                        if hasattr(weather, param):
                            setattr(weather, param, value)
                
                # Apply weather
                self.world.set_weather(weather)
                logging.info(f"Weather set to preset '{preset}' with parameters: {params}")
            else:
                logging.warning(f"Unknown weather preset: {preset}")
        except Exception as e:
            logging.error(f"Error setting weather: {str(e)}")
            raise
    
    def load_map(self, map_name: str, reset_settings: bool = True):
        """
        Load a new map
        
        Args:
            map_name: Name of the map to load
            reset_settings: Whether to reset world settings after loading
        """
        try:
            logging.info(f"Loading map: {map_name}")
            self.client.load_world(map_name)
            self.world = self.client.get_world()
            
            if reset_settings:
                self._setup_world()
                
            logging.info(f"Map {map_name} loaded successfully")
        except Exception as e:
            logging.error(f"Error loading map {map_name}: {str(e)}")
            raise
    
    def tick(self, frames: int = 1):
        """
        Advance the simulation by the specified number of frames
        
        Args:
            frames: Number of frames to advance
        """
        if not self.sync_mode:
            logging.warning("Tick called but synchronous mode is disabled")
            return
            
        try:
            for _ in range(frames):
                self.world.tick()
        except Exception as e:
            logging.error(f"Error during world tick: {str(e)}")
            raise
    
    def reset(self):
        """Reset world to original settings"""
        try:
            if self.original_settings:
                self.world.apply_settings(self.original_settings)
                logging.info("World settings reset to original")
        except Exception as e:
            logging.error(f"Error resetting world settings: {str(e)}")
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.reset()