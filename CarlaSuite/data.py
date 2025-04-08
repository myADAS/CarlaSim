import numpy as np
import cv2
import os
import csv
import logging
import time
import threading
import queue
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

class CarlaDataProcessor:
    """Processes and manages CARLA sensor data"""
    
    def __init__(self, output_dir: str):
        """
        Initialize the data processor
        
        Args:
            output_dir: Base directory for output data
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # Processing queues
        self.image_queue = queue.Queue(maxsize=100)
        self.lidar_queue = queue.Queue(maxsize=100)
        self.metadata_queue = queue.Queue(maxsize=100)
        
        # Processing threads
        self.threads = []
        self.stop_event = threading.Event()
        
        # Session info
        self.session_id = time.strftime("%Y%m%d_%H%M%S")
        self.session_dir = self.output_dir / f"session_{self.session_id}"
        self.session_dir.mkdir(exist_ok=True)
    
    def start_processing_threads(self, num_threads=3):
        """Start data processing threads"""
        # Image processing thread
        image_thread = threading.Thread(target=self._process_images)
        image_thread.daemon = True
        image_thread.start()
        self.threads.append(image_thread)
        
        # LiDAR processing thread
        lidar_thread = threading.Thread(target=self._process_lidar)
        lidar_thread.daemon = True
        lidar_thread.start()
        self.threads.append(lidar_thread)
        
        # Metadata processing thread
        metadata_thread = threading.Thread(target=self._process_metadata)
        metadata_thread.daemon = True
        metadata_thread.start()
        self.threads.append(metadata_thread)
        
        logging.info(f"Started {len(self.threads)} data processing threads")
    
    def queue_image(self, image_data, vehicle_name, frame_id, image_type='rgb'):
        """Queue an image for processing"""
        try:
            self.image_queue.put({
                'data': image_data,
                'vehicle': vehicle_name,
                'frame': frame_id,
                'type': image_type
            }, block=False)
        except queue.Full:
            logging.warning(f"Image queue full, dropping frame {frame_id} from {vehicle_name}")
    
    def queue_lidar(self, lidar_data, vehicle_name, frame_id):
        """Queue LiDAR data for processing"""
        try:
            self.lidar_queue.put({
                'data': lidar_data,
                'vehicle': vehicle_name,
                'frame': frame_id
            }, block=False)
        except queue.Full:
            logging.warning(f"LiDAR queue full, dropping frame {frame_id} from {vehicle_name}")
    
    def queue_metadata(self, metadata, vehicle_name, frame_id):
        """Queue metadata for processing"""
        try:
            self.metadata_queue.put({
                'data': metadata,
                'vehicle': vehicle_name,
                'frame': frame_id
            }, block=False)
        except queue.Full:
            logging.warning(f"Metadata queue full, dropping frame {frame_id} from {vehicle_name}")
    
    def _process_images(self):
        """Process images from the queue"""
        while not self.stop_event.is_set():
            try:
                # Get image with timeout
                item = self.image_queue.get(timeout=1.0)
                
                # Create vehicle directory if needed
                vehicle_dir = self.session_dir / item['vehicle']
                vehicle_dir.mkdir(exist_ok=True)
                
                # Create image type directory if needed
                image_type_dir = vehicle_dir / item['type']
                image_type_dir.mkdir(exist_ok=True)
                
                # Process based on image type
                if item['type'] == 'rgb':
                    # Convert image to numpy array
                    array = np.frombuffer(item['data'].raw_data, dtype=np.dtype("uint8"))
                    array = np.reshape(array, (item['data'].height, item['data'].width, 4))
                    array = array[:, :, :3]  # Remove alpha channel
                    
                    # Save image
                    filename = image_type_dir / f"frame_{item['frame']:06d}.jpg"
                    cv2.imwrite(str(filename), array[:, :, ::-1])  # BGR to RGB
                    
                elif item['type'] == 'depth':
                    # Convert depth image to numpy array
                    array = np.frombuffer(item['data'].raw_data, dtype=np.dtype("uint8"))
                    array = np.reshape(array, (item['data'].height, item['data'].width, 4))
                    
                    # Convert BGRA to depth map
                    depth_map = array[:, :, 2] + array[:, :, 1] * 256 + array[:, :, 0] * 256 * 256
                    depth_map = depth_map.astype(np.float32) / (256 * 256 * 256 - 1)
                    depth_map = depth_map * 1000  # Convert to meters
                    
                    # Save depth map
                    filename = image_type_dir / f"frame_{item['frame']:06d}.npy"
                    np.save(str(filename), depth_map)
                
                # Mark task as done
                self.image_queue.task_done()
                
            except queue.Empty:
                continue
            except Exception as e:
                logging.error(f"Error processing image: {str(e)}")
    
    def _process_lidar(self):
        """Process LiDAR data from the queue"""
        while not self.stop_event.is_set():
            try:
                # Get LiDAR data with timeout
                item = self.lidar_queue.get(timeout=1.0)
                
                # Create vehicle directory if needed
                vehicle_dir = self.session_dir / item['vehicle']
                vehicle_dir.mkdir(exist_ok=True)
                
                # Create LiDAR directory if needed
                lidar_dir = vehicle_dir / 'lidar'
                lidar_dir.mkdir(exist_ok=True)
                
                # Get point cloud data
                points = np.frombuffer(item['data'].raw_data, dtype=np.dtype('f4'))
                points = np.reshape(points, (-1, 4))
                
                # Save point cloud
                filename = lidar_dir / f"frame_{item['frame']:06d}.npy"
                np.save(str(filename), points)
                
                # Mark task as done
                self.lidar_queue.task_done()
                
            except queue.Empty:
                continue
            except Exception as e:
                logging.error(f"Error processing LiDAR data: {str(e)}")
    
    def _process_metadata(self):
        """Process metadata from the queue"""
        # CSV files for each vehicle
        csv_files = {}
        
        while not self.stop_event.is_set():
            try:
                # Get metadata with timeout
                item = self.metadata_queue.get(timeout=1.0)
                
                # Create vehicle directory if needed
                vehicle_dir = self.session_dir / item['vehicle']
                vehicle_dir.mkdir(exist_ok=True)
                
                # Create or get CSV file
                if item['vehicle'] not in csv_files:
                    csv_path = vehicle_dir / 'metadata.csv'
                    is_new_file = not csv_path.exists()
                    
                    csv_file = open(csv_path, 'a', newline='')
                    csv_writer = csv.writer(csv_file)
                    
                    # Write header if new file
                    if is_new_file:
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
                    
                    csv_files[item['vehicle']] = {
                        'file': csv_file,
                        'writer': csv_writer,
                        'last_flush': time.time()
                    }
                
                # Write metadata row
                metadata = item['data']
                csv_files[item['vehicle']]['writer'].writerow([
                    item['frame'], metadata['timestamp'],
                    metadata['pos_x'], metadata['pos_y'], metadata['pos_z'],
                    metadata['rot_pitch'], metadata['rot_yaw'], metadata['rot_roll'],
                    metadata['vel_x'], metadata['vel_y'], metadata['vel_z'],
                    metadata['ang_vel_x'], metadata['ang_vel_y'], metadata['ang_vel_z'],
                    metadata['acc_x'], metadata['acc_y'], metadata['acc_z'],
                    metadata['throttle'], metadata['steer'], metadata['brake'], 
                    metadata['handbrake'], metadata['reverse'],
                    metadata['gear'], metadata['rpm'], metadata['speed_kmh']
                ])
                
                # Flush periodically
                now = time.time()
                if now - csv_files[item['vehicle']]['last_flush'] > 5.0:
                    csv_files[item['vehicle']]['file'].flush()
                    csv_files[item['vehicle']]['last_flush'] = now
                
                # Mark task as done
                self.metadata_queue.task_done()
                
            except queue.Empty:
                continue
            except Exception as e:
                logging.error(f"Error processing metadata: {str(e)}")
    
    def stop(self):
        """Stop all processing threads"""
        self.stop_event.set()
        
        # Wait for threads to finish
        for thread in self.threads:
            if thread.is_alive():
                thread.join(timeout=2.0)
        
        # Close any open CSV files
        for vehicle_name in list(self._csv_files.keys()):
            try:
                self._csv_files[vehicle_name]['file'].close()
            except:
                pass
        
        logging.info("Data processor stopped")