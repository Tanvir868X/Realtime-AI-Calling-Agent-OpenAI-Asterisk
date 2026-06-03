"""
RTP handler for managing audio streaming and RTP connections
"""
import asyncio
import socket
import struct
import logging
from typing import Optional, Dict, Any, Callable
from config import config
import time

logger = logging.getLogger(__name__)

class RTPPacket:
    """RTP packet structure"""
    
    def __init__(self, data: bytes):
        if len(data) < 12:
            raise ValueError("RTP packet too short")
            
        # Parse RTP header (first 12 bytes)
        header = struct.unpack('!BBHII', data[:12])
        self.version = (header[0] >> 6) & 0x3
        self.padding = (header[0] >> 5) & 0x1
        self.extension = (header[0] >> 4) & 0x1
        self.csrc_count = header[0] & 0xF
        self.marker = (header[1] >> 7) & 0x1
        self.payload_type = header[1] & 0x7F
        self.sequence_number = header[2]
        self.timestamp = header[3]
        self.ssrc = header[4]
        
        # Payload starts after header
        self.payload = data[12:]
        
    def to_bytes(self) -> bytes:
        """Convert RTP packet back to bytes"""
        header = struct.pack('!BBHII',
            (self.version << 6) | (self.padding << 5) | (self.extension << 4) | self.csrc_count,
            (self.marker << 7) | self.payload_type,
            self.sequence_number,
            self.timestamp,
            self.ssrc
        )
        return header + self.payload

class RTPReceiver:
    """Receives RTP audio from Asterisk"""
    
    def __init__(self, port: int, on_audio: Callable[[bytes, str], None], channel_id: str):
        self.port = port
        self.on_audio = on_audio
        self.channel_id = channel_id
        self.socket: Optional[socket.socket] = None
        self.is_running = False
        self.sequence_number = 0
        self.last_sender_addr: Optional[tuple] = None  # (host, port)
        
    async def start(self):
        """Start receiving RTP packets"""
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.socket.bind(('0.0.0.0', self.port))
            self.socket.settimeout(1.0)
            self.is_running = True
            
            logger.info(f"[RTP] Receiver started on port {self.port} for channel {self.channel_id}")
            
            # Start receiving loop
            asyncio.create_task(self._receive_loop())
            
        except Exception as e:
            logger.error(f"[RTP] Failed to start receiver on port {self.port}: {str(e)}")
            raise
            
    async def _receive_loop(self):
        """Main receive loop for RTP packets"""
        while self.is_running and self.socket:
            try:
                # Receive data with timeout
                data, addr = await asyncio.get_event_loop().run_in_executor(
                    None, self.socket.recvfrom, 1500
                )
                
                if data:
                    # Remember where RTP is coming from so we can send back
                    self.last_sender_addr = addr
                    # Parse RTP packet
                    try:
                        rtp_packet = RTPPacket(data)
                        
                        # Check if this is an audio packet (payload type 0 for PCM)
                        if rtp_packet.payload_type == 0:
                            # Call audio callback
                            await self.on_audio(rtp_packet.payload, self.channel_id)
                            
                    except ValueError as e:
                        logger.debug(f"[RTP] Invalid RTP packet: {str(e)}")
                        
            except socket.timeout:
                continue
            except Exception as e:
                if self.is_running:
                    logger.error(f"[RTP] Error in receive loop: {str(e)}")
                    
        logger.info(f"[RTP] Receiver stopped for channel {self.channel_id}")
        
    def stop(self):
        """Stop receiving RTP packets"""
        self.is_running = False
        if self.socket:
            self.socket.close()
            self.socket = None
            
    def get_port(self) -> int:
        """Get the port this receiver is listening on"""
        return self.port

class RTPSender:
    """Sends RTP audio to Asterisk"""
    
    def __init__(self, host: str, port: int, channel_id: str):
        self.host = host
        self.port = port
        self.channel_id = channel_id
        self.socket: Optional[socket.socket] = None
        self.sequence_number = 0
        self.timestamp = 0
        self.ssrc = 0x12345678  # Random SSRC
        
    async def start(self):
        """Start the RTP sender"""
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            logger.info(f"[RTP] Sender started for {self.host}:{self.port} (channel {self.channel_id})")
        except Exception as e:
            logger.error(f"[RTP] Failed to start sender: {str(e)}")
            raise
            
    async def send_audio(self, audio_data: bytes, sample_rate: int = 8000, cancel: Optional[asyncio.Event] = None):
        """Send audio data as RTP packets in 20ms (160-byte) mu-law frames.
        If cancel is provided and set, stops sending early (for barge-in).
        """
        if not self.socket:
            logger.warning(f"[RTP] Sender not started for channel {self.channel_id}")
            return
            
        try:
            frame_duration_ms = 20
            samples_per_frame = sample_rate * frame_duration_ms // 1000  # 160 at 8kHz
            bytes_per_frame = samples_per_frame  # 1 byte per sample for mu-law

            total_len = len(audio_data)
            offset = 0
            while offset < total_len:
                if cancel is not None and cancel.is_set():
                    logger.info(f"[RTP] Send canceled for channel {self.channel_id}")
                    break
                frame = audio_data[offset:offset + bytes_per_frame]
                if len(frame) < bytes_per_frame:
                    # pad with silence (0xFF is mu-law silence)
                    frame = frame + b"\xff" * (bytes_per_frame - len(frame))

                # Build RTP header directly (12 bytes)
                version = 2
                padding = 0
                extension = 0
                csrc_count = 0
                marker = 0
                payload_type = 0  # 0 = PCMU (G.711 mu-law)
                header_byte0 = (version << 6) | (padding << 5) | (extension << 4) | csrc_count
                header_byte1 = (marker << 7) | payload_type
                header = struct.pack('!BBHII', header_byte0, header_byte1, self.sequence_number, self.timestamp, self.ssrc)
                packet_data = header + frame
                await asyncio.get_event_loop().run_in_executor(
                    None, self.socket.sendto, packet_data, (self.host, self.port)
                )

                # Update counters
                self.sequence_number = (self.sequence_number + 1) & 0xFFFF
                self.timestamp = (self.timestamp + samples_per_frame) & 0xFFFFFFFF
                offset += bytes_per_frame

                # Pace to real-time
                await asyncio.sleep(frame_duration_ms / 1000.0)
            
        except Exception as e:
            logger.error(f"[RTP] Error sending audio for channel {self.channel_id}: {str(e)}")
            
    def stop(self):
        """Stop the RTP sender"""
        if self.socket:
            self.socket.close()
            self.socket = None

class RTPManager:
    """Manages RTP connections and port allocation"""
    
    def __init__(self):
        self.port_start = config.RTP_PORT_START
        self.used_ports: set = set()
        self.next_port: int = self.port_start
        self.receivers: Dict[str, RTPReceiver] = {}
        self.senders: Dict[str, RTPSender] = {}
        
    def get_next_port(self) -> int:
        """Get next available RTP port"""
        # Monotonic allocation to avoid races with OS binding reuse
        port = self.next_port
        self.used_ports.add(port)
        self.next_port = port + 2
        return port
        
    def release_port(self, port: int):
        """Release an RTP port"""
        if port in self.used_ports:
            self.used_ports.remove(port)
            
    async def create_receiver(self, channel_id: str, on_audio: Callable[[bytes, str], None]) -> RTPReceiver:
        """Create a new RTP receiver for a channel"""
        port = self.get_next_port()
        receiver = RTPReceiver(port, on_audio, channel_id)
        self.receivers[channel_id] = receiver
        await receiver.start()
        return receiver
        
    async def create_sender(self, channel_id: str, host: str, port: int) -> RTPSender:
        """Create a new RTP sender for a channel"""
        sender = RTPSender(host, port, channel_id)
        self.senders[channel_id] = sender
        await sender.start()
        return sender
        
    def remove_channel(self, channel_id: str):
        """Remove RTP connections for a channel"""
        if channel_id in self.receivers:
            receiver = self.receivers[channel_id]
            receiver.stop()
            self.release_port(receiver.get_port())
            del self.receivers[channel_id]
            
        if channel_id in self.senders:
            sender = self.senders[channel_id]
            sender.stop()
            del self.senders[channel_id]
            
    def get_active_channels(self) -> list:
        """Get list of channels with active RTP connections"""
        return list(self.receivers.keys())

    async def send_audio(self, channel_id: str, audio_data: bytes, sample_rate: int = 8000, cancel_event: Optional[asyncio.Event] = None):
        """Send audio bytes to the remote RTP endpoint for a channel.
        Creates a sender on first use, targeting the last observed source of RTP packets.
        """
        try:
            # Ensure we have a sender
            sender = self.senders.get(channel_id)
            if sender is None:
                receiver = self.receivers.get(channel_id)
                if receiver is None:
                    logger.warning(f"[RTP] No receiver for channel {channel_id}; cannot infer remote address")
                    return
                if receiver.last_sender_addr is None:
                    logger.warning(f"[RTP] No remote RTP address observed yet for channel {channel_id}")
                    return
                host, port = receiver.last_sender_addr[0], receiver.last_sender_addr[1]
                sender = await self.create_sender(channel_id, host, port)
            # Send the audio
            await sender.send_audio(audio_data, sample_rate=sample_rate, cancel=cancel_event)
        except Exception as e:
            logger.error(f"[RTP] Failed to send audio for channel {channel_id}: {str(e)}")

# Global RTP manager instance
rtp_manager = RTPManager()
