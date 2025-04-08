import carla
import logging
import random
import time
from typing import List, Dict, Optional, Tuple

class CarlaVehicleManager:
    """Manages vehicle spawning and control in CARLA"""
    
    def __init__(self, client: carla.Client, world_manager, max_vehicles: int = 30):
        """
        Initialize the vehicle manager
        
        Args:
            client: Connected CARLA client
            world_manager: CarlaWorldManager instance
            max_vehicles: Maximum number of vehicles to spawn
        """
        self.client = client
        self.world = client.get_world()
        self.world_manager = world_manager
        self.max_vehicles = max_vehicles
        self.traffic_manager = world_manager.traffic_manager
        self.blueprint_library = self.world.get_blueprint_library()
        
        # Vehicle tracking
        self.vehicles = {}  # id -> vehicle object
        self.hero_vehicles = {}  # name -> vehicle object
    
    def spawn_traffic(self, num_vehicles: int = 30, safe_spawn: bool = True) -> int:
        """
        Spawn traffic vehicles with autopilot
        
        Args:
            num_vehicles: Number of vehicles to spawn
            safe_spawn: Whether to filter out problematic vehicle types
            
        Returns:
            Number of vehicles successfully spawned
        """
        try:
            # Limit to max vehicles
            num_vehicles = min(num_vehicles, self.max_vehicles)
            
            # Get spawn points
            spawn_points = self.world.get_map().get_spawn_points()
            if not spawn_points:
                logging.error("No spawn points available")
                return 0
                
            # Get vehicle blueprints
            vehicle_bps = self.blueprint_library.filter('vehicle.*')
            
            # Filter out problematic vehicles if safe_spawn is True
            if safe_spawn:
                vehicle_bps = [bp for bp in vehicle_bps if 
                              int(bp.get_attribute('number_of_wheels')) == 4 and
                              not bp.id.endswith('isetta') and
                              not bp.id.endswith('carlacola') and
                              not bp.id.endswith('cybertruck') and
                              not bp.id.endswith('t2')]
            
            # Spawn vehicles
            batch_commands = []
            for i in range(num_vehicles):
                # Get random blueprint and spawn point
                bp = random.choice(vehicle_bps)
                transform = random.choice(spawn_points)
                
                # Try to avoid spawning at the same point
                spawn_points.remove(transform)
                if not spawn_points:
                    spawn_points = self.world.get_map().get_spawn_points()
                
                # Set blueprint attributes
                if bp.has_attribute('color'):
                    color = random.choice(bp.get_attribute('color').recommended_values)
                    bp.set_attribute('color', color)
                
                if bp.has_attribute('driver_id'):
                    driver_id = random.choice(bp.get_attribute('driver_id').recommended_values)
                    bp.set_attribute('driver_id', driver_id)
                
                # Set as non-hero vehicle
                if bp.has_attribute('role_name'):
                    bp.set_attribute('role_name', 'autopilot')
                
                # Add spawn command to batch
                batch_commands.append(carla.command.SpawnActor(bp, transform)
                    .then(carla.command.SetAutopilot(carla.command.FutureActor, True, self.traffic_manager.get_port())))
            
            # Execute batch
            results = self.client.apply_batch_sync(batch_commands, True)
            
            # Store spawned vehicles
            spawned_count = 0
            for result in results:
                if not result.error:
                    self.vehicles[result.actor_id] = result.actor_id
                    spawned_count += 1
            
            logging.info(f"Spawned {spawned_count} traffic vehicles")
            return spawned_count
            
        except Exception as e:
            logging.error(f"Error spawning traffic: {str(e)}")
            return 0
    
    def spawn_hero_vehicle(self, name: str, blueprint: str = None, spawn_point_idx: int = None) -> Optional[carla.Vehicle]:
        """
        Spawn a hero vehicle (player-controlled or for recording)
        
        Args:
            name: Unique name for the hero vehicle
            blueprint: Specific vehicle blueprint to use (or None for random)
            spawn_point_idx: Specific spawn point index (or None for random)
            
        Returns:
            The spawned vehicle or None if failed
        """
        try:
            # Check if name already exists
            if name in self.hero_vehicles:
                logging.warning(f"Hero vehicle '{name}' already exists")
                return self.hero_vehicles[name]
            
            # Get spawn points
            spawn_points = self.world.get_map().get_spawn_points()
            if not spawn_points:
                logging.error("No spawn points available")
                return None
            
            # Select spawn point
            if spawn_point_idx is not None and 0 <= spawn_point_idx < len(spawn_points):
                transform = spawn_points[spawn_point_idx]
            else:
                transform = random.choice(spawn_points)
            
            # Get blueprint
            if blueprint:
                bp = self.blueprint_library.find(blueprint)
            else:
                # Get a safe vehicle blueprint
                vehicle_bps = [bp for bp in self.blueprint_library.filter('vehicle.*') if 
                              int(bp.get_attribute('number_of_wheels')) == 4 and
                              not bp.id.endswith('isetta')]
                bp = random.choice(vehicle_bps)
            
            # Set as hero vehicle
            if bp.has_attribute('role_name'):
                bp.set_attribute('role_name', f'hero_{name}')
            
            # Spawn vehicle
            vehicle = self.world.spawn_actor(bp, transform)
            
            # Store in hero vehicles
            self.hero_vehicles[name] = vehicle
            
            logging.info(f"Spawned hero vehicle '{name}' ({bp.id})")
            return vehicle
            
        except Exception as e:
            logging.error(f"Error spawning hero vehicle '{name}': {str(e)}")
            return None
    
    def get_hero_vehicle(self, name: str) -> Optional[carla.Vehicle]:
        """Get a hero vehicle by name"""
        return self.hero_vehicles.get(name)
    
    def get_all_hero_vehicles(self) -> Dict[str, carla.Vehicle]:
        """Get all hero vehicles"""
        return self.hero_vehicles
    
    def set_autopilot(self, vehicle_or_name, enable: bool = True):
        """Enable or disable autopilot for a vehicle"""
        try:
            # Get vehicle object
            vehicle = vehicle_or_name
            if isinstance(vehicle_or_name, str):
                vehicle = self.get_hero_vehicle(vehicle_or_name)
                
            if vehicle:
                vehicle.set_autopilot(enable, self.traffic_manager.get_port())
                logging.info(f"Set autopilot to {enable} for vehicle {vehicle.id}")
            else:
                logging.warning(f"Vehicle not found: {vehicle_or_name}")
                
        except Exception as e:
            logging.error(f"Error setting autopilot: {str(e)}")
    
    def cleanup(self):
        """Destroy all spawned vehicles"""
        try:
            # First destroy hero vehicles
            for name, vehicle in list(self.hero_vehicles.items()):
                if vehicle.is_alive:
                    vehicle.destroy()
            self.hero_vehicles.clear()
            
            # Then destroy all other vehicles
            vehicle_ids = list(self.vehicles.keys())
            if vehicle_ids:
                destroy_commands = [carla.command.DestroyActor(actor_id) for actor_id in vehicle_ids]
                self.client.apply_batch_sync(destroy_commands, True)
            self.vehicles.clear()
            
            logging.info("All vehicles destroyed")
            
        except Exception as e:
            logging.error(f"Error cleaning up vehicles: {str(e)}")
