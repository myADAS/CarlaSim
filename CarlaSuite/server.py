import carla
import logging
import time
from pathlib import Path

class CarlaServerManager:
    """Manages CARLA client connection with robust error handling"""
    
    def __init__(self, port=2000, timeout=20):
        """
        Initialize the CARLA client manager
        
        Args:
            port: Server port (default: 2000)
            timeout: Maximum time to wait for connection (seconds)
        """
        self.port = port
        self.timeout = timeout
        self.client = None
        self.world = None
    
    def connect(self):
        """Connect to running CARLA server"""
        try:
            # Try to establish a client connection
            self.client = carla.Client('localhost', self.port)
            self.client.set_timeout(10.0)
            
            # Try to get world
            start_time = time.time()
            while time.time() - start_time < self.timeout:
                try:
                    self.world = self.client.get_world()
                    version = self.client.get_server_version()
                    logging.info(f"Connected to CARLA server version {version}")
                    return True
                except Exception as e:
                    logging.debug(f"Retrying connection: {str(e)}")
                    time.sleep(2)
            
            raise TimeoutError(f"Could not connect to CARLA server within {self.timeout} seconds")
            
        except Exception as e:
            logging.error(f"Failed to connect to CARLA server: {str(e)}")
            raise
    
    def disconnect(self):
        """Disconnect from CARLA server"""
        self.client = None
        self.world = None
    
    def __enter__(self):
        self.connect()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()