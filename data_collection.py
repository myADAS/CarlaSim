#!/usr/bin/env python

# Copyright (c) 2019 Computer Vision Center (CVC) at the Universitat Autonoma de
# Barcelona (UAB).
#
# This work is licensed under the terms of the MIT license.
# For a copy, see <https://opensource.org/licenses/MIT>.

# Allows controlling a vehicle with a keyboard. For a simpler and more
# documented example, please take a look at tutorial.py.

"""
Welcome to CARLA manual control.

Use ARROWS or WASD keys for control.

    W            : throttle
    S            : brake
    A/D          : steer left/right
    Q            : toggle reverse
    Space        : hand-brake
    P            : toggle autopilot
    M            : toggle manual transmission
    ,/.          : gear up/down
    CTRL + W     : toggle constant velocity mode at 60 km/h

    L            : toggle next light type
    SHIFT + L    : toggle high beam
    Z/X          : toggle right/left blinker
    I            : toggle interior light

    TAB          : change sensor position
    ` or N       : next sensor
    [1-9]        : change to sensor [1-9]
    G            : toggle radar visualization
    C            : change weather (Shift+C reverse)
    Backspace    : change vehicle

    O            : open/close all doors of vehicle
    T            : toggle vehicle's telemetry

    V            : Select next map layer (Shift+V reverse)
    B            : Load current selected map layer (Shift+B to unload)

    R            : toggle recording images to disk

    CTRL + R     : toggle recording of simulation (replacing any previous)
    CTRL + P     : start replaying last recorded simulation
    CTRL + +     : increments the start time of the replay by 1 second (+SHIFT = 10 seconds)
    CTRL + -     : decrements the start time of the replay by 1 second (+SHIFT = 10 seconds)

    F1           : toggle HUD
    H/?          : toggle help
    ESC          : quit
"""

from __future__ import print_function


# ==============================================================================
# -- find carla module ---------------------------------------------------------
# ==============================================================================


import glob
import os
import sys
import csv
import datetime
import networkx as nx
from pathlib import Path

try:
    sys.path.append(glob.glob('../carla/dist/carla-*%d.%d-%s.egg' % (
        sys.version_info.major,
        sys.version_info.minor,
        'win-amd64' if os.name == 'nt' else 'linux-x86_64'))[0])
except IndexError:
    pass


# ==============================================================================
# -- imports -------------------------------------------------------------------
# ==============================================================================


import carla

from carla import ColorConverter as cc

import argparse
import collections
import logging
import math
import random
import re
import weakref
import time

try:
    import pygame
    from pygame.locals import KMOD_CTRL
    from pygame.locals import KMOD_SHIFT
    from pygame.locals import K_0
    from pygame.locals import K_9
    from pygame.locals import K_BACKQUOTE
    from pygame.locals import K_BACKSPACE
    from pygame.locals import K_COMMA
    from pygame.locals import K_DOWN
    from pygame.locals import K_ESCAPE
    from pygame.locals import K_F1
    from pygame.locals import K_LEFT
    from pygame.locals import K_PERIOD
    from pygame.locals import K_RIGHT
    from pygame.locals import K_SLASH
    from pygame.locals import K_SPACE
    from pygame.locals import K_TAB
    from pygame.locals import K_UP
    from pygame.locals import K_a
    from pygame.locals import K_b
    from pygame.locals import K_c
    from pygame.locals import K_d
    from pygame.locals import K_f
    from pygame.locals import K_g
    from pygame.locals import K_h
    from pygame.locals import K_i
    from pygame.locals import K_l
    from pygame.locals import K_m
    from pygame.locals import K_n
    from pygame.locals import K_o
    from pygame.locals import K_p
    from pygame.locals import K_q
    from pygame.locals import K_r
    from pygame.locals import K_s
    from pygame.locals import K_t
    from pygame.locals import K_v
    from pygame.locals import K_w
    from pygame.locals import K_x
    from pygame.locals import K_z
    from pygame.locals import K_MINUS
    from pygame.locals import K_EQUALS
except ImportError:
    raise RuntimeError('cannot import pygame, make sure pygame package is installed')

try:
    import numpy as np
except ImportError:
    raise RuntimeError('cannot import numpy, make sure numpy package is installed')

import cv2


# ==============================================================================
# -- Global functions ----------------------------------------------------------
# ==============================================================================

def get_lane_metrics(vehicle, world):
    """Calculate lane metrics matching record.py implementation"""
    # Get vehicle's current waypoint
    vehicle_transform = vehicle.get_transform()
    vehicle_location = vehicle_transform.location
    waypoint = world.get_map().get_waypoint(vehicle_location, project_to_road=True)
    
    # Initialize info dictionary matching record.py structure
    info = {
        'angle': 0.0,
        'in_lane': {
            'toMarking_LL': None,
            'toMarking_ML': None,
            'toMarking_MR': None,
            'toMarking_RR': None,
            'dist_LL': float('inf'),
            'dist_MM': float('inf'),
            'dist_RR': float('inf')
        },
        'on_marking': {
            'toMarking_L': None,
            'toMarking_M': None,
            'toMarking_R': None,
            'dist_L': float('inf'),
            'dist_R': float('inf')
        }
    }
    
    # Calculate angle between road and vehicle direction
    road_dir = waypoint.transform.get_forward_vector()
    vehicle_dir = vehicle_transform.get_forward_vector()
    dot = road_dir.x * vehicle_dir.x + road_dir.y * vehicle_dir.y
    cross = road_dir.x * vehicle_dir.y - road_dir.y * vehicle_dir.x
    info['angle'] = math.degrees(math.atan2(cross, dot))
    
    # Get lane width
    lane_width = waypoint.lane_width
    
    # Set lane markings distances
    if waypoint.lane_type == carla.LaneType.Driving:
        info['in_lane']['toMarking_ML'] = lane_width/2
        info['in_lane']['toMarking_MR'] = lane_width/2
        
        # Get adjacent lanes
        left_lane = waypoint.get_left_lane()
        right_lane = waypoint.get_right_lane()
        
        if left_lane:
            info['in_lane']['toMarking_LL'] = lane_width
        if right_lane:
            info['in_lane']['toMarking_RR'] = lane_width
    
    # Find distances to other vehicles
    vehicle_list = world.get_actors().filter('vehicle.*')
    for other_vehicle in vehicle_list:
        if other_vehicle.id == vehicle.id:
            continue
        
        other_location = other_vehicle.get_location()
        other_waypoint = world.get_map().get_waypoint(other_location)
        
        # Check if vehicle is in front
        to_other = other_location - vehicle_location
        forward = vehicle_transform.get_forward_vector()
        
        if forward.dot(to_other) > 0:
            distance = vehicle_location.distance(other_location)
            
            # Check which lane the other vehicle is in
            if other_waypoint.lane_id == waypoint.lane_id:
                info['in_lane']['dist_MM'] = min(info['in_lane']['dist_MM'], distance)
            elif other_waypoint.lane_id == waypoint.lane_id - 1:  # Left lane
                info['in_lane']['dist_LL'] = min(info['in_lane']['dist_LL'], distance)
            elif other_waypoint.lane_id == waypoint.lane_id + 1:  # Right lane
                info['in_lane']['dist_RR'] = min(info['in_lane']['dist_RR'], distance)
    
    # Set on-marking measurements
    if waypoint.lane_type == carla.LaneType.Driving:
        info['on_marking']['toMarking_L'] = lane_width
        info['on_marking']['toMarking_M'] = lane_width/2
        info['on_marking']['toMarking_R'] = lane_width
        info['on_marking']['dist_L'] = info['in_lane']['dist_LL']
        info['on_marking']['dist_R'] = info['in_lane']['dist_RR']
    
    return info

def find_weather_presets():
    rgx = re.compile('.+?(?:(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])|$)')
    name = lambda x: ' '.join(m.group(0) for m in rgx.finditer(x))
    presets = [x for x in dir(carla.WeatherParameters) if re.match('[A-Z].+', x)]
    return [(getattr(carla.WeatherParameters, x), name(x)) for x in presets]


def get_actor_display_name(actor, truncate=250):
    name = ' '.join(actor.type_id.replace('_', '.').title().split('.')[1:])
    return (name[:truncate - 1] + u'\u2026') if len(name) > truncate else name

def get_actor_blueprints(world, filter, generation):
    bps = world.get_blueprint_library().filter(filter)

    if generation.lower() == "all":
        return bps

    # If the filter returns only one bp, we assume that this one needed
    # and therefore, we ignore the generation
    if len(bps) == 1:
        return bps

    try:
        int_generation = int(generation)
        # Check if generation is in available generations
        if int_generation in [1, 2, 3]:
            bps = [x for x in bps if int(x.get_attribute('generation')) == int_generation]
            return bps
        else:
            print("   Warning! Actor Generation is not valid. No actor will be spawned.")
            return []
    except:
        print("   Warning! Actor Generation is not valid. No actor will be spawned.")
        return []

def generate_full_map_route(world):
    """Generate a route that covers the entire map"""
    
    # Get the map
    carla_map = world.get_map()
    
    # Get all waypoints with a fixed distance
    waypoint_list = carla_map.generate_waypoints(2.0)  # Generate waypoints every 2 meters
    
    # Filter waypoints to keep only one per road segment
    filtered_waypoints = []
    road_segments = set()
    
    for wp in waypoint_list:
        road_lane = (wp.road_id, wp.lane_id)
        if road_lane not in road_segments:
            road_segments.add(road_lane)
            filtered_waypoints.append(wp)
    
    return filtered_waypoints

def setup_full_map_navigation(world, vehicle):
    """Set up navigation to cover the entire map"""
    
    # Set up the traffic manager with careful driving parameters
    client = carla.Client('localhost', 2000)  # Create a client to get traffic manager
    traffic_manager = client.get_trafficmanager(8000)  # Get traffic manager on port 8000
    traffic_manager.set_global_distance_to_leading_vehicle(4.0)  # Safer following distance
    traffic_manager.global_percentage_speed_difference(-20)  # Drive 20% slower than speed limit
    traffic_manager.set_synchronous_mode(True)
    
    # Set vehicle under traffic manager control
    vehicle.set_autopilot(True, traffic_manager.get_port())
    
    # Configure vehicle-specific behavior
    traffic_manager.auto_lane_change(vehicle, True)  # Enable automatic lane changes
    traffic_manager.distance_to_leading_vehicle(vehicle, 5)  # Vehicle-specific following distance
    traffic_manager.vehicle_percentage_speed_difference(vehicle, -20)  # Vehicle-specific speed
    traffic_manager.ignore_lights_percentage(vehicle, 0)  # Always obey traffic lights
    traffic_manager.ignore_signs_percentage(vehicle, 0)  # Always obey traffic signs
    traffic_manager.ignore_vehicles_percentage(vehicle, 0)  # Don't ignore other vehicles
    traffic_manager.ignore_walkers_percentage(vehicle, 0)  # Don't ignore pedestrians
    
    # Let the traffic manager handle the navigation
    # It will automatically explore the map while following traffic rules
    print("Vehicle is now set to explore the map autonomously while following traffic rules")
    
    return traffic_manager


# ==============================================================================
# -- World ---------------------------------------------------------------------
# ==============================================================================


class World(object):
    def __init__(self, carla_world, hud, args):
        self.world = carla_world
        self.sync = args.sync
        self.actor_role_name = args.rolename
        self.recording_timer = args.timer
        self.timer_quit = args.timer_quit
        self.traverse_map = args.traverse_map
        self.recording_start_time = None
        self.coverage_threshold = args.coverage if hasattr(args, 'coverage') else 85.0  # Default 85% coverage
        
        # Initialize map coverage tracking
        self.visited_cells = set()
        self.total_cells = 0
        self.cell_size = 10  # Size of each grid cell in meters
        self.coverage_percentage = 0.0
        self.last_coverage_update = 0
        
        try:
            self.map = self.world.get_map()
            # Initialize the coverage grid
            self._init_coverage_grid()
        except RuntimeError as error:
            print('RuntimeError: {}'.format(error))
            print('  The server could not send the OpenDRIVE (.xodr) file:')
            print('  Make sure it exists, has the same name of your town, and is correct.')
            sys.exit(1)
            
        self.hud = hud
        self.player = None
        self.collision_sensor = None
        self.lane_invasion_sensor = None
        self.gnss_sensor = None
        self.imu_sensor = None
        self.radar_sensor = None
        self.camera_manager = None
        self._weather_presets = find_weather_presets()
        self._weather_index = 0
        self._actor_filter = args.filter
        self._actor_generation = args.generation
        self._gamma = args.gamma
        self.restart()
        self.world.on_tick(hud.on_world_tick)
        self.recording_enabled = False
        self.constant_velocity_enabled = False
        self.show_vehicle_telemetry = False
        self.doors_are_open = False
        self.current_map_layer = 0
        self.map_layer_names = [
            carla.MapLayer.NONE,
            carla.MapLayer.Buildings,
            carla.MapLayer.Decals,
            carla.MapLayer.Foliage,
            carla.MapLayer.Ground,
            carla.MapLayer.ParkedVehicles,
            carla.MapLayer.Particles,
            carla.MapLayer.Props,
            carla.MapLayer.StreetLights,
            carla.MapLayer.Walls,
            carla.MapLayer.All
        ]
        
        # Initialize traffic manager for map traversal if needed
        if self.traverse_map:
            self.traffic_manager = setup_full_map_navigation(self.world, self.player)
            print("Full map traversal mode activated - Vehicle will systematically explore the entire map")

    def _init_coverage_grid(self):
        """Initialize the grid for tracking map coverage."""
        # Get map bounds
        waypoints = self.map.generate_waypoints(2.0)
        if not waypoints:
            return
            
        # Calculate map boundaries from waypoints
        locations = [w.transform.location for w in waypoints]
        min_x = min(loc.x for loc in locations)
        max_x = max(loc.x for loc in locations)
        min_y = min(loc.y for loc in locations)
        max_y = max(loc.y for loc in locations)
        
        # Add padding
        padding = 50
        min_x -= padding
        max_x += padding
        min_y -= padding
        max_y += padding
        
        # Calculate grid dimensions
        self.grid_min_x = min_x
        self.grid_min_y = min_y
        self.grid_width = max_x - min_x
        self.grid_height = max_y - min_y
        
        # Calculate total cells (only count cells that contain roads)
        road_cells = set()
        for wp in waypoints:
            cell_x = int((wp.transform.location.x - self.grid_min_x) / self.cell_size)
            cell_y = int((wp.transform.location.y - self.grid_min_y) / self.cell_size)
            road_cells.add((cell_x, cell_y))
        
        self.total_cells = len(road_cells)
        print(f"Map grid initialized with {self.total_cells} road cells")

    def update_coverage(self):
        """Update the map coverage based on vehicle position."""
        if not self.player or self.total_cells == 0:
            return 0.0
            
        # Get current position
        location = self.player.get_location()
        
        # Convert to grid cell
        cell_x = int((location.x - self.grid_min_x) / self.cell_size)
        cell_y = int((location.y - self.grid_min_y) / self.cell_size)
        
        # Add to visited cells
        self.visited_cells.add((cell_x, cell_y))
        
        # Calculate coverage percentage
        self.coverage_percentage = (len(self.visited_cells) / self.total_cells) * 100
        
        # Update coverage less frequently to avoid spam
        current_time = time.time()
        if current_time - self.last_coverage_update >= 5:  # Update every 5 seconds
            print(f"\rMap Coverage: {self.coverage_percentage:.2f}%", end="")
            self.last_coverage_update = current_time
            
            # Write coverage to file
            with open("current_coverage.txt", "w") as f:
                f.write(f"{self.coverage_percentage:.2f}")
        
        return self.coverage_percentage

    def restart(self):
        self.player_max_speed = 1.589
        self.player_max_speed_fast = 3.713
        # Keep same camera config if the camera manager exists.
        cam_index = self.camera_manager.index if self.camera_manager is not None else 0
        cam_pos_index = 1  # Force cockpit view
        # Get a random blueprint.
        blueprint_list = get_actor_blueprints(self.world, self._actor_filter, self._actor_generation)
        if not blueprint_list:
            raise ValueError("Couldn't find any blueprints with the specified filters")
        blueprint = random.choice(blueprint_list)
        blueprint.set_attribute('role_name', self.actor_role_name)
        if blueprint.has_attribute('terramechanics'):
            blueprint.set_attribute('terramechanics', 'true')
        if blueprint.has_attribute('color'):
            color = random.choice(blueprint.get_attribute('color').recommended_values)
            blueprint.set_attribute('color', color)
        if blueprint.has_attribute('driver_id'):
            driver_id = random.choice(blueprint.get_attribute('driver_id').recommended_values)
            blueprint.set_attribute('driver_id', driver_id)
        if blueprint.has_attribute('is_invincible'):
            blueprint.set_attribute('is_invincible', 'true')
        # set the max speed
        if blueprint.has_attribute('speed'):
            self.player_max_speed = float(blueprint.get_attribute('speed').recommended_values[1])
            self.player_max_speed_fast = float(blueprint.get_attribute('speed').recommended_values[2])

        # Spawn the player.
        if self.player is not None:
            spawn_point = self.player.get_transform()
            spawn_point.location.z += 2.0
            spawn_point.rotation.roll = 0.0
            spawn_point.rotation.pitch = 0.0
            self.destroy()
            self.player = self.world.try_spawn_actor(blueprint, spawn_point)
            self.show_vehicle_telemetry = False
            self.modify_vehicle_physics(self.player)
        while self.player is None:
            if not self.map.get_spawn_points():
                print('There are no spawn points available in your map/town.')
                print('Please add some Vehicle Spawn Point to your UE4 scene.')
                sys.exit(1)
            spawn_points = self.map.get_spawn_points()
            spawn_point = random.choice(spawn_points) if spawn_points else carla.Transform()
            self.player = self.world.try_spawn_actor(blueprint, spawn_point)
            self.show_vehicle_telemetry = False
            self.modify_vehicle_physics(self.player)
            
        # Initialize traffic manager for map traversal if needed
        if hasattr(self, 'traverse_map') and self.traverse_map:
            self.traffic_manager = setup_full_map_navigation(self.world, self.player)
            print("Full map traversal mode activated - Vehicle will systematically explore the entire map")
            
        # Set up the sensors.
        self.collision_sensor = CollisionSensor(self.player, self.hud)
        self.lane_invasion_sensor = LaneInvasionSensor(self.player, self.hud)
        self.gnss_sensor = GnssSensor(self.player)
        self.imu_sensor = IMUSensor(self.player)
        self.camera_manager = CameraManager(self.player, self.hud, self._gamma)
        self.camera_manager.transform_index = cam_pos_index
        self.camera_manager.set_sensor(cam_index, notify=False)
        actor_type = get_actor_display_name(self.player)
        self.hud.notification(actor_type)

        if self.sync:
            self.world.tick()
        else:
            self.world.wait_for_tick()

    def next_weather(self, reverse=False):
        self._weather_index += -1 if reverse else 1
        self._weather_index %= len(self._weather_presets)
        preset = self._weather_presets[self._weather_index]
        self.hud.notification('Weather: %s' % preset[1])
        self.player.get_world().set_weather(preset[0])

    def next_map_layer(self, reverse=False):
        self.current_map_layer += -1 if reverse else 1
        self.current_map_layer %= len(self.map_layer_names)
        selected = self.map_layer_names[self.current_map_layer]
        self.hud.notification('LayerMap selected: %s' % selected)

    def load_map_layer(self, unload=False):
        selected = self.map_layer_names[self.current_map_layer]
        if unload:
            self.hud.notification('Unloading map layer: %s' % selected)
            self.world.unload_map_layer(selected)
        else:
            self.hud.notification('Loading map layer: %s' % selected)
            self.world.load_map_layer(selected)

    def toggle_radar(self):
        if self.radar_sensor is None:
            self.radar_sensor = RadarSensor(self.player)
        elif self.radar_sensor.sensor is not None:
            self.radar_sensor.sensor.destroy()
            self.radar_sensor = None

    def modify_vehicle_physics(self, actor):
        #If actor is not a vehicle, we cannot use the physics control
        try:
            physics_control = actor.get_physics_control()
            physics_control.use_sweep_wheel_collision = True
            actor.apply_physics_control(physics_control)
        except Exception:
            pass

    def tick(self, clock):
        self.hud.tick(self, clock)
        
        # Update map coverage
        coverage = self.update_coverage()
        
        # Check if coverage threshold is met
        if coverage >= self.coverage_threshold:
            print(f"\nMap coverage threshold ({self.coverage_threshold}%) reached!")
            if self.timer_quit:
                return True
        
        # Handle recording timer if active
        if self.recording_timer > 0:
            # Initialize recording start time when recording begins
            if self.camera_manager.recording and self.recording_start_time is None:
                self.recording_start_time = time.time()
                print(f"\nRecording started - Timer set for {self.recording_timer}s")
            
            # Check if recording is active and timer has expired
            if self.camera_manager.recording and self.recording_start_time is not None:
                elapsed = time.time() - self.recording_start_time
                if elapsed >= self.recording_timer:
                    print(f"\nRecording timer ({self.recording_timer}s) expired!")
                    self.camera_manager.toggle_recording()
                    self.recording_start_time = None
                    if self.timer_quit:
                        print("Timer quit enabled - exiting...")
                        return True
        
        return False  # Continue running

    def render(self, display):
        self.camera_manager.render(display)
        self.hud.render(display)

    def destroy_sensors(self):
        self.camera_manager.sensor.destroy()
        self.camera_manager.sensor = None
        self.camera_manager.index = None

    def destroy(self):
        try:
            if self.radar_sensor is not None:
                self.toggle_radar()
            sensors = [
                self.camera_manager.sensor,
                self.collision_sensor.sensor,
                self.lane_invasion_sensor.sensor,
                self.gnss_sensor.sensor,
                self.imu_sensor.sensor]
            for sensor in sensors:
                if sensor is not None and sensor.is_alive:
                    sensor.stop()
                    sensor.destroy()
            # Destroy camera manager sensors separately
            if self.camera_manager is not None:
                self.camera_manager.destroy_sensors()
            if self.player is not None and self.player.is_alive:
                self.player.destroy()
            # Clear references
            self.radar_sensor = None
            self.camera_manager = None
            self.collision_sensor = None
            self.lane_invasion_sensor = None
            self.gnss_sensor = None
            self.imu_sensor = None
            self.player = None
        except Exception as e:
            print(f"Warning: Error during world cleanup: {e}")


# ==============================================================================
# -- KeyboardControl -----------------------------------------------------------
# ==============================================================================


class KeyboardControl(object):
    """Class that handles keyboard input."""
    def __init__(self, world, start_in_autopilot):
        self._autopilot_enabled = start_in_autopilot
        self._ackermann_enabled = False
        self._ackermann_reverse = 1
        if isinstance(world.player, carla.Vehicle):
            self._control = carla.VehicleControl()
            self._ackermann_control = carla.VehicleAckermannControl()
            self._lights = carla.VehicleLightState.NONE
            world.player.set_autopilot(self._autopilot_enabled)
            world.player.set_light_state(self._lights)
        elif isinstance(world.player, carla.Walker):
            self._control = carla.WalkerControl()
            self._autopilot_enabled = False
            self._rotation = world.player.get_transform().rotation
        else:
            raise NotImplementedError("Actor type not supported")
        self._steer_cache = 0.0
        world.hud.notification("Press 'H' or '?' for help.", seconds=4.0)

    def parse_events(self, client, world, clock, sync_mode):
        if isinstance(self._control, carla.VehicleControl):
            current_lights = self._lights
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return True
            elif event.type == pygame.KEYUP:
                if self._is_quit_shortcut(event.key):
                    return True
                elif event.key == K_BACKSPACE:
                    if self._autopilot_enabled:
                        world.player.set_autopilot(False)
                        world.restart()
                        world.player.set_autopilot(True)
                    else:
                        world.restart()
                elif event.key == K_F1:
                    world.hud.toggle_info()
                elif event.key == K_v and pygame.key.get_mods() & KMOD_SHIFT:
                    world.next_map_layer(reverse=True)
                elif event.key == K_v:
                    world.next_map_layer()
                elif event.key == K_b and pygame.key.get_mods() & KMOD_SHIFT:
                    world.load_map_layer(unload=True)
                elif event.key == K_b:
                    world.load_map_layer()
                elif event.key == K_TAB:
                    world.camera_manager.toggle_camera()
                elif event.key == K_h or (event.key == K_SLASH and pygame.key.get_mods() & KMOD_SHIFT):
                    world.hud.help.toggle()
                elif event.key == K_c and pygame.key.get_mods() & KMOD_SHIFT:
                    world.next_weather(reverse=True)
                elif event.key == K_c:
                    world.next_weather()
                elif event.key == K_g:
                    world.toggle_radar()
                elif event.key == K_BACKQUOTE:
                    world.camera_manager.next_sensor()
                elif event.key == K_n:
                    world.camera_manager.next_sensor()
                elif event.key == K_w and (pygame.key.get_mods() & KMOD_CTRL):
                    if world.constant_velocity_enabled:
                        world.player.disable_constant_velocity()
                        world.constant_velocity_enabled = False
                        world.hud.notification("Disabled Constant Velocity Mode")
                    else:
                        world.player.enable_constant_velocity(carla.Vector3D(17, 0, 0))
                        world.constant_velocity_enabled = True
                        world.hud.notification("Enabled Constant Velocity Mode at 60 km/h")
                elif event.key == K_o:
                    try:
                        if world.doors_are_open:
                            world.hud.notification("Closing Doors")
                            world.doors_are_open = False
                            world.player.close_door(carla.VehicleDoor.All)
                        else:
                            world.hud.notification("Opening doors")
                            world.doors_are_open = True
                            world.player.open_door(carla.VehicleDoor.All)
                    except Exception:
                        pass
                elif event.key == K_t:
                    if world.show_vehicle_telemetry:
                        world.player.show_debug_telemetry(False)
                        world.show_vehicle_telemetry = False
                        world.hud.notification("Disabled Vehicle Telemetry")
                    else:
                        try:
                            world.player.show_debug_telemetry(True)
                            world.show_vehicle_telemetry = True
                            world.hud.notification("Enabled Vehicle Telemetry")
                        except Exception:
                            pass
                elif event.key > K_0 and event.key <= K_9:
                    index_ctrl = 0
                    if pygame.key.get_mods() & KMOD_CTRL:
                        index_ctrl = 9
                    world.camera_manager.set_sensor(event.key - 1 - K_0 + index_ctrl)
                elif event.key == K_r and not (pygame.key.get_mods() & KMOD_CTRL):
                    world.camera_manager.toggle_recording()
                elif event.key == K_r and (pygame.key.get_mods() & KMOD_CTRL):
                    if (world.recording_enabled):
                        client.stop_recorder()
                        world.recording_enabled = False
                        world.hud.notification("Recorder is OFF")
                    else:
                        client.start_recorder("manual_recording.rec")
                        world.recording_enabled = True
                        world.hud.notification("Recorder is ON")
                elif event.key == K_p and (pygame.key.get_mods() & KMOD_CTRL):
                    # stop recorder
                    client.stop_recorder()
                    world.recording_enabled = False
                    # work around to fix camera at start of replaying
                    current_index = world.camera_manager.index
                    world.destroy_sensors()
                    # disable autopilot
                    self._autopilot_enabled = False
                    world.player.set_autopilot(self._autopilot_enabled)
                    world.hud.notification("Replaying file 'manual_recording.rec'")
                    # replayer
                    client.replay_file("manual_recording.rec", world.recording_start, 0, 0)
                    world.camera_manager.set_sensor(current_index)
                elif event.key == K_MINUS and (pygame.key.get_mods() & KMOD_CTRL):
                    if pygame.key.get_mods() & KMOD_SHIFT:
                        world.recording_start -= 10
                    else:
                        world.recording_start -= 1
                    world.hud.notification("Recording start time is %d" % (world.recording_start))
                elif event.key == K_EQUALS and (pygame.key.get_mods() & KMOD_CTRL):
                    if pygame.key.get_mods() & KMOD_SHIFT:
                        world.recording_start += 10
                    else:
                        world.recording_start += 1
                    world.hud.notification("Recording start time is %d" % (world.recording_start))
                if isinstance(self._control, carla.VehicleControl):
                    if event.key == K_f:
                        # Toggle ackermann controller
                        self._ackermann_enabled = not self._ackermann_enabled
                        world.hud.show_ackermann_info(self._ackermann_enabled)
                        world.hud.notification("Ackermann Controller %s" %
                                               ("Enabled" if self._ackermann_enabled else "Disabled"))
                    if event.key == K_q:
                        if not self._ackermann_enabled:
                            self._control.gear = 1 if self._control.reverse else -1
                        else:
                            self._ackermann_reverse *= -1
                            # Reset ackermann control
                            self._ackermann_control = carla.VehicleAckermannControl()
                    elif event.key == K_m:
                        self._control.manual_gear_shift = not self._control.manual_gear_shift
                        self._control.gear = world.player.get_control().gear
                        world.hud.notification('%s Transmission' %
                                               ('Manual' if self._control.manual_gear_shift else 'Automatic'))
                    elif self._control.manual_gear_shift and event.key == K_COMMA:
                        self._control.gear = max(-1, self._control.gear - 1)
                    elif self._control.manual_gear_shift and event.key == K_PERIOD:
                        self._control.gear = self._control.gear + 1
                    elif event.key == K_p and not pygame.key.get_mods() & KMOD_CTRL:
                        if not self._autopilot_enabled and not sync_mode:
                            print("WARNING: You are currently in asynchronous mode and could "
                                  "experience some issues with the traffic simulation")
                        self._autopilot_enabled = not self._autopilot_enabled
                        world.player.set_autopilot(self._autopilot_enabled)
                        world.hud.notification(
                            'Autopilot %s' % ('On' if self._autopilot_enabled else 'Off'))
                    elif event.key == K_l and pygame.key.get_mods() & KMOD_CTRL:
                        current_lights ^= carla.VehicleLightState.Special1
                    elif event.key == K_l and pygame.key.get_mods() & KMOD_SHIFT:
                        current_lights ^= carla.VehicleLightState.HighBeam
                    elif event.key == K_l:
                        # Use 'L' key to switch between lights:
                        # closed -> position -> low beam -> fog
                        if not self._lights & carla.VehicleLightState.Position:
                            world.hud.notification("Position lights")
                            current_lights |= carla.VehicleLightState.Position
                        else:
                            world.hud.notification("Low beam lights")
                            current_lights |= carla.VehicleLightState.LowBeam
                        if self._lights & carla.VehicleLightState.LowBeam:
                            world.hud.notification("Fog lights")
                            current_lights |= carla.VehicleLightState.Fog
                        if self._lights & carla.VehicleLightState.Fog:
                            world.hud.notification("Lights off")
                            current_lights ^= carla.VehicleLightState.Position
                            current_lights ^= carla.VehicleLightState.LowBeam
                            current_lights ^= carla.VehicleLightState.Fog
                    elif event.key == K_i:
                        current_lights ^= carla.VehicleLightState.Interior
                    elif event.key == K_z:
                        current_lights ^= carla.VehicleLightState.LeftBlinker
                    elif event.key == K_x:
                        current_lights ^= carla.VehicleLightState.RightBlinker

        if not self._autopilot_enabled:
            if isinstance(self._control, carla.VehicleControl):
                self._parse_vehicle_keys(pygame.key.get_pressed(), clock.get_time())
                self._control.reverse = self._control.gear < 0
                # Set automatic control-related vehicle lights
                if self._control.brake:
                    current_lights |= carla.VehicleLightState.Brake
                else: # Remove the Brake flag
                    current_lights &= ~carla.VehicleLightState.Brake
                if self._control.reverse:
                    current_lights |= carla.VehicleLightState.Reverse
                else: # Remove the Reverse flag
                    current_lights &= ~carla.VehicleLightState.Reverse
                if current_lights != self._lights: # Change the light state only if necessary
                    self._lights = current_lights
                    world.player.set_light_state(carla.VehicleLightState(self._lights))
                # Apply control
                if not self._ackermann_enabled:
                    world.player.apply_control(self._control)
                else:
                    world.player.apply_ackermann_control(self._ackermann_control)
                    # Update control to the last one applied by the ackermann controller.
                    self._control = world.player.get_control()
                    # Update hud with the newest ackermann control
                    world.hud.update_ackermann_control(self._ackermann_control)

            elif isinstance(self._control, carla.WalkerControl):
                self._parse_walker_keys(pygame.key.get_pressed(), clock.get_time(), world)
                world.player.apply_control(self._control)

    def _parse_vehicle_keys(self, keys, milliseconds):
        if keys[K_UP] or keys[K_w]:
            if not self._ackermann_enabled:
                self._control.throttle = min(self._control.throttle + 0.1, 1.00)
            else:
                self._ackermann_control.speed += round(milliseconds * 0.005, 2) * self._ackermann_reverse
        else:
            if not self._ackermann_enabled:
                self._control.throttle = 0.0

        if keys[K_DOWN] or keys[K_s]:
            if not self._ackermann_enabled:
                self._control.brake = min(self._control.brake + 0.2, 1)
            else:
                self._ackermann_control.speed -= min(abs(self._ackermann_control.speed), round(milliseconds * 0.005, 2)) * self._ackermann_reverse
                self._ackermann_control.speed = max(0, abs(self._ackermann_control.speed)) * self._ackermann_reverse
        else:
            if not self._ackermann_enabled:
                self._control.brake = 0

        steer_increment = 5e-4 * milliseconds
        if keys[K_LEFT] or keys[K_a]:
            if self._steer_cache > 0:
                self._steer_cache = 0
            else:
                self._steer_cache -= steer_increment
        elif keys[K_RIGHT] or keys[K_d]:
            if self._steer_cache < 0:
                self._steer_cache = 0
            else:
                self._steer_cache += steer_increment
        else:
            self._steer_cache = 0.0
        self._steer_cache = min(0.7, max(-0.7, self._steer_cache))
        if not self._ackermann_enabled:
            self._control.steer = round(self._steer_cache, 1)
            self._control.hand_brake = keys[K_SPACE]
        else:
            self._ackermann_control.steer = round(self._steer_cache, 1)

    def _parse_walker_keys(self, keys, milliseconds, world):
        self._control.speed = 0.0
        if keys[K_DOWN] or keys[K_s]:
            self._control.speed = 0.0
        if keys[K_LEFT] or keys[K_a]:
            self._control.speed = .01
            self._rotation.yaw -= 0.08 * milliseconds
        if keys[K_RIGHT] or keys[K_d]:
            self._control.speed = .01
            self._rotation.yaw += 0.08 * milliseconds
        if keys[K_UP] or keys[K_w]:
            self._control.speed = world.player_max_speed_fast if pygame.key.get_mods() & KMOD_SHIFT else world.player_max_speed
        self._control.jump = keys[K_SPACE]
        self._rotation.yaw = round(self._rotation.yaw, 1)
        self._control.direction = self._rotation.get_forward_vector()

    @staticmethod
    def _is_quit_shortcut(key):
        return (key == K_ESCAPE) or (key == K_q and pygame.key.get_mods() & KMOD_CTRL)


# ==============================================================================
# -- HUD -----------------------------------------------------------------------
# ==============================================================================


class HUD(object):
    def __init__(self, width, height):
        self.dim = (width, height)
        font = pygame.font.Font(pygame.font.get_default_font(), 20)
        font_name = 'courier' if os.name == 'nt' else 'mono'
        fonts = [x for x in pygame.font.get_fonts() if font_name in x]
        default_font = 'ubuntumono'
        mono = default_font if default_font in fonts else fonts[0]
        mono = pygame.font.match_font(mono)
        self._font_mono = pygame.font.Font(mono, 12 if os.name == 'nt' else 14)
        self._notifications = FadingText(font, (width, 40), (0, height - 40))
        self.help = HelpText(pygame.font.Font(mono, 16), width, height)
        self.server_fps = 0
        self.frame = 0
        self.simulation_time = 0
        self._show_info = True
        self._info_text = []
        self._server_clock = pygame.time.Clock()

        self._show_ackermann_info = False
        self._ackermann_control = carla.VehicleAckermannControl()
        
        # Timer display attributes
        self._timer_font = pygame.font.Font(mono, 48)  # Larger font for timer
        self._timer_surface = None
        self._last_recording_state = False

    def on_world_tick(self, timestamp):
        self._server_clock.tick()
        self.server_fps = self._server_clock.get_fps()
        self.frame = timestamp.frame
        self.simulation_time = timestamp.elapsed_seconds

    def tick(self, world, clock):
        self._notifications.tick(world, clock)
        if not self._show_info:
            return
            
        # Update timer display if recording with timer
        timer_text = None
        if world.camera_manager.recording and world.recording_timer > 0:
            if world.recording_start_time is not None:
                elapsed = time.time() - world.recording_start_time
                remaining = max(0, world.recording_timer - elapsed)
                minutes = int(remaining // 60)
                seconds = int(remaining % 60)
                timer_text = f"{minutes:02d}:{seconds:02d}"
                
                # Create timer surface with red background if less than 10 seconds remaining
                color = (255, 0, 0) if remaining < 10 else (255, 255, 255)
                self._timer_surface = self._timer_font.render(timer_text, True, color)
            
            # Handle recording state change
            if not self._last_recording_state:
                self.notification(f'Recording started - Timer set for {world.recording_timer}s')
            self._last_recording_state = True
        else:
            self._timer_surface = None
            if self._last_recording_state:
                if world.recording_timer > 0:
                    self.notification('Recording stopped - Timer expired')
                self._last_recording_state = False

        t = world.player.get_transform()
        v = world.player.get_velocity()
        c = world.player.get_control()
        compass = world.imu_sensor.compass
        heading = 'N' if compass > 270.5 or compass < 89.5 else ''
        heading += 'S' if 90.5 < compass < 269.5 else ''
        heading += 'E' if 0.5 < compass < 179.5 else ''
        heading += 'W' if 180.5 < compass < 359.5 else ''
        colhist = world.collision_sensor.get_collision_history()
        collision = [colhist[x + self.frame - 200] for x in range(0, 200)]
        max_col = max(1.0, max(collision))
        collision = [x / max_col for x in collision]
        vehicles = world.world.get_actors().filter('vehicle.*')
        self._info_text = [
            'Server:  % 16.0f FPS' % self.server_fps,
            'Client:  % 16.0f FPS' % clock.get_fps()]
            
        # Add timer information if active
        if timer_text:
            self._info_text.append('Recording Timer: %s' % timer_text)
            
        self._info_text.extend([
            '',
            'Vehicle: % 20s' % get_actor_display_name(world.player, truncate=20),
            'Map:     % 20s' % world.map.name.split('/')[-1],
            'Simulation time: % 12s' % datetime.timedelta(seconds=int(self.simulation_time)),
            '',
            'Speed:   % 15.0f km/h' % (3.6 * math.sqrt(v.x**2 + v.y**2 + v.z**2)),
            u'Compass:% 17.0f\N{DEGREE SIGN} % 2s' % (compass, heading),
            'Accelero: (%5.1f,%5.1f,%5.1f)' % (world.imu_sensor.accelerometer),
            'Gyroscop: (%5.1f,%5.1f,%5.1f)' % (world.imu_sensor.gyroscope),
            'Location:% 20s' % ('(% 5.1f, % 5.1f)' % (t.location.x, t.location.y)),
            'GNSS:% 24s' % ('(% 2.6f, % 3.6f)' % (world.gnss_sensor.lat, world.gnss_sensor.lon)),
            'Height:  % 18.0f m' % t.location.z,
            ''])
        if isinstance(c, carla.VehicleControl):
            self._info_text += [
                ('Throttle:', c.throttle, 0.0, 1.0),
                ('Steer:', c.steer, -1.0, 1.0),
                ('Brake:', c.brake, 0.0, 1.0),
                ('Reverse:', c.reverse),
                ('Hand brake:', c.hand_brake),
                ('Manual:', c.manual_gear_shift),
                'Gear:        %s' % {-1: 'R', 0: 'N'}.get(c.gear, c.gear)]
            if self._show_ackermann_info:
                self._info_text += [
                    '',
                    'Ackermann Controller:',
                    '  Target speed: % 8.0f km/h' % (3.6*self._ackermann_control.speed),
                ]
        elif isinstance(c, carla.WalkerControl):
            self._info_text += [
                ('Speed:', c.speed, 0.0, 5.556),
                ('Jump:', c.jump)]
        self._info_text += [
            '',
            'Collision:',
            collision,
            '',
            'Number of vehicles: % 8d' % len(vehicles)]
        if len(vehicles) > 1:
            self._info_text += ['Nearby vehicles:']
            distance = lambda l: math.sqrt((l.x - t.location.x)**2 + (l.y - t.location.y)**2 + (l.z - t.location.z)**2)
            vehicles = [(distance(x.get_location()), x) for x in vehicles if x.id != world.player.id]
            for d, vehicle in sorted(vehicles, key=lambda vehicles: vehicles[0]):
                if d > 200.0:
                    break
                vehicle_type = get_actor_display_name(vehicle, truncate=22)
                self._info_text.append('% 4dm %s' % (d, vehicle_type))

    def show_ackermann_info(self, enabled):
        self._show_ackermann_info = enabled

    def update_ackermann_control(self, ackermann_control):
        self._ackermann_control = ackermann_control

    def toggle_info(self):
        self._show_info = not self._show_info

    def notification(self, text, seconds=2.0):
        self._notifications.set_text(text, seconds=seconds)

    def error(self, text):
        self._notifications.set_text('Error: %s' % text, (255, 0, 0))

    def render(self, display):
        if self._show_info:
            info_surface = pygame.Surface((220, self.dim[1]))
            info_surface.set_alpha(100)
            display.blit(info_surface, (0, 0))
            v_offset = 4
            bar_h_offset = 100
            bar_width = 106
            for item in self._info_text:
                if v_offset + 18 > self.dim[1]:
                    break
                if isinstance(item, list):
                    if len(item) > 1:
                        points = [(x + 8, v_offset + 8 + (1.0 - y) * 30) for x, y in enumerate(item)]
                        pygame.draw.lines(display, (255, 136, 0), False, points, 2)
                    item = None
                    v_offset += 18
                elif isinstance(item, tuple):
                    if isinstance(item[1], bool):
                        rect = pygame.Rect((bar_h_offset, v_offset + 8), (6, 6))
                        pygame.draw.rect(display, (255, 255, 255), rect, 0 if item[1] else 1)
                    else:
                        rect_border = pygame.Rect((bar_h_offset, v_offset + 8), (bar_width, 6))
                        pygame.draw.rect(display, (255, 255, 255), rect_border, 1)
                        f = (item[1] - item[2]) / (item[3] - item[2])
                        if item[2] < 0.0:
                            rect = pygame.Rect((bar_h_offset + f * (bar_width - 6), v_offset + 8), (6, 6))
                        else:
                            rect = pygame.Rect((bar_h_offset, v_offset + 8), (f * bar_width, 6))
                        pygame.draw.rect(display, (255, 255, 255), rect)
                    item = item[0]
                if item:  # At this point has to be a str.
                    surface = self._font_mono.render(item, True, (255, 255, 255))
                    display.blit(surface, (8, v_offset))
                v_offset += 18
        self._notifications.render(display)
        self.help.render(display)
        
        # Render timer if active
        if self._timer_surface is not None:
            timer_pos = (self.dim[0] // 2 - self._timer_surface.get_width() // 2, 50)
            timer_bg = pygame.Surface((self._timer_surface.get_width() + 20, self._timer_surface.get_height() + 10))
            timer_bg.fill((0, 0, 0))
            timer_bg.set_alpha(128)
            display.blit(timer_bg, (timer_pos[0] - 10, timer_pos[1] - 5))
            display.blit(self._timer_surface, timer_pos)


# ==============================================================================
# -- FadingText ----------------------------------------------------------------
# ==============================================================================


class FadingText(object):
    def __init__(self, font, dim, pos):
        self.font = font
        self.dim = dim
        self.pos = pos
        self.seconds_left = 0
        self.surface = pygame.Surface(self.dim)

    def set_text(self, text, color=(255, 255, 255), seconds=2.0):
        text_texture = self.font.render(text, True, color)
        self.surface = pygame.Surface(self.dim)
        self.seconds_left = seconds
        self.surface.fill((0, 0, 0, 0))
        self.surface.blit(text_texture, (10, 11))

    def tick(self, _, clock):
        delta_seconds = 1e-3 * clock.get_time()
        self.seconds_left = max(0.0, self.seconds_left - delta_seconds)
        self.surface.set_alpha(500.0 * self.seconds_left)

    def render(self, display):
        display.blit(self.surface, self.pos)


# ==============================================================================
# -- HelpText ------------------------------------------------------------------
# ==============================================================================


class HelpText(object):
    """Helper class to handle text output using pygame"""
    def __init__(self, font, width, height):
        lines = __doc__.split('\n')
        self.font = font
        self.line_space = 18
        self.dim = (780, len(lines) * self.line_space + 12)
        self.pos = (0.5 * width - 0.5 * self.dim[0], 0.5 * height - 0.5 * self.dim[1])
        self.seconds_left = 0
        self.surface = pygame.Surface(self.dim)
        self.surface.fill((0, 0, 0, 0))
        for n, line in enumerate(lines):
            text_texture = self.font.render(line, True, (255, 255, 255))
            self.surface.blit(text_texture, (22, n * self.line_space))
            self._render = False
        self.surface.set_alpha(220)

    def toggle(self):
        self._render = not self._render

    def render(self, display):
        if self._render:
            display.blit(self.surface, self.pos)


# ==============================================================================
# -- CollisionSensor -----------------------------------------------------------
# ==============================================================================


class CollisionSensor(object):
    def __init__(self, parent_actor, hud):
        self.sensor = None
        self.history = []
        self._parent = parent_actor
        self.hud = hud
        world = self._parent.get_world()
        bp = world.get_blueprint_library().find('sensor.other.collision')
        self.sensor = world.spawn_actor(bp, carla.Transform(), attach_to=self._parent)
        # We need to pass the lambda a weak reference to self to avoid circular
        # reference.
        weak_self = weakref.ref(self)
        self.sensor.listen(lambda event: CollisionSensor._on_collision(weak_self, event))

    def get_collision_history(self):
        history = collections.defaultdict(int)
        for frame, intensity in self.history:
            history[frame] += intensity
        return history

    @staticmethod
    def _on_collision(weak_self, event):
        self = weak_self()
        if not self:
            return
        actor_type = get_actor_display_name(event.other_actor)
        self.hud.notification('Collision with %r' % actor_type)
        impulse = event.normal_impulse
        intensity = math.sqrt(impulse.x**2 + impulse.y**2 + impulse.z**2)
        self.history.append((event.frame, intensity))
        if len(self.history) > 4000:
            self.history.pop(0)


# ==============================================================================
# -- LaneInvasionSensor --------------------------------------------------------
# ==============================================================================


class LaneInvasionSensor(object):
    def __init__(self, parent_actor, hud):
        self.sensor = None

        # If the spawn object is not a vehicle, we cannot use the Lane Invasion Sensor
        if parent_actor.type_id.startswith("vehicle."):
            self._parent = parent_actor
            self.hud = hud
            world = self._parent.get_world()
            bp = world.get_blueprint_library().find('sensor.other.lane_invasion')
            self.sensor = world.spawn_actor(bp, carla.Transform(), attach_to=self._parent)
            # We need to pass the lambda a weak reference to self to avoid circular
            # reference.
            weak_self = weakref.ref(self)
            self.sensor.listen(lambda event: LaneInvasionSensor._on_invasion(weak_self, event))

    @staticmethod
    def _on_invasion(weak_self, event):
        self = weak_self()
        if not self:
            return
        lane_types = set(x.type for x in event.crossed_lane_markings)
        text = ['%r' % str(x).split()[-1] for x in lane_types]
        self.hud.notification('Crossed line %s' % ' and '.join(text))


# ==============================================================================
# -- GnssSensor ----------------------------------------------------------------
# ==============================================================================


class GnssSensor(object):
    def __init__(self, parent_actor):
        self.sensor = None
        self._parent = parent_actor
        self.lat = 0.0
        self.lon = 0.0
        world = self._parent.get_world()
        bp = world.get_blueprint_library().find('sensor.other.gnss')
        self.sensor = world.spawn_actor(bp, carla.Transform(carla.Location(x=1.0, z=2.8)), attach_to=self._parent)
        # We need to pass the lambda a weak reference to self to avoid circular
        # reference.
        weak_self = weakref.ref(self)
        self.sensor.listen(lambda event: GnssSensor._on_gnss_event(weak_self, event))

    @staticmethod
    def _on_gnss_event(weak_self, event):
        self = weak_self()
        if not self:
            return
        self.lat = event.latitude
        self.lon = event.longitude


# ==============================================================================
# -- IMUSensor -----------------------------------------------------------------
# ==============================================================================


class IMUSensor(object):
    def __init__(self, parent_actor):
        self.sensor = None
        self._parent = parent_actor
        self.accelerometer = (0.0, 0.0, 0.0)
        self.gyroscope = (0.0, 0.0, 0.0)
        self.compass = 0.0
        world = self._parent.get_world()
        bp = world.get_blueprint_library().find('sensor.other.imu')
        self.sensor = world.spawn_actor(
            bp, carla.Transform(), attach_to=self._parent)
        # We need to pass the lambda a weak reference to self to avoid circular
        # reference.
        weak_self = weakref.ref(self)
        self.sensor.listen(
            lambda sensor_data: IMUSensor._IMU_callback(weak_self, sensor_data))

    @staticmethod
    def _IMU_callback(weak_self, sensor_data):
        self = weak_self()
        if not self:
            return
        limits = (-99.9, 99.9)
        self.accelerometer = (
            max(limits[0], min(limits[1], sensor_data.accelerometer.x)),
            max(limits[0], min(limits[1], sensor_data.accelerometer.y)),
            max(limits[0], min(limits[1], sensor_data.accelerometer.z)))
        self.gyroscope = (
            max(limits[0], min(limits[1], math.degrees(sensor_data.gyroscope.x))),
            max(limits[0], min(limits[1], math.degrees(sensor_data.gyroscope.y))),
            max(limits[0], min(limits[1], math.degrees(sensor_data.gyroscope.z))))
        self.compass = math.degrees(sensor_data.compass)


# ==============================================================================
# -- RadarSensor ---------------------------------------------------------------
# ==============================================================================


class RadarSensor(object):
    def __init__(self, parent_actor):
        self.sensor = None
        self._parent = parent_actor
        bound_x = 0.5 + self._parent.bounding_box.extent.x
        bound_y = 0.5 + self._parent.bounding_box.extent.y
        bound_z = 0.5 + self._parent.bounding_box.extent.z

        self.velocity_range = 7.5 # m/s
        world = self._parent.get_world()
        self.debug = world.debug
        bp = world.get_blueprint_library().find('sensor.other.radar')
        bp.set_attribute('horizontal_fov', str(35))
        bp.set_attribute('vertical_fov', str(20))
        self.sensor = world.spawn_actor(
            bp,
            carla.Transform(
                carla.Location(x=bound_x + 0.05, z=bound_z+0.05),
                carla.Rotation(pitch=5)),
            attach_to=self._parent)
        # We need a weak reference to self to avoid circular reference.
        weak_self = weakref.ref(self)
        self.sensor.listen(
            lambda radar_data: RadarSensor._Radar_callback(weak_self, radar_data))

    @staticmethod
    def _Radar_callback(weak_self, radar_data):
        self = weak_self()
        if not self:
            return
        # To get a numpy [[vel, altitude, azimuth, depth],...[,,,]]:
        # points = np.frombuffer(radar_data.raw_data, dtype=np.dtype('f4'))
        # points = np.reshape(points, (len(radar_data), 4))

        current_rot = radar_data.transform.rotation
        for detect in radar_data:
            azi = math.degrees(detect.azimuth)
            alt = math.degrees(detect.altitude)
            # The 0.25 adjusts a bit the distance so the dots can
            # be properly seen
            fw_vec = carla.Vector3D(x=detect.depth - 0.25)
            carla.Transform(
                carla.Location(),
                carla.Rotation(
                    pitch=current_rot.pitch + alt,
                    yaw=current_rot.yaw + azi,
                    roll=current_rot.roll)).transform(fw_vec)

            def clamp(min_v, max_v, value):
                return max(min_v, min(value, max_v))

            norm_velocity = detect.velocity / self.velocity_range # range [-1, 1]
            r = int(clamp(0.0, 1.0, 1.0 - norm_velocity) * 255.0)
            g = int(clamp(0.0, 1.0, 1.0 - abs(norm_velocity)) * 255.0)
            b = int(abs(clamp(- 1.0, 0.0, - 1.0 - norm_velocity)) * 255.0)
            self.debug.draw_point(
                radar_data.transform.location + fw_vec,
                size=0.075,
                life_time=0.06,
                persistent_lines=False,
                color=carla.Color(r, g, b))

# ==============================================================================
# -- CameraManager -------------------------------------------------------------
# ==============================================================================


class CameraManager(object):
    def __init__(self, parent_actor, hud, gamma_correction):
        self.sensor = None
        self.surface = None
        self._parent = parent_actor
        self.hud = hud
        self.recording = False
        self.data_dir = None
        self.csv_file = None
        self.csv_writer = None
        self.frame_count = 0
        self.recording_fps = 30  # Default FPS
        self.last_frame_time = 0
        self.minimap_sensor = None
        self.minimap_surface = None
        self.minimap_size = (320, 180)  # 1/4 of 1280x720
        self.map_overlay_size = (480, 480)  # Increased size by 20%
        self.map_surface = None
        self.map_waypoints = None
        self.map_boundaries = None
        self.traversed_positions = []  # Store traversed positions
        self.trail_surface = None  # Surface for the trail
        
        # Initialize the map overlay
        self._init_map_overlay()
        
        bound_x = 0.5 + self._parent.bounding_box.extent.x
        bound_y = 0.5 + self._parent.bounding_box.extent.y
        bound_z = 0.5 + self._parent.bounding_box.extent.z
        Attachment = carla.AttachmentType

        # Create data directory if it doesn't exist
        self.base_data_dir = Path("data")
        if not self.base_data_dir.exists():
            self.base_data_dir.mkdir(parents=True)

        if not self._parent.type_id.startswith("walker.pedestrian"):
            self._camera_transforms = [
                (carla.Transform(carla.Location(x=-2.0*bound_x, y=+0.0*bound_y, z=2.0*bound_z), carla.Rotation(pitch=8.0)), Attachment.SpringArmGhost),
                (carla.Transform(carla.Location(x=+0.8*bound_x, y=+0.0*bound_y, z=1.3*bound_z)), Attachment.Rigid),
                (carla.Transform(carla.Location(x=+1.9*bound_x, y=+1.0*bound_y, z=1.2*bound_z)), Attachment.SpringArmGhost),
                (carla.Transform(carla.Location(x=-2.8*bound_x, y=+0.0*bound_y, z=4.6*bound_z), carla.Rotation(pitch=6.0)), Attachment.SpringArmGhost),
                (carla.Transform(carla.Location(x=-1.0, y=-1.0*bound_y, z=0.4*bound_z)), Attachment.Rigid)]
        else:
            self._camera_transforms = [
                (carla.Transform(carla.Location(x=-2.5, z=0.0), carla.Rotation(pitch=-8.0)), Attachment.SpringArmGhost),
                (carla.Transform(carla.Location(x=1.6, z=1.7)), Attachment.Rigid),
                (carla.Transform(carla.Location(x=2.5, y=0.5, z=0.0), carla.Rotation(pitch=-8.0)), Attachment.SpringArmGhost),
                (carla.Transform(carla.Location(x=-4.0, z=2.0), carla.Rotation(pitch=6.0)), Attachment.SpringArmGhost),
                (carla.Transform(carla.Location(x=0, y=-2.5, z=-0.0), carla.Rotation(yaw=90.0)), Attachment.Rigid)]

        self.transform_index = 1
        self.sensors = [
            ['sensor.camera.rgb', cc.Raw, 'Camera RGB', {}],
            ['sensor.camera.depth', cc.Raw, 'Camera Depth (Raw)', {}],
            ['sensor.camera.depth', cc.Depth, 'Camera Depth (Gray Scale)', {}],
            ['sensor.camera.depth', cc.LogarithmicDepth, 'Camera Depth (Logarithmic Gray Scale)', {}],
            ['sensor.camera.semantic_segmentation', cc.Raw, 'Camera Semantic Segmentation (Raw)', {}],
            ['sensor.camera.semantic_segmentation', cc.CityScapesPalette, 'Camera Semantic Segmentation (CityScapes Palette)', {}],
            ['sensor.camera.instance_segmentation', cc.CityScapesPalette, 'Camera Instance Segmentation (CityScapes Palette)', {}],
            ['sensor.camera.instance_segmentation', cc.Raw, 'Camera Instance Segmentation (Raw)', {}],
            ['sensor.lidar.ray_cast', None, 'Lidar (Ray-Cast)', {'range': '50'}],
            ['sensor.camera.dvs', cc.Raw, 'Dynamic Vision Sensor', {}],
            ['sensor.camera.rgb', cc.Raw, 'Camera RGB Distorted',
                {'lens_circle_multiplier': '3.0',
                'lens_circle_falloff': '3.0',
                'chromatic_aberration_intensity': '0.5',
                'chromatic_aberration_offset': '0'}],
            ['sensor.camera.optical_flow', cc.Raw, 'Optical Flow', {}],
            ['sensor.camera.normals', cc.Raw, 'Camera Normals', {}],
        ]
        world = self._parent.get_world()
        bp_library = world.get_blueprint_library()
        for item in self.sensors:
            bp = bp_library.find(item[0])
            if item[0].startswith('sensor.camera'):
                bp.set_attribute('image_size_x', str(hud.dim[0]))
                bp.set_attribute('image_size_y', str(hud.dim[1]))
                if bp.has_attribute('gamma'):
                    bp.set_attribute('gamma', str(gamma_correction))
                for attr_name, attr_value in item[3].items():
                    bp.set_attribute(attr_name, attr_value)
            elif item[0].startswith('sensor.lidar'):
                self.lidar_range = 50

                for attr_name, attr_value in item[3].items():
                    bp.set_attribute(attr_name, attr_value)
                    if attr_name == 'range':
                        self.lidar_range = float(attr_value)

            item.append(bp)
        self.index = None

        # Setup minimap camera (bird's eye view)
        world = self._parent.get_world()
        bp = bp_library.find('sensor.camera.instance_segmentation')
        bp.set_attribute('image_size_x', str(self.minimap_size[0]))
        bp.set_attribute('image_size_y', str(self.minimap_size[1]))
        bp.set_attribute('fov', '90')
        if bp.has_attribute('gamma'):
            bp.set_attribute('gamma', str(gamma_correction))
            
        minimap_transform = carla.Transform(
            carla.Location(x=0, y=0, z=50.0),
            carla.Rotation(pitch=-90, yaw=0, roll=0))
        
        self.minimap_sensor = world.spawn_actor(bp, minimap_transform, attach_to=self._parent)
        weak_self = weakref.ref(self)
        self.minimap_sensor.listen(lambda image: CameraManager._parse_minimap_image(weak_self, image))

    def _init_map_overlay(self):
        """Initialize the map overlay with waypoints and boundaries."""
        world = self._parent.get_world()
        carla_map = world.get_map()
        
        # Get all waypoints with a fixed distance
        self.map_waypoints = carla_map.generate_waypoints(2.0)
        
        # Calculate map boundaries
        waypoints_loc = [wp.transform.location for wp in self.map_waypoints]
        min_x = min(wp.x for wp in waypoints_loc)
        max_x = max(wp.x for wp in waypoints_loc)
        min_y = min(wp.y for wp in waypoints_loc)
        max_y = max(wp.y for wp in waypoints_loc)
        
        # Add some padding
        padding = 50
        self.map_boundaries = {
            'min_x': min_x - padding,
            'max_x': max_x + padding,
            'min_y': min_y - padding,
            'max_y': max_y + padding
        }
        
        # Create the base map surface with alpha channel
        self.map_surface = pygame.Surface(self.map_overlay_size, pygame.SRCALPHA)
        self.map_surface.fill((0, 0, 0, 0))  # Fully transparent background
        
        # Create trail surface with alpha channel
        self.trail_surface = pygame.Surface(self.map_overlay_size, pygame.SRCALPHA)
        self.trail_surface.fill((0, 0, 0, 0))  # Fully transparent background
        
        self._draw_base_map()

    def _draw_base_map(self):
        """Draw the base map with all roads."""
        if not self.map_waypoints or not self.map_boundaries:
            return
            
        # Clear the surface with full transparency
        self.map_surface.fill((0, 0, 0, 0))
        
        # Draw roads with thicker lines and better colors
        for wp in self.map_waypoints:
            # Convert world coordinates to map overlay coordinates
            x, y = self._world_to_map_coords(wp.transform.location)
            
            # Draw road point with larger radius
            pygame.draw.circle(self.map_surface, (80, 80, 80, 153), (int(x), int(y)), 3)
            
            # Draw lane connections with thicker lines
            next_wps = wp.next(2.0)
            for next_wp in next_wps:
                next_x, next_y = self._world_to_map_coords(next_wp.transform.location)
                # Draw thick gray line for road
                pygame.draw.line(self.map_surface, (120, 120, 120, 153), 
                               (int(x), int(y)), 
                               (int(next_x), int(next_y)), 5)
                
                # Draw white line for lane markings
                if wp.lane_id * next_wp.lane_id > 0:  # Same direction lanes
                    pygame.draw.line(self.map_surface, (200, 200, 200, 153), 
                                   (int(x), int(y)), 
                                   (int(next_x), int(next_y)), 2)

    def _world_to_map_coords(self, location):
        """Convert world coordinates to map overlay coordinates."""
        x = (location.x - self.map_boundaries['min_x']) / \
            (self.map_boundaries['max_x'] - self.map_boundaries['min_x']) * self.map_overlay_size[0]
        y = (location.y - self.map_boundaries['min_y']) / \
            (self.map_boundaries['max_y'] - self.map_boundaries['min_y']) * self.map_overlay_size[1]
        return x, self.map_overlay_size[1] - y  # Flip y coordinate for pygame

    def _update_map_overlay(self):
        """Update the map overlay with current vehicle position and other vehicles."""
        if not self.map_surface:
            return
            
        # Create a copy of the base map with alpha channel
        current_map = pygame.Surface(self.map_overlay_size, pygame.SRCALPHA)
        current_map.fill((0, 0, 0, 0))  # Fully transparent background
        current_map.blit(self.map_surface, (0, 0))
        
        # Get vehicle position
        vehicle_location = self._parent.get_location()
        vehicle_x, vehicle_y = self._world_to_map_coords(vehicle_location)
        
        # Add current position to traversed positions
        self.traversed_positions.append((int(vehicle_x), int(vehicle_y)))
        if len(self.traversed_positions) > 1000:  # Limit trail length
            self.traversed_positions.pop(0)
        
        # Draw trail on trail surface
        if len(self.traversed_positions) > 1:
            pygame.draw.lines(self.trail_surface, (0, 255, 0, 80), False, 
                            self.traversed_positions, 2)
        
        # Blend trail with current map
        current_map.blit(self.trail_surface, (0, 0))
        
        # Draw other vehicles
        world = self._parent.get_world()
        for vehicle in world.get_actors().filter('vehicle.*'):
            if vehicle.id != self._parent.id:
                v_loc = vehicle.get_location()
                v_x, v_y = self._world_to_map_coords(v_loc)
                
                # Draw other vehicles as blue dots with direction indicators
                pygame.draw.circle(current_map, (50, 100, 255, 200), (int(v_x), int(v_y)), 3)
                
                # Draw vehicle direction
                v_transform = vehicle.get_transform()
                v_direction = v_transform.get_forward_vector()
                direction_x = v_x + v_direction.x * 8
                direction_y = v_y - v_direction.y * 8
                pygame.draw.line(current_map, (50, 100, 255, 200),
                               (int(v_x), int(v_y)),
                               (int(direction_x), int(direction_y)), 2)
        
        # Draw hero vehicle (with highlight effect)
        # Draw highlight circle
        pygame.draw.circle(current_map, (255, 255, 255, 100), (int(vehicle_x), int(vehicle_y)), 6)
        # Draw vehicle position
        pygame.draw.circle(current_map, (255, 50, 50, 220), (int(vehicle_x), int(vehicle_y)), 4)
        
        # Draw vehicle direction with arrow
        vehicle_transform = self._parent.get_transform()
        direction = vehicle_transform.get_forward_vector()
        direction_x = vehicle_x + direction.x * 12
        direction_y = vehicle_y - direction.y * 12
        
        # Draw direction line
        pygame.draw.line(current_map, (255, 50, 50, 220),
                        (int(vehicle_x), int(vehicle_y)),
                        (int(direction_x), int(direction_y)), 2)
        
        return current_map

    def toggle_camera(self):
        self.transform_index = (self.transform_index + 1) % len(self._camera_transforms)
        self.set_sensor(self.index, notify=False, force_respawn=True)
        print(self.transform_index)

    def set_sensor(self, index, notify=True, force_respawn=False):
        index = index % len(self.sensors)
        needs_respawn = True if self.index is None else \
            (force_respawn or (self.sensors[index][2] != self.sensors[self.index][2]))
        if needs_respawn:
            if self.sensor is not None:
                self.sensor.destroy()
                self.surface = None
            self.sensor = self._parent.get_world().spawn_actor(
                self.sensors[index][-1],
                self._camera_transforms[self.transform_index][0],
                attach_to=self._parent,
                attachment_type=self._camera_transforms[self.transform_index][1])
            # We need to pass the lambda a weak reference to self to avoid
            # circular reference.
            weak_self = weakref.ref(self)
            self.sensor.listen(lambda image: CameraManager._parse_image(weak_self, image))
        if notify:
            self.hud.notification(self.sensors[index][2])
        self.index = index

    def next_sensor(self):
        self.set_sensor(self.index + 1)

    def toggle_recording(self):
        self.recording = not self.recording
        if self.recording:
            # Create new data directory with timestamp
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            self.data_dir = Path("data") / f"session_{timestamp}"
            self.data_dir.mkdir(parents=True, exist_ok=True)
            
            # Create and open CSV file for metadata
            self.csv_file = open(self.data_dir / "metadata.csv", 'w', newline='')
            self.csv_writer = csv.writer(self.csv_file)
            
            # Write header matching record.py format
            self.csv_writer.writerow([
                'frame', 'timestamp',
                'location_x', 'location_y', 'location_z',
                'rotation_pitch', 'rotation_yaw', 'rotation_roll',
                'velocity_x', 'velocity_y', 'velocity_z',
                'road_angle',
                'toMarking_LL', 'toMarking_ML', 'toMarking_MR', 'toMarking_RR',
                'dist_LL', 'dist_MM', 'dist_RR',
                'toMarking_L', 'toMarking_M', 'toMarking_R',
                'dist_L', 'dist_R',
                'image_path'
            ])
        else:
            # Close CSV file if it's open
            if self.csv_file:
                self.csv_file.close()
                self.csv_file = None
                self.csv_writer = None
                self.frame_count = 0
                self.last_frame_time = 0
        
        self.hud.notification('Recording %s' % ('On' if self.recording else 'Off'))

    @staticmethod
    def _parse_image(weak_self, image):
        self = weak_self()
        if not self:
            return
        if self.sensors[self.index][0].startswith('sensor.lidar'):
            points = np.frombuffer(image.raw_data, dtype=np.dtype('f4'))
            points = np.reshape(points, (int(points.shape[0] / 4), 4))
            lidar_data = np.array(points[:, :2])
            lidar_data *= min(self.hud.dim) / (2.0 * self.lidar_range)
            lidar_data += (0.5 * self.hud.dim[0], 0.5 * self.hud.dim[1])
            lidar_data = np.fabs(lidar_data)
            lidar_data = lidar_data.astype(np.int32)
            lidar_data = np.reshape(lidar_data, (-1, 2))
            lidar_img_size = (self.hud.dim[0], self.hud.dim[1], 3)
            lidar_img = np.zeros((lidar_img_size), dtype=np.uint8)
            lidar_img[tuple(lidar_data.T)] = (255, 255, 255)
            self.surface = pygame.surfarray.make_surface(lidar_img)
        else:
            image.convert(self.sensors[self.index][1])
            array = np.frombuffer(image.raw_data, dtype=np.dtype("uint8"))
            array = np.reshape(array, (image.height, image.width, 4))
            array = array[:, :, :3]
            array = array[:, :, ::-1]
            self.surface = pygame.surfarray.make_surface(array.swapaxes(0, 1))

        if self.recording and self.data_dir:
            # Check if we should save this frame based on FPS
            current_time = time.time()
            if current_time - self.last_frame_time >= 1.0 / self.recording_fps:
                # Save frame as JPG with 85% quality using OpenCV
                filename = f"frame_{image.frame:08d}.jpg"
                image_path = self.data_dir / filename
                
                # Convert CARLA image to numpy array for OpenCV
                array = np.frombuffer(image.raw_data, dtype=np.dtype("uint8"))
                array = np.reshape(array, (image.height, image.width, 4))
                array = array[:, :, :3]  # Remove alpha channel
                
                # Save using OpenCV with 85% quality
                cv2.imwrite(str(image_path), array, [cv2.IMWRITE_JPEG_QUALITY, 85])
                
                # Get vehicle state
                vehicle = self._parent
                world = vehicle.get_world()
                transform = vehicle.get_transform()
                velocity = vehicle.get_velocity()
                
                # Get lane metrics using the updated function
                metrics = get_lane_metrics(vehicle, world)
                
                # Write metadata to CSV matching record.py format
                if self.csv_writer:
                    self.frame_count += 1
                    
                    metadata = [
                        self.frame_count, image.timestamp,
                        # Location
                        transform.location.x, transform.location.y, transform.location.z,
                        # Rotation
                        transform.rotation.pitch, transform.rotation.yaw, transform.rotation.roll,
                        # Velocity
                        velocity.x, velocity.y, velocity.z,
                        # Road angle
                        metrics['angle'],
                        # Lane marking distances
                        metrics['in_lane']['toMarking_LL'], metrics['in_lane']['toMarking_ML'],
                        metrics['in_lane']['toMarking_MR'], metrics['in_lane']['toMarking_RR'],
                        # Lane distances
                        metrics['in_lane']['dist_LL'], metrics['in_lane']['dist_MM'],
                        metrics['in_lane']['dist_RR'],
                        # Adjacent lane markings
                        metrics['on_marking']['toMarking_L'], metrics['on_marking']['toMarking_M'],
                        metrics['on_marking']['toMarking_R'],
                        # Adjacent lane distances
                        metrics['on_marking']['dist_L'], metrics['on_marking']['dist_R'],
                        # Image path
                        filename
                    ]
                    
                    self.csv_writer.writerow(metadata)
                    
                    # Flush periodically to avoid data loss
                    if self.frame_count % 10 == 0:
                        self.csv_file.flush()
                
                # Update last frame time
                self.last_frame_time = current_time

    def destroy_sensors(self):
        try:
            if self.sensor is not None:
                if self.sensor.is_alive:
                    self.sensor.stop()
                    self.sensor.destroy()
                self.sensor = None
            if self.minimap_sensor is not None:
                if self.minimap_sensor.is_alive:
                    self.minimap_sensor.stop()
                    self.minimap_sensor.destroy()
                self.minimap_sensor = None
            self.surface = None
            self.minimap_surface = None
            self.index = None
        except Exception as e:
            print(f"Warning: Error during sensor cleanup: {e}")

    @staticmethod
    def _parse_minimap_image(weak_self, image):
        self = weak_self()
        if not self:
            return
            
        # Convert the segmentation image to a colored visualization
        array = np.frombuffer(image.raw_data, dtype=np.dtype("uint8"))
        array = np.reshape(array, (image.height, image.width, 4))
        
        # Extract the semantic tags (stored in the red channel)
        array = array[:, :, 2]
        
        # Create an RGB array for the colored visualization
        result = np.zeros((array.shape[0], array.shape[1], 3), dtype=np.uint8)
        
        # Apply CityScapes-like color palette
        # Road - dark gray
        result[array == 7] = [128, 128, 128]
        # Sidewalk - light gray
        result[array == 8] = [192, 192, 192]
        # Vehicles - red
        result[array == 10] = [255, 0, 0]
        # Buildings - dark blue
        result[array == 1] = [70, 70, 190]
        # Vegetation - green
        result[array == 9] = [0, 175, 0]
        # Ground - brown
        result[array == 14] = [145, 105, 82]
        
        # Convert to pygame surface
        self.minimap_surface = pygame.surfarray.make_surface(result.swapaxes(0, 1))

    def render(self, display):
        if self.surface is not None:
            display.blit(self.surface, (0, 0))
            
        # Render minimap in top-right corner with a border
        if self.minimap_surface is not None:
            minimap_pos = (display.get_width() - self.minimap_size[0] - 10, 10)
            
            # Draw a black background for the border
            pygame.draw.rect(display, (0, 0, 0), 
                           (minimap_pos[0] - 2, minimap_pos[1] - 2,
                            self.minimap_size[0] + 4, self.minimap_size[1] + 4))
            
            # Draw semi-transparent background
            minimap_bg = pygame.Surface(self.minimap_size)
            minimap_bg.fill((0, 0, 0))
            minimap_bg.set_alpha(200)
            display.blit(minimap_bg, minimap_pos)
            
            # Draw the minimap
            display.blit(self.minimap_surface, minimap_pos)
            
        # Render map overlay in bottom-right corner
        current_map = self._update_map_overlay()
        if current_map is not None:
            # Position the map overlay closer to the corner (5 pixels from edge instead of 10)
            map_pos = (display.get_width() - self.map_overlay_size[0] - 5,
                      display.get_height() - self.map_overlay_size[1] - 5)
            
            # Draw the map overlay directly without border
            display.blit(current_map, map_pos)


# ==============================================================================
# -- game_loop() ---------------------------------------------------------------
# ==============================================================================


def game_loop(args):
    pygame.init()
    pygame.font.init()
    world = None
    original_settings = None
    should_quit = False  # Initialize should_quit variable

    try:
        client = carla.Client(args.host, args.port)
        client.set_timeout(2000.0)

        sim_world = client.get_world()
        if args.sync:
            original_settings = sim_world.get_settings()
            settings = sim_world.get_settings()
            if not settings.synchronous_mode:
                settings.synchronous_mode = True
                settings.fixed_delta_seconds = 0.05
            sim_world.apply_settings(settings)

            traffic_manager = client.get_trafficmanager()
            traffic_manager.set_synchronous_mode(True)

        if args.autopilot and not sim_world.get_settings().synchronous_mode:
            print("WARNING: You are currently in asynchronous mode and could "
                  "experience some issues with the traffic simulation")

        # Set weather
        weather_presets = {
            'Clear Night': carla.WeatherParameters.ClearNight,
            'Clear Noon': carla.WeatherParameters.ClearNoon,
            'Clear Sunset': carla.WeatherParameters.ClearSunset,
            'Cloudy Night': carla.WeatherParameters.CloudyNight,
            'Cloudy Noon': carla.WeatherParameters.CloudyNoon,
            'Cloudy Sunset': carla.WeatherParameters.CloudySunset,
            'Default': carla.WeatherParameters.Default,
            'Dust Storm': carla.WeatherParameters.DustStorm,
            'Hard Rain Night': carla.WeatherParameters.HardRainNight,
            'Hard Rain Noon': carla.WeatherParameters.HardRainNoon,
            'Hard Rain Sunset': carla.WeatherParameters.HardRainSunset,
            'Mid Rain Sunset': carla.WeatherParameters.MidRainSunset,
            'Mid Rainy Night': carla.WeatherParameters.MidRainyNight,
            'Mid Rainy Noon': carla.WeatherParameters.MidRainyNoon,
            'Soft Rain Night': carla.WeatherParameters.SoftRainNight,
            'Soft Rain Noon': carla.WeatherParameters.SoftRainNoon,
            'Soft Rain Sunset': carla.WeatherParameters.SoftRainSunset,
            'Wet Cloudy Night': carla.WeatherParameters.WetCloudyNight,
            'Wet Cloudy Noon': carla.WeatherParameters.WetCloudyNoon,
            'Wet Cloudy Sunset': carla.WeatherParameters.WetCloudySunset,
            'Wet Night': carla.WeatherParameters.WetNight,
            'Wet Noon': carla.WeatherParameters.WetNoon,
            'Wet Sunset': carla.WeatherParameters.WetSunset
        }
        sim_world.set_weather(weather_presets[args.weather])

        # Clear all existing vehicles first
        print("Clearing existing vehicles...")
        for actor in sim_world.get_actors().filter('vehicle.*'):
            actor.destroy()
        print("All existing vehicles cleared")

        display = pygame.display.set_mode(
            (args.width, args.height),
            pygame.HWSURFACE | pygame.DOUBLEBUF)
        display.fill((0,0,0))
        pygame.display.flip()

        hud = HUD(args.width, args.height)
        world = World(sim_world, hud, args)
        
        # Set camera to interior view (transform index 1)
        world.camera_manager.transform_index = 1
        world.camera_manager.set_sensor(0, notify=False)
        
        # Set recording FPS
        world.camera_manager.recording_fps = args.recording_fps

        # Spawn additional AI vehicles if requested
        if args.vehicles > 0:
            # Get spawn points
            spawn_points = sim_world.get_map().get_spawn_points()
            
            # Get all available vehicle blueprints
            vehicle_blueprints = sim_world.get_blueprint_library().filter('vehicle.*')
            # Filter out bikes, bicycles, and special vehicles
            vehicle_blueprints = [bp for bp in vehicle_blueprints if int(bp.get_attribute('number_of_wheels')) == 4]
            
            # Set up traffic manager
            tm = client.get_trafficmanager()
            tm.set_global_distance_to_leading_vehicle(2.5)  # Safer following distance
            tm.set_hybrid_physics_mode(True)  # Enable hybrid mode for better performance
            tm.set_synchronous_mode(True)
            
            # Global traffic manager settings
            tm.global_percentage_speed_difference(-20.0)  # Drive slower
            tm.set_hybrid_physics_radius(50.0)  # Hybrid physics radius
            
            # Spawn vehicles
            for i in range(args.vehicles):
                if spawn_points:
                    spawn_point = spawn_points.pop(0) if spawn_points else None
                    if spawn_point:
                        # Randomly select a vehicle blueprint
                        blueprint = random.choice(vehicle_blueprints)
                        
                        # Randomize the color
                        if blueprint.has_attribute('color'):
                            color = random.choice(blueprint.get_attribute('color').recommended_values)
                            blueprint.set_attribute('color', color)
                        
                        # Try to spawn the vehicle
                        vehicle = sim_world.try_spawn_actor(blueprint, spawn_point)
                        if vehicle:
                            vehicle.set_autopilot(True)
                            
                            # Per-vehicle traffic manager settings
                            tm.update_vehicle_lights(vehicle, True)  # Enable lights
                            tm.distance_to_leading_vehicle(vehicle, 4.0)  # Increased following distance
                            tm.vehicle_percentage_speed_difference(vehicle, -15.0)  # Slightly slower
                            tm.random_left_lanechange_percentage(vehicle, 0.0)  # Disable lane changes
                            tm.random_right_lanechange_percentage(vehicle, 0.0)  # Disable lane changes
                            tm.auto_lane_change(vehicle, False)  # Disable automatic lane changes
                            tm.ignore_vehicles_percentage(vehicle, 0.0)  # Don't ignore any vehicles
                            tm.ignore_lights_percentage(vehicle, 0.0)  # Don't ignore traffic lights
                            tm.ignore_signs_percentage(vehicle, 0.0)  # Don't ignore traffic signs
                            tm.ignore_walkers_percentage(vehicle, 0.0)  # Don't ignore pedestrians

        controller = KeyboardControl(world, args.autopilot)

        if args.sync:
            sim_world.tick()
        else:
            sim_world.wait_for_tick()

        # Start recording if requested
        if args.record:
            world.camera_manager.toggle_recording()
            world.hud.notification("Recording started automatically")

        clock = pygame.time.Clock()
        while True:
            if args.sync:
                sim_world.tick()
            clock.tick_busy_loop(60)
            if controller.parse_events(client, world, clock, args.sync):
                return
            # Check if timer-based quit is requested and handle it
            should_quit = world.tick(clock)
            if should_quit:
                print("\nQuitting application due to timer expiration...")
                break
            world.render(display)
            pygame.display.flip()

    finally:
        if original_settings:
            sim_world.apply_settings(original_settings)

        if (world and world.recording_enabled):
            client.stop_recorder()

        if world is not None:
            world.destroy()

        pygame.quit()
        if should_quit:
            sys.exit(0)  # Ensure the application fully exits


# ==============================================================================
# -- main() --------------------------------------------------------------------
# ==============================================================================


def main():
    argparser = argparse.ArgumentParser(
        description='CARLA Manual Control Client')
    argparser.add_argument(
        '-v', '--verbose',
        action='store_true',
        dest='debug',
        help='print debug information')
    argparser.add_argument(
        '--host',
        metavar='H',
        default='127.0.0.1',
        help='IP of the host server (default: 127.0.0.1)')
    argparser.add_argument(
        '-p', '--port',
        metavar='P',
        default=2000,
        type=int,
        help='TCP port to listen to (default: 2000)')
    argparser.add_argument(
        '-a', '--autopilot',
        action='store_true',
        help='enable autopilot')
    argparser.add_argument(
        '--res',
        metavar='WIDTHxHEIGHT',
        default='1280x720',
        help='window resolution (default: 1280x720)')
    argparser.add_argument(
        '--filter',
        metavar='PATTERN',
        default='vehicle.dodge.charger_2020',
        help='actor filter (default: "vehicle.dodge.charger_2020")')
    argparser.add_argument(
        '--generation',
        metavar='G',
        default='2',
        help='restrict to certain actor generation (values: "1","2","All" - default: "2")')
    argparser.add_argument(
        '--rolename',
        metavar='NAME',
        default='hero',
        help='actor role name (default: "hero")')
    argparser.add_argument(
        '--gamma',
        default=2.2,
        type=float,
        help='Gamma correction of the camera (default: 2.2)')
    argparser.add_argument(
        '--sync',
        action='store_true',
        help='Activate synchronous mode execution')
    argparser.add_argument(
        '--vehicles',
        type=int,
        default=0,
        help='Number of AI vehicles to spawn (default: 0)')
    argparser.add_argument(
        '--weather',
        type=str,
        default='Default',
        choices=[
            'Clear Night', 'Clear Noon', 'Clear Sunset',
            'Cloudy Night', 'Cloudy Noon', 'Cloudy Sunset',
            'Default', 'Dust Storm',
            'Hard Rain Night', 'Hard Rain Noon', 'Hard Rain Sunset',
            'Mid Rain Sunset', 'Mid Rainy Night', 'Mid Rainy Noon',
            'Soft Rain Night', 'Soft Rain Noon', 'Soft Rain Sunset',
            'Wet Cloudy Night', 'Wet Cloudy Noon', 'Wet Cloudy Sunset',
            'Wet Night', 'Wet Noon', 'Wet Sunset'
        ],
        help='Set the weather condition')
    argparser.add_argument(
        '-r', '--record',
        action='store_true',
        help='Start recording automatically when launching')
    argparser.add_argument(
        '--recording-fps',
        type=int,
        default=30,
        help='Number of frames to record per second (default: 30)')
    argparser.add_argument(
        '-t', '--timer',
        type=int,
        default=0,
        help='Timer in seconds for recording duration (default: 0 means no timer)')
    argparser.add_argument(
        '-tq', '--timer-quit',
        action='store_true',
        help='Quit after timer expires (only works with --timer)')
    argparser.add_argument(
        '--traverse-map',
        action='store_true',
        help='Enable systematic traversal of the entire map while following traffic rules')
    argparser.add_argument(
        '--map',
        metavar='MAPNAME',
        default=None,
        help='Load a specific map (e.g., "Town01", "Town02", etc.)')
    argparser.add_argument(
        '--coverage',
        type=float,
        default=85.0,
        help='Map coverage threshold percentage to stop simulation (default: 85.0)')
    
    args = argparser.parse_args()

    args.width, args.height = [int(x) for x in args.res.split('x')]

    log_level = logging.DEBUG if args.debug else logging.INFO
    logging.basicConfig(format='%(levelname)s: %(message)s', level=log_level)

    logging.info('listening to server %s:%s', args.host, args.port)

    print(__doc__)

    try:
        # Create a client and retrieve the current world
        client = carla.Client(args.host, args.port)
        client.set_timeout(10.0)

        # Change map if specified
        if args.map:
            print(f'Loading map {args.map}...')
            try:
                # Get available maps
                available_maps = client.get_available_maps()
                # Find the requested map
                requested_map = next((m for m in available_maps if args.map.lower() in m.lower()), None)
                
                if requested_map:
                    client.load_world(requested_map)
                    print(f'Map {requested_map} loaded successfully')
                else:
                    print(f'ERROR: Map {args.map} not found. Available maps:')
                    for m in available_maps:
                        print(f'  - {m.split("/")[-1]}')
                    return
            except Exception as e:
                print(f'ERROR: Failed to load map {args.map}: {str(e)}')
                return

        game_loop(args)

    except KeyboardInterrupt:
        print('\nCancelled by user. Bye!')

if __name__ == '__main__':
    main()
