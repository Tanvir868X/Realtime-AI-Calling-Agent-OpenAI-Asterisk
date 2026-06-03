"""
State management for Asterisk calling agent
"""
import asyncio
from typing import Dict, Set, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

@dataclass
class ChannelData:
    """Data structure for tracking channel information"""
    channel_id: str
    bridge_id: Optional[str] = None
    local_channel_id: Optional[str] = None
    call_start_time: datetime = field(default_factory=datetime.now)
    call_timeout_id: Optional[asyncio.Task] = None
    ws_closed: bool = False
    stream_handler: Optional[Any] = None
    gemini_session: Optional[Any] = None
    deepgram_connection: Optional[Any] = None
    audio_buffer: bytes = b''
    is_speaking: bool = False
    last_activity: datetime = field(default_factory=datetime.now)

class StateManager:
    """Manages global state for the calling agent"""
    
    def __init__(self):
        self.sip_map: Dict[str, ChannelData] = {}
        self.ext_map: Dict[str, str] = {}
        self.rtp_senders: Dict[str, Any] = {}
        self.rtp_receivers: Dict[str, Any] = {}
        self.cleanup_promises: Dict[str, asyncio.Future] = {}
        self.active_calls: Set[str] = set()
        self.max_concurrent_calls: int = 10
        
    def add_channel(self, channel_id: str, channel_data: ChannelData) -> None:
        """Add a new channel to the state"""
        if len(self.active_calls) >= self.max_concurrent_calls:
            logger.warning(f"Maximum concurrent calls reached ({self.max_concurrent_calls})")
            return
            
        self.sip_map[channel_id] = channel_data
        self.active_calls.add(channel_id)
        logger.info(f"Channel {channel_id} added to state. Active calls: {len(self.active_calls)}")
        
    def remove_channel(self, channel_id: str) -> None:
        """Remove a channel from the state"""
        if channel_id in self.sip_map:
            del self.sip_map[channel_id]
        if channel_id in self.active_calls:
            self.active_calls.remove(channel_id)
        if channel_id in self.rtp_senders:
            del self.rtp_senders[channel_id]
        if channel_id in self.rtp_receivers:
            del self.rtp_receivers[channel_id]
        if channel_id in self.cleanup_promises:
            del self.cleanup_promises[channel_id]
            
        logger.info(f"Channel {channel_id} removed from state. Active calls: {len(self.active_calls)}")
        
    def get_channel(self, channel_id: str) -> Optional[ChannelData]:
        """Get channel data by ID"""
        return self.sip_map.get(channel_id)
        
    def update_channel(self, channel_id: str, **kwargs) -> None:
        """Update channel data"""
        if channel_id in self.sip_map:
            channel_data = self.sip_map[channel_id]
            for key, value in kwargs.items():
                if hasattr(channel_data, key):
                    setattr(channel_data, key, value)
                    if key == 'last_activity':
                        channel_data.last_activity = datetime.now()
                        
    def add_rtp_sender(self, channel_id: str, sender: Any) -> None:
        """Add RTP sender for a channel"""
        self.rtp_senders[channel_id] = sender
        
    def add_rtp_receiver(self, channel_id: str, receiver: Any) -> None:
        """Add RTP receiver for a channel"""
        self.rtp_receivers[channel_id] = receiver
        
    def get_active_calls_count(self) -> int:
        """Get current active calls count"""
        return len(self.active_calls)
        
    def can_accept_new_call(self) -> bool:
        """Check if new calls can be accepted"""
        return len(self.active_calls) < self.max_concurrent_calls
        
    def cleanup_channel_resources(self, channel_id: str) -> None:
        """Clean up all resources associated with a channel"""
        self.remove_channel(channel_id)
        
    def get_all_channels(self) -> Dict[str, ChannelData]:
        """Get all active channels"""
        return self.sip_map.copy()
        
    def is_channel_active(self, channel_id: str) -> bool:
        """Check if a channel is active"""
        return channel_id in self.active_calls

# Global state instance
state_manager = StateManager()
