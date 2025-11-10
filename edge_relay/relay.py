"""
Edge relay application - runs locally to forward LSL streams to cloud.

This lightweight service:
1. Reads LSL stream from local EEG device
2. Optionally preprocesses signals (filtering, feature extraction)
3. Compresses and sends data to cloud via WebSocket
4. Handles reconnection and buffering
"""

import asyncio
import time
import json
from datetime import datetime
from typing import Optional, Dict, Any
from collections import deque
import numpy as np

try:
    from pylsl import StreamInlet, resolve_byprop
    PYLSL_AVAILABLE = True
except ImportError:
    PYLSL_AVAILABLE = False
    print("WARNING: pylsl not available. Install with: pip install pylsl")

try:
    import msgpack
    MSGPACK_AVAILABLE = True
except ImportError:
    MSGPACK_AVAILABLE = False
    print("WARNING: msgpack not available. Install with: pip install msgpack")

import websockets
from websockets.client import WebSocketClientProtocol
import yaml


class EdgeRelay:
    """Forwards LSL streams to cloud WebSocket server."""

    def __init__(self, config_path: str = "edge_relay_config.yaml"):
        """
        Initialize edge relay.

        Args:
            config_path: Path to configuration file
        """
        with open(config_path, 'r') as f:
            self.config = yaml.safe_load(f)

        self.lsl_stream_name = self.config['lsl']['stream_name']
        self.cloud_endpoint = self.config['cloud']['endpoint']
        self.api_key = self.config['cloud']['api_key']
        self.user_id = self.config['cloud'].get('user_id', 'default_user')

        self.preprocessing_enabled = self.config.get('preprocessing', {}).get('enabled', False)
        self.buffer_size = self.config.get('buffer', {}).get('size', 1000)
        self.compression = self.config.get('compression', 'msgpack')

        # Local buffer for when cloud is disconnected
        self.buffer = deque(maxlen=self.buffer_size)

        # Connection state
        self.ws: Optional[WebSocketClientProtocol] = None
        self.lsl_inlet: Optional[StreamInlet] = None
        self.connected = False
        self.running = False

        print(f"Edge Relay initialized")
        print(f"  LSL stream: {self.lsl_stream_name}")
        print(f"  Cloud endpoint: {self.cloud_endpoint}")
        print(f"  Preprocessing: {self.preprocessing_enabled}")

    async def connect_lsl(self):
        """Connect to local LSL stream."""
        if not PYLSL_AVAILABLE:
            raise RuntimeError("pylsl not available - cannot connect to LSL stream")

        print(f"Searching for LSL stream: {self.lsl_stream_name}...")
        streams = resolve_byprop("name", self.lsl_stream_name, timeout=10.0)

        if not streams:
            raise RuntimeError(f"LSL stream '{self.lsl_stream_name}' not found")

        self.lsl_inlet = StreamInlet(streams[0])
        info = self.lsl_inlet.info()

        print(f"Connected to LSL stream:")
        print(f"  Name: {info.name()}")
        print(f"  Type: {info.type()}")
        print(f"  Channels: {info.channel_count()}")
        print(f"  Sampling rate: {info.nominal_srate()} Hz")

        return {
            "name": info.name(),
            "type": info.type(),
            "channel_count": info.channel_count(),
            "sampling_rate": info.nominal_srate(),
        }

    async def connect_cloud(self):
        """Connect to cloud WebSocket server."""
        print(f"Connecting to cloud: {self.cloud_endpoint}...")

        headers = {
            "X-API-Key": self.api_key,
            "X-User-ID": self.user_id,
        }

        try:
            self.ws = await websockets.connect(
                self.cloud_endpoint,
                extra_headers=headers,
                ping_interval=30,
                ping_timeout=10,
            )
            self.connected = True
            print("Connected to cloud successfully")
        except Exception as e:
            print(f"Failed to connect to cloud: {e}")
            raise

    async def send_data(self, data: Dict[str, Any]):
        """
        Send data to cloud with compression.

        Args:
            data: Dictionary to send
        """
        if not self.connected or not self.ws:
            # Buffer data if not connected
            self.buffer.append(data)
            return

        try:
            # Serialize and compress
            if self.compression == 'msgpack' and MSGPACK_AVAILABLE:
                payload = msgpack.packb(data, use_bin_type=True)
            else:
                payload = json.dumps(data).encode('utf-8')

            await self.ws.send(payload)

        except Exception as e:
            print(f"Error sending data: {e}")
            self.connected = False
            self.buffer.append(data)

    async def flush_buffer(self):
        """Send buffered data to cloud after reconnection."""
        if not self.buffer:
            return

        print(f"Flushing {len(self.buffer)} buffered samples...")
        while self.buffer and self.connected:
            data = self.buffer.popleft()
            await self.send_data(data)
            await asyncio.sleep(0.001)  # Rate limit

        print("Buffer flushed")

    def preprocess_sample(self, sample: list, timestamp: float) -> Dict[str, Any]:
        """
        Optionally preprocess EEG sample before sending.

        If preprocessing is disabled, sends raw samples.
        If enabled, extracts features to reduce bandwidth.

        Args:
            sample: LSL sample data
            timestamp: LSL timestamp

        Returns:
            Dictionary with processed data
        """
        if not self.preprocessing_enabled:
            # Send raw sample
            return {
                "type": "raw_sample",
                "timestamp": timestamp,
                "data": sample,
                "user_id": self.user_id,
            }

        # TODO: Implement feature extraction here
        # For now, just send raw
        return {
            "type": "raw_sample",
            "timestamp": timestamp,
            "data": sample,
            "user_id": self.user_id,
        }

    async def lsl_reader_loop(self):
        """Main loop to read from LSL and send to cloud."""
        print("Starting LSL reader loop...")

        while self.running:
            try:
                # Pull sample from LSL (timeout 1 second)
                sample, timestamp = self.lsl_inlet.pull_sample(timeout=1.0)

                if sample:
                    # Preprocess and package data
                    data = self.preprocess_sample(sample, timestamp)

                    # Send to cloud
                    await self.send_data(data)

            except Exception as e:
                print(f"Error in LSL reader loop: {e}")
                await asyncio.sleep(1.0)

    async def reconnect_loop(self):
        """Monitor connection and reconnect if needed."""
        print("Starting reconnect monitor...")

        while self.running:
            if not self.connected:
                try:
                    print("Attempting to reconnect to cloud...")
                    await self.connect_cloud()

                    # Flush buffered data
                    await self.flush_buffer()

                except Exception as e:
                    print(f"Reconnection failed: {e}")
                    await asyncio.sleep(5.0)  # Wait before retry

            await asyncio.sleep(10.0)  # Check every 10 seconds

    async def run(self):
        """Run the edge relay."""
        self.running = True

        try:
            # Connect to LSL stream
            stream_info = await self.connect_lsl()

            # Connect to cloud
            await self.connect_cloud()

            # Send initial handshake with stream info
            await self.send_data({
                "type": "handshake",
                "user_id": self.user_id,
                "stream_info": stream_info,
                "timestamp": time.time(),
            })

            # Start reader and reconnect loops
            await asyncio.gather(
                self.lsl_reader_loop(),
                self.reconnect_loop(),
            )

        except KeyboardInterrupt:
            print("\nShutting down...")
        except Exception as e:
            print(f"Error in edge relay: {e}")
            raise
        finally:
            await self.stop()

    async def stop(self):
        """Stop the edge relay gracefully."""
        print("Stopping edge relay...")
        self.running = False

        # Flush remaining buffer
        if self.connected:
            await self.flush_buffer()

        # Close WebSocket
        if self.ws:
            await self.ws.close()

        print("Edge relay stopped")


async def main():
    """Main entry point."""
    import sys

    config_file = sys.argv[1] if len(sys.argv) > 1 else "edge_relay_config.yaml"

    relay = EdgeRelay(config_path=config_file)
    await relay.run()


if __name__ == "__main__":
    asyncio.run(main())
