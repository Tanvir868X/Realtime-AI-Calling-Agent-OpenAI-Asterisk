"""
OpenAI Realtime client (full-duplex STT+LLM+TTS) for Asterisk calling agent

Mirrors the behavior of the Node.js reference in `asterisk_python/test`:
- Uses single Realtime WebSocket per call
- Sends incoming RTP audio (G.711 mu-law 8k) as input_audio_buffer.append
- Receives assistant audio deltas in G.711 mu-law and forwards via RTP
- Server VAD triggers barge-in; playback is canceled when user speaks
"""
import asyncio
import base64
import json
import logging
from dataclasses import dataclass, field
from typing import Dict, Optional

import websockets

from config import config, log_client, log_openai, log_conversation


logger = logging.getLogger(__name__)


@dataclass
class ChannelSession:
    channel_id: str
    websocket: Optional[websockets.WebSocketClientProtocol] = None
    connected: bool = False
    delta_queue: "asyncio.Queue[bytes]" = field(default_factory=asyncio.Queue)
    playback_task: Optional[asyncio.Task] = None
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)
    total_delta_bytes: int = 0
    initialized: bool = False


class OpenAIRealtimeClient:
    def __init__(self) -> None:
        self.sessions: Dict[str, ChannelSession] = {}

    async def connect(self, channel_id: str, rtp_manager) -> None:
        """Open a realtime WS session and start processing messages for a channel."""
        if channel_id in self.sessions and self.sessions[channel_id].connected:
            return

        api_key = getattr(config, "OPENAI_API_KEY", None)
        model = getattr(
            config,
            "OPENAI_REALTIME_MODEL",
            "gpt-4o-mini-realtime-preview-2024-12-17",
        )
        if not api_key:
            raise ValueError("OPENAI_API_KEY is missing in config")

        url = f"wss://api.openai.com/v1/realtime?model={model}"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "OpenAI-Beta": "realtime=v1",
            "Origin": "https://api.openai.com",
        }

        session = ChannelSession(channel_id=channel_id)
        self.sessions[channel_id] = session

        # Establish websocket
        ws = await websockets.connect(
            url,
            additional_headers=headers,
            ping_interval=15,
            ping_timeout=10,
            max_queue=128,
        )
        session.websocket = ws
        session.connected = True

        log_client(f"WebSocket connected for {channel_id}")

        # Initialize server-side session to use ulaw in/out and VAD
        vad_threshold = getattr(config, "VAD_THRESHOLD", 0.6)
        vad_prefix = getattr(config, "VAD_PREFIX_PADDING_MS", 200)
        vad_silence = getattr(config, "VAD_SILENCE_DURATION_MS", 600)
        voice = getattr(config, "OPENAI_VOICE", "alloy")
        instructions = getattr(
            config,
            "SYSTEM_PROMPT",
            "You are a concise voice assistant for phone calls.",
        )

        await ws.send(
            json.dumps(
                {
                    "type": "session.update",
                    "session": {
                        "modalities": ["audio", "text"],
                        "voice": voice,
                        "instructions": instructions,
                        # Mirror Node reference: send/receive ulaw directly
                        "input_audio_format": "g711_ulaw",
                        "output_audio_format": "g711_ulaw",
                        # Optional: expose VAD config knobs
                        "turn_detection": {
                            "type": "server_vad",
                            "threshold": vad_threshold,
                            "prefix_padding_ms": vad_prefix,
                            "silence_duration_ms": vad_silence,
                        },
                    },
                }
            )
        )

        # Start playback worker for assistant audio deltas
        session.playback_task = asyncio.create_task(
            self._playback_worker(session, rtp_manager)
        )

        # Start message pump
        asyncio.create_task(self._listen_for_messages(session, rtp_manager))

        # Kick off initial assistant greeting by seeding a user item
        initial_text = getattr(config, "INITIAL_MESSAGE", "Hi") or "Hi"
        try:
            # Don't auto-seed conversation - let the greeting method handle it
            log_client(f"Session initialized for {channel_id}, waiting for greeting setup")
        except Exception as e:
            logger.warning(f"[Realtime] Failed to initialize session: {e}")

    async def _playback_worker(self, session: ChannelSession, rtp_manager) -> None:
        """Reads ulaw audio chunks from queue and sends over RTP paced by RTPSender."""
        channel_id = session.channel_id
        try:
            while session.connected:
                chunk = await session.delta_queue.get()
                if chunk is None:
                    break
                # On first chunk of a new stream, prepend small silence per config
                try:
                    if session.total_delta_bytes == 0:
                        silence_ms = int(getattr(config, "SILENCE_PADDING_MS", 100) or 0)
                        if silence_ms > 0:
                            num_packets = max(0, (silence_ms + 19) // 20)
                            if num_packets > 0:
                                silence = bytes([0x7F]) * (num_packets * 160)
                                await rtp_manager.send_audio(channel_id, silence, sample_rate=8000, cancel_event=session.cancel_event)
                except Exception:
                    pass

                session.total_delta_bytes += len(chunk)
                # Send ulaw bytes; sender frames into 20ms automatically
                await rtp_manager.send_audio(
                    channel_id, chunk, sample_rate=8000, cancel_event=session.cancel_event
                )
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"[Realtime] Playback worker error for {channel_id}: {e}")

    async def _listen_for_messages(self, session: ChannelSession, rtp_manager) -> None:
        """Process events from OpenAI WS, enqueueing audio deltas and handling barge-in."""
        ws = session.websocket
        channel_id = session.channel_id
        try:
            async for message in ws:
                try:
                    data = json.loads(message)
                except Exception as e:
                    logger.warning(f"[Realtime] JSON parse error for {channel_id}: {e}")
                    continue

                event_type = data.get("type")

                if event_type == "session.created":
                    log_client(f"Session created for {channel_id}")
                elif event_type == "session.updated":
                    log_openai(f"Session updated for {channel_id}")
                elif event_type == "conversation.item.created":
                    # If server VAD detected user speech, cancel current playback
                    item = data.get("item") or {}
                    role = item.get("role")
                    if role == "user":
                        log_openai(f"Barge-in detected for {channel_id}; canceling playback")
                        session.cancel_event.set()
                        # Drain any queued audio
                        try:
                            while not session.delta_queue.empty():
                                _ = session.delta_queue.get_nowait()
                        except Exception:
                            pass
                    elif role == "assistant":
                        # Log assistant responses
                        content = item.get("content", [])
                        text_content = ""
                        for content_item in content:
                            if content_item.get("type") == "text":
                                text_content = content_item.get("text", "")
                                break
                        if text_content:
                            log_client(f"Assistant response for {channel_id}: {text_content}")
                elif event_type == "response.audio.delta":
                    delta_b64 = data.get("delta")
                    if delta_b64:
                        try:
                            chunk = base64.b64decode(delta_b64)
                            # Filter out all-silence buffers (optional)
                            if chunk and not all(b == 0x7F for b in chunk):
                                # If we were canceled by barge-in, reset cancel and start fresh
                                if session.cancel_event.is_set():
                                    session.cancel_event = asyncio.Event()
                                    session.total_delta_bytes = 0
                                await session.delta_queue.put(chunk)
                        except Exception as e:
                            logger.debug(f"[Realtime] Failed to decode delta for {channel_id}: {e}")
                elif event_type == "response.audio.done":
                    log_openai(f"Response audio done for {channel_id}, total bytes: {session.total_delta_bytes}")
                    session.total_delta_bytes = 0
                elif event_type == "error":
                    log_openai(f"Error for {channel_id}: {data}")
                elif event_type == "conversation.item.updated":
                    # Log transcription updates for debugging
                    if getattr(config, "ENABLE_TRANSCRIPTION_LOGGING", True):
                        item = data.get("item", {})
                        role = item.get("role")
                        if role == "user":
                            content = item.get("content", [])
                            for content_item in content:
                                if content_item.get("type") == "text":
                                    text = content_item.get("text", "")
                                    if text:
                                        log_openai(f"User transcript for {channel_id}: {text}")
                elif event_type == "response.audio_transcript.delta":
                    # Only show delta logs if explicitly enabled
                    if getattr(config, "LOG_TRANSCRIPT_DELTAS", False):
                        if data.get("delta") and getattr(config, "ENABLE_TRANSCRIPTION_LOGGING", True):
                            delta_text = data.get("delta", "").strip()
                            if delta_text:
                                log_openai(f"Transcript delta for {channel_id}: {delta_text}")
                elif event_type == "response.audio_transcript.done":
                    if data.get("transcript") and getattr(config, "ENABLE_TRANSCRIPTION_LOGGING", True):
                        transcript = data.get("transcript", "")
                        item_id = data.get("item_id", "")
                        # Determine role based on item_id context
                        role = "User" if item_id else "Assistant"
                        log_openai(f"{role} transcript completed for {channel_id}: {transcript}")
                elif event_type == "conversation.item.input_audio_transcription.delta":
                    # Only show delta logs if explicitly enabled
                    if getattr(config, "LOG_TRANSCRIPT_DELTAS", False):
                        if data.get("delta") and getattr(config, "ENABLE_TRANSCRIPTION_LOGGING", True):
                            delta_text = data.get("delta", "").strip()
                            if delta_text:
                                log_openai(f"User transcript delta for {channel_id}: {delta_text}")
                elif event_type == "conversation.item.input_audio_transcription.completed":
                    if data.get("transcript") and getattr(config, "ENABLE_TRANSCRIPTION_LOGGING", True):
                        transcript = data.get("transcript", "")
                        log_openai(f"User transcript completed for {channel_id}: {transcript}")
                else:
                    # Other transcript delta events can be logged at debug level
                    if getattr(config, "ENABLE_TRANSCRIPTION_LOGGING", True):
                        logger.debug(f"[Realtime] {channel_id}: {event_type} - {data}")
        except websockets.exceptions.ConnectionClosed:
            log_openai(f"WebSocket closed for {channel_id}")
        except Exception as e:
            log_openai(f"Listener error for {channel_id}: {e}")
        finally:
            session.connected = False
            # Unblock playback worker
            try:
                await session.delta_queue.put(None)  # type: ignore[arg-type]
            except Exception:
                pass

    async def send_input_audio(self, audio_mulaw_8k: bytes, channel_id: str) -> None:
        """Append incoming ulaw audio to the realtime session."""
        session = self.sessions.get(channel_id)
        if not session or not session.connected or not session.websocket:
            return
        try:
            payload = {
                "type": "input_audio_buffer.append",
                "audio": base64.b64encode(audio_mulaw_8k).decode("ascii"),
            }
            await session.websocket.send(json.dumps(payload))
        except Exception as e:
            logger.debug(f"[Realtime] send_input_audio error for {channel_id}: {e}")

    async def send_user_text(self, text: str, channel_id: str) -> None:
        """Send a user text message into the realtime conversation and request a response."""
        session = self.sessions.get(channel_id)
        if not session or not session.connected or not session.websocket:
            return
        ws = session.websocket
        instructions = getattr(
            config,
            "SYSTEM_PROMPT",
            "You are a concise voice assistant for phone calls.",
        )
        try:
            # Log the user text input
            log_openai(f"User text input for {channel_id}: {text}")
            
            await ws.send(
                json.dumps(
                    {
                        "type": "conversation.item.create",
                        "item": {
                            "type": "message",
                            "role": "user",
                            "content": [
                                {"type": "input_text", "text": text[:4000]},
                            ],
                        },
                    }
                )
            )
            await ws.send(
                json.dumps(
                    {
                        "type": "response.create",
                        "response": {
                            "modalities": ["audio", "text"],
                            "instructions": instructions,
                            "output_audio_format": "g711_ulaw",
                        },
                    }
                )
            )
            
            log_client(f"Requested response for {channel_id}")
        except Exception as e:
            log_openai(f"send_user_text error for {channel_id}: {e}")

    async def close(self, channel_id: str) -> None:
        session = self.sessions.get(channel_id)
        if not session:
            return
        try:
            session.connected = False
            if session.websocket:
                await session.websocket.close()
            if session.playback_task and not session.playback_task.done():
                session.playback_task.cancel()
                try:
                    await session.playback_task
                except Exception:
                    pass
        except Exception as e:
            logger.debug(f"[Realtime] close error for {channel_id}: {e}")
        finally:
            self.sessions.pop(channel_id, None)

    def is_connection_active(self, channel_id: str) -> bool:
        s = self.sessions.get(channel_id)
        return bool(s and s.connected and s.websocket is not None)

    async def health_check(self) -> bool:
        api_key = getattr(config, "OPENAI_API_KEY", None)
        model = getattr(
            config,
            "OPENAI_REALTIME_MODEL",
            "gpt-4o-mini-realtime-preview-2024-12-17",
        )
        if not api_key:
            return False
        url = f"wss://api.openai.com/v1/realtime?model={model}"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "OpenAI-Beta": "realtime=v1",
            "Origin": "https://api.openai.com",
        }
        try:
            async with websockets.connect(url, additional_headers=headers) as ws:
                await ws.close()
            return True
        except Exception as e:
            try:
                # Attempt to extract status code if available
                status = getattr(e, 'status_code', None) or getattr(e, 'code', None)
                logger.error(f"[Realtime] Health check failed: {e} status={status}")
            except Exception:
                logger.error(f"[Realtime] Health check failed: {e}")
            return False


# Global client instance
openai_realtime_client = OpenAIRealtimeClient()


