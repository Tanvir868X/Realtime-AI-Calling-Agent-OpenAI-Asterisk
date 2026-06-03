"""
Asterisk ARI client for managing calls and channels
"""
import asyncio
import aiohttp
import json
import logging
from typing import Optional, Dict, Any, Callable
from config import config, log_client, log_openai
from state import state_manager, ChannelData
from rtp_handler import rtp_manager
from openai_realtime_client import openai_realtime_client
import time

logger = logging.getLogger(__name__)

class AsteriskClient:
    """Client for Asterisk ARI (Asterisk REST Interface)"""
    
    def __init__(self):
        # Auto-append /ari if missing from URL
        base_url = config.ARI_URL
        if not base_url.endswith('/ari'):
            if base_url.endswith('/'):
                base_url += 'ari'
            else:
                base_url += '/ari'
        
        self.base_url = base_url
        self.username = config.ARI_USER
        self.password = config.ARI_PASS
        self.app_name = config.ARI_APP
        self.session: Optional[aiohttp.ClientSession] = None
        self.websocket: Optional[aiohttp.ClientWebSocketResponse] = None
        self.is_connected = False
        self.channel_handlers: Dict[str, Callable] = {}
        
    async def connect(self):
        """Connect to Asterisk ARI"""
        try:
            # Create HTTP session
            auth = aiohttp.BasicAuth(self.username, self.password)
            self.session = aiohttp.ClientSession(auth=auth)
            
            # Test connection
            async with self.session.get(f"{self.base_url}/asterisk/info") as response:
                if response.status != 200:
                    raise ConnectionError(f"ARI connection failed: {response.status}")
                    
            # Connect to WebSocket for events
            ws_url = f"{self.base_url.replace('http', 'ws')}/events?app={self.app_name}&api_key={self.username}:{self.password}"
            
            self.websocket = await self.session.ws_connect(ws_url)
            self.is_connected = True
            
            log_client(f"Connected to Asterisk ARI at {self.base_url}")
            
            # Start listening for events
            asyncio.create_task(self._listen_for_events())
            
        except Exception as e:
            log_openai(f"Connection failed: {str(e)}")
            self.is_connected = False
            raise
            
    async def _listen_for_events(self):
        """Listen for Asterisk events via WebSocket"""
        try:
            async for msg in self.websocket:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    event_data = json.loads(msg.data)
                    await self._handle_event(event_data)
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    logger.error(f"[ARI] WebSocket error: {self.websocket.exception()}")
                    break
                    
        except Exception as e:
            logger.error(f"[ARI] Error in event listener: {str(e)}")
        finally:
            self.is_connected = False
            
    async def _handle_event(self, event_data: Dict[str, Any]):
        """Handle incoming Asterisk events"""
        try:
            event_type = event_data.get('type')
            channel_id = event_data.get('channel', {}).get('id')
            
            if not channel_id:
                return
                
            logger.debug(f"[ARI] Received event: {event_type} for channel {channel_id}")
            
            if event_type == 'StasisStart':
                await self._handle_stasis_start(event_data)
            elif event_type == 'ChannelStateChange':
                await self._handle_channel_state_change(event_data)
            elif event_type == 'ChannelDestroyed':
                await self._handle_channel_destroyed(event_data)
            elif event_type == 'StasisEnd':
                await self._handle_stasis_end(event_data)
                
        except Exception as e:
            logger.error(f"[ARI] Error handling event: {str(e)}")
            
    async def _handle_stasis_start(self, event_data: Dict[str, Any]):
        """Handle new call start"""
        try:
            channel_id = event_data['channel']['id']
            channel_info = event_data.get('channel', {})
            technology = channel_info.get('technology') or ''
            name = channel_info.get('name') or ''

            # Ignore ExternalMedia/UnicastRTP channels to avoid recursion
            if technology.upper() == 'UNICASTRTP' or name.startswith('UnicastRTP/'):
                logger.debug(f"[ARI] Ignoring ExternalMedia channel {channel_id} ({name})")
                return
            
            if not state_manager.can_accept_new_call():
                logger.warning(f"[ARI] Maximum concurrent calls reached, rejecting {channel_id}")
                await self.hangup_channel(channel_id)
                return
                
            log_client(f"New call started on channel {channel_id}")
            
            # Create channel data
            channel_data = ChannelData(channel_id=channel_id)
            state_manager.add_channel(channel_id, channel_data)
            
            # Answer the call
            await self.answer_channel(channel_id)
            
            # Create bridge for the call
            bridge_id = await self.create_bridge(channel_id)
            if bridge_id:
                channel_data.bridge_id = bridge_id
                # Add the caller's channel to the bridge so audio mixes with ExternalMedia
                try:
                    await self.add_channel_to_bridge(bridge_id, channel_id)
                except Exception as e:
                    logger.warning(f"[ARI] Could not add caller channel {channel_id} to bridge {bridge_id}: {str(e)}")
                
            # Start RTP receiver
            rtp_receiver = await rtp_manager.create_receiver(
                channel_id, 
                self._on_audio_received
            )
            state_manager.add_rtp_receiver(channel_id, rtp_receiver)

            # Create an ExternalMedia channel to send TTS deterministically to our RTP port
            try:
                await self._ensure_external_media(channel_id)
            except Exception as e:
                logger.warning(f"[ARI] ExternalMedia setup failed: {str(e)}")
            
            # Start OpenAI Realtime session (full STT+LLM+TTS via single WS)
            await openai_realtime_client.connect(channel_id, rtp_manager)
            
            # Ensure agent starts with greeting (not random conversation)
            try:
                await self._ensure_agent_greeting(channel_id)
            except Exception as e:
                logger.warning(f"[ARI] Greeting setup failed: {str(e)}")
            
        except Exception as e:
            logger.error(f"[ARI] Error handling StasisStart: {str(e)}")
            
    async def _handle_channel_state_change(self, event_data: Dict[str, Any]):
        """Handle channel state changes"""
        channel_id = event_data['channel']['id']
        new_state = event_data['channel']['state']
        
        logger.debug(f"[ARI] Channel {channel_id} state changed to {new_state}")
        
        # Update channel state
        state_manager.update_channel(channel_id, last_activity=time.time())
        
    async def _handle_channel_destroyed(self, event_data: Dict[str, Any]):
        """Handle channel destruction"""
        channel_id = event_data['channel']['id']
        log_client(f"Channel {channel_id} destroyed")
        
        # Cleanup channel resources
        await self._cleanup_channel(channel_id)
        
    async def _handle_stasis_end(self, event_data: Dict[str, Any]):
        """Handle call end"""
        channel_id = event_data['channel']['id']
        log_client(f"Stasis ended for channel {channel_id}")
        
        # Cleanup channel resources
        await self._cleanup_channel(channel_id)
        
    async def _cleanup_channel(self, channel_id: str):
        """Clean up all resources for a channel"""
        try:
            # Remove from state manager
            state_manager.cleanup_channel_resources(channel_id)
            
            # Remove RTP connections
            rtp_manager.remove_channel(channel_id)
            
            # Close realtime session
            await openai_realtime_client.close(channel_id)
            
            logger.info(f"[ARI] Cleanup completed for channel {channel_id}")
            
        except Exception as e:
            logger.error(f"[ARI] Error during cleanup for channel {channel_id}: {str(e)}")
            
    async def _on_audio_received(self, audio_data: bytes, channel_id: str):
        """Handle incoming audio from RTP"""
        try:
            # Update channel activity
            state_manager.update_channel(channel_id, last_activity=time.time())
            
            # Always forward to OpenAI (for barge-in, VAD, and optional server STT)
            if openai_realtime_client.is_connection_active(channel_id):
                await openai_realtime_client.send_input_audio(audio_data, channel_id)

        except Exception as e:
            logger.error(f"[ARI] Error handling audio for channel {channel_id}: {str(e)}")
            

            
    async def _play_initial_greeting(self, channel_id: str):
        """Play initial greeting message"""
        try:
            # Wait briefly for RTP peer address to be learned before sending audio
            try:
                max_wait_ms = 1500
                waited_ms = 0
                while waited_ms < max_wait_ms:
                    receiver = rtp_manager.receivers.get(channel_id)
                    if receiver and getattr(receiver, 'last_sender_addr', None):
                        break
                    await asyncio.sleep(0.05)
                    waited_ms += 50
                if waited_ms >= max_wait_ms:
                    logger.warning(f"[ARI] Proceeding without learned RTP peer for channel {channel_id}")
            except Exception:
                pass

            # No-op: greeting handled by realtime client during connect()
            return
            
        except Exception as e:
            logger.error(f"[ARI] Error playing greeting for channel {channel_id}: {str(e)}")
            
    async def answer_channel(self, channel_id: str):
        """Answer a channel"""
        try:
            url = f"{self.base_url}/channels/{channel_id}/answer"
            async with self.session.post(url) as response:
                if response.status in (200, 204):
                    logger.info(f"[ARI] Channel {channel_id} answered (status {response.status})")
                else:
                    logger.error(f"[ARI] Failed to answer channel {channel_id}: {response.status}")
                    
        except Exception as e:
            logger.error(f"[ARI] Error answering channel {channel_id}: {str(e)}")
            
    async def hangup_channel(self, channel_id: str):
        """Hang up a channel"""
        try:
            url = f"{self.base_url}/channels/{channel_id}/hangup"
            async with self.session.delete(url) as response:
                if response.status == 200:
                    logger.info(f"[ARI] Channel {channel_id} hung up")
                else:
                    logger.error(f"[ARI] Failed to hang up channel {channel_id}: {response.status}")
                    
        except Exception as e:
            logger.error(f"[ARI] Error hanging up channel {channel_id}: {str(e)}")
            
    async def create_bridge(self, channel_id: str) -> Optional[str]:
        """Create a bridge for a channel"""
        try:
            url = f"{self.base_url}/bridges"
            data = {
                "type": "mixing",
                "bridgeId": f"bridge_{channel_id}"
            }
            
            async with self.session.post(url, json=data) as response:
                if response.status == 200:
                    bridge_data = await response.json()
                    bridge_id = bridge_data.get('id')
                    logger.info(f"[ARI] Bridge {bridge_id} created for channel {channel_id}")
                    return bridge_id
                else:
                    logger.error(f"[ARI] Failed to create bridge for channel {channel_id}: {response.status}")
                    return None
                    
        except Exception as e:
            logger.error(f"[ARI] Error creating bridge for channel {channel_id}: {str(e)}")
            return None
            
    async def add_channel_to_bridge(self, bridge_id: str, channel_id: str):
        """Add a channel to a bridge"""
        try:
            url = f"{self.base_url}/bridges/{bridge_id}/addChannel"
            data = {"channel": channel_id}
            
            async with self.session.post(url, json=data) as response:
                if response.status in (200, 204):
                    logger.info(f"[ARI] Channel {channel_id} added to bridge {bridge_id} (status {response.status})")
                else:
                    logger.error(f"[ARI] Failed to add channel {channel_id} to bridge {bridge_id}: {response.status}")
                    
        except Exception as e:
            logger.error(f"[ARI] Error adding channel {channel_id} to bridge {bridge_id}: {str(e)}")

    async def _ensure_external_media(self, channel_id: str):
        """Create an ExternalMedia channel that points to our local RTP receiver and add it to the bridge."""
        try:
            bridge_id = f"bridge_{channel_id}"
            receiver = rtp_manager.receivers.get(channel_id)
            if not receiver:
                logger.warning(f"[ARI] No RTP receiver found for channel {channel_id}; cannot create ExternalMedia")
                return
            host = config.RTP_EXTERNAL_HOST
            port = receiver.get_port()

            # Create ExternalMedia channel
            url = f"{self.base_url}/channels/externalMedia"
            params = {
                "app": self.app_name,
                "external_host": f"{host}:{port}",
                "format": "ulaw"
            }
            async with self.session.post(url, params=params) as resp:
                if resp.status not in (200, 202):
                    body = await resp.text()
                    logger.warning(f"[ARI] Failed to create ExternalMedia (status {resp.status}): {body}")
                else:
                    data = await resp.json()
                    ext_chan_id = data.get('id') or data.get('channel', {}).get('id')
                    if ext_chan_id:
                        # Add ExternalMedia channel to the bridge
                        await self.add_channel_to_bridge(bridge_id, ext_chan_id)
                        logger.info(f"[ARI] ExternalMedia channel {ext_chan_id} added to bridge {bridge_id}")
        except Exception as e:
            logger.warning(f"[ARI] Error ensuring ExternalMedia: {str(e)}")
            
    async def close(self):
        """Close ARI connection"""
        try:
            self.is_connected = False
            
            if self.websocket:
                await self.websocket.close()
                
            if self.session:
                await self.session.close()
                
            logger.info("[ARI] Connection closed")
            
        except Exception as e:
            logger.error(f"[ARI] Error closing connection: {str(e)}")
            
    def is_connection_active(self) -> bool:
        """Check if ARI connection is active"""
        return self.is_connected and self.session is not None

    async def _ensure_agent_greeting(self, channel_id: str):
        """Ensure the agent starts with a proper greeting message."""
        try:
            # Wait a moment for OpenAI Realtime to be ready
            await asyncio.sleep(0.5)
            
            if openai_realtime_client.is_connection_active(channel_id):
                # Send a greeting message to start the conversation properly
                greeting = getattr(config, "INITIAL_MESSAGE", "Hi there! How can I help you today?")
                log_client(f"Starting with greeting for {channel_id}: {greeting}")
                
                # This will trigger OpenAI to respond with the greeting
                await openai_realtime_client.send_user_text(greeting, channel_id)
            else:
                logger.warning(f"[AGENT] {channel_id}: OpenAI Realtime not ready for greeting")
        except Exception as e:
            logger.error(f"[AGENT] {channel_id}: Error setting up greeting: {str(e)}")

# Global Asterisk client instance
asterisk_client = AsteriskClient()
