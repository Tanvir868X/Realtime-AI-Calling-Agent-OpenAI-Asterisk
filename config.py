import os
from dotenv import load_dotenv
from rich.console import Console
from rich.logging import RichHandler
import logging
from rich.text import Text
from rich.panel import Panel

# Load environment variables
load_dotenv('./config.conf')

# Global counters for conversation logging
sent_event_counter = 0
received_event_counter = -1

class Config:
    # Asterisk ARI Configuration
    ARI_URL = os.getenv('ARI_URL', 'http://127.0.0.1:6021/ari')
    ARI_USER = os.getenv('ARI_USER', 'asterisk')
    ARI_PASS = os.getenv('ARI_PASS', 'your-ari-password-here')
    ARI_APP = os.getenv('ARI_APP', 'myapp')
    
    # OpenAI Realtime Configuration
    OPENAI_API_KEY = os.getenv('OPENAI_API_KEY', '')
    OPENAI_REALTIME_URL = os.getenv('OPENAI_REALTIME_URL', 'wss://api.openai.com/v1/audio/realtime')
    
    # Transcription quality settings
    ENABLE_TRANSCRIPTION_LOGGING = os.getenv('ENABLE_TRANSCRIPTION_LOGGING', 'true').lower() in ('1', 'true', 'yes', 'on')
    ASK_FOR_CLARIFICATION = os.getenv('ASK_FOR_CLARIFICATION', 'true').lower() in ('1', 'true', 'yes', 'on')
    
    # Conversation logging settings
    ENABLE_CONVERSATION_LOGGING = os.getenv('ENABLE_CONVERSATION_LOGGING', 'true').lower() in ('1', 'true', 'yes', 'on')
    LOG_CONVERSATION_COUNTERS = os.getenv('LOG_CONVERSATION_COUNTERS', 'true').lower() in ('1', 'true', 'yes', 'on')
    LOG_COLORED_OUTPUT = os.getenv('LOG_COLORED_OUTPUT', 'true').lower() in ('1', 'true', 'yes', 'on')
    LOG_TRANSCRIPT_DELTAS = os.getenv('LOG_TRANSCRIPT_DELTAS', 'false').lower() in ('1', 'true', 'yes', 'on')
    
    # System prompt to improve transcription accuracy for place names
    SYSTEM_PROMPT = os.getenv('SYSTEM_PROMPT', 
        "You are a helpful voice assistant for phone calls. Pay special attention to place names and locations. "
        "Common places include: Dhaka, Sylhet, Chittagong, Khulna, Rajshahi, Barisal, Rangpur, Mymensingh, "
        "Cox's Bazar, Comilla, Narayanganj, Gazipur, and other cities in Bangladesh. "
        "When users mention travel or destinations, carefully listen to the exact place names they say. "
        "If you're unsure about a place name, ask for clarification rather than guessing. "
        "For example, if someone says 'I want to go from Dhaka to Sylhet', make sure you understand 'Sylhet' correctly. "
        "If you hear something unclear, ask 'Did you say Sylhet?' to confirm."
    )
    
    # Initial greeting message
    INITIAL_MESSAGE = os.getenv('INITIAL_MESSAGE', "Hi there! How can I help you today?")
    
    # OpenAI Configuration (Realtime + optional Chat/TTS)
    OPENAI_REALTIME_MODEL = os.getenv('OPENAI_REALTIME_MODEL', os.getenv('REALTIME_MODEL', 'gpt-4o-mini-realtime-preview-2024-12-17'))
    OPENAI_VOICE = os.getenv('OPENAI_VOICE', 'alloy')
    OPENAI_LLM_MODEL = os.getenv('OPENAI_LLM_MODEL', 'gpt-4o-mini')
    OPENAI_TTS_MODEL = os.getenv('OPENAI_TTS_MODEL', 'tts-1')
    MAX_TTS_SENTENCES = int(os.getenv('MAX_TTS_SENTENCES', 2))
    
    # RTP Configuration
    RTP_PORT_START = int(os.getenv('RTP_PORT_START', 12000))
    RTP_EXTERNAL_HOST = os.getenv('RTP_EXTERNAL_HOST', '127.0.0.1')
    MAX_CONCURRENT_CALLS = int(os.getenv('MAX_CONCURRENT_CALLS', 10))
    
    # Voice Activity Detection
    VAD_THRESHOLD = float(os.getenv('VAD_THRESHOLD', 0.6))
    VAD_PREFIX_PADDING_MS = int(os.getenv('VAD_PREFIX_PADDING_MS', 200))
    VAD_SILENCE_DURATION_MS = int(os.getenv('VAD_SILENCE_DURATION_MS', 600))
    
    # Logging
    LOG_LEVEL = os.getenv('LOG_LEVEL', 'info')
    
    # System Configuration
    SILENCE_PADDING_MS = int(os.getenv('SILENCE_PADDING_MS', 100))
    CALL_DURATION_LIMIT_SECONDS = int(os.getenv('CALL_DURATION_LIMIT_SECONDS', 0))
    
    # Audio Configuration
    SAMPLE_RATE = int(os.getenv('SAMPLE_RATE', 8000))
    CHANNELS = int(os.getenv('CHANNELS', 1))
    CHUNK_SIZE = int(os.getenv('CHUNK_SIZE', 1024))
    AUDIO_FORMAT = os.getenv('AUDIO_FORMAT', 'mulaw')

    # External STT Configuration
    USE_EXTERNAL_STT = os.getenv('USE_EXTERNAL_STT', 'false').lower() in ('1', 'true', 'yes', 'on')

# Initialize console for rich output
console = Console()

# Global counters for conversation logging
sent_event_counter = 0
received_event_counter = -1

# Configure logging
def setup_logging():
    # Create custom formatter for conversation logging
    class ConversationFormatter(logging.Formatter):
        def format(self, record):
            # Check if this is a conversation log message
            if hasattr(record, 'conversation_type'):
                if record.conversation_type == 'client':
                    global sent_event_counter
                    counter = f"C-{sent_event_counter:04d}"
                    sent_event_counter += 1
                    prefix = f"[cyan]{counter}[/cyan]"
                elif record.conversation_type == 'openai':
                    global received_event_counter
                    received_event_counter += 1
                    counter = f"O-{received_event_counter:04d}"
                    prefix = f"[yellow]{counter}[/yellow]"
                else:
                    prefix = "N/A"
                
                # Add counter to the message
                record.msg = f"{prefix} | {record.msg}"
            
            return super().format(record)
    
    # Set up basic logging
    logging.basicConfig(
        level=getattr(logging, Config.LOG_LEVEL.upper()),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[RichHandler(console=console, rich_tracebacks=True)]
    )
    
    # Get the root logger and add our custom formatter
    root_logger = logging.getLogger()
    for handler in root_logger.handlers:
        if isinstance(handler, RichHandler):
            handler.setFormatter(ConversationFormatter())
    
    return logging.getLogger(__name__)

# Conversation logging functions
def log_client(msg: str, level: str = 'info', logger_instance=None):
    """Log client-side events with counter"""
    if not logger_instance:
        logger_instance = logging.getLogger(__name__)
    
    # Create a custom record with conversation type
    record = logger_instance.makeRecord(
        logger_instance.name, 
        getattr(logging, level.upper()), 
        '', 0, msg, (), None
    )
    record.conversation_type = 'client'
    
    # Log using the appropriate level
    if level == 'debug':
        logger_instance.debug(msg, extra={'conversation_type': 'client'})
    elif level == 'info':
        logger_instance.info(msg, extra={'conversation_type': 'client'})
    elif level == 'warning':
        logger_instance.warning(msg, extra={'conversation_type': 'client'})
    elif level == 'error':
        logger_instance.error(msg, extra={'conversation_type': 'client'})
    else:
        logger_instance.info(msg, extra={'conversation_type': 'client'})

def log_openai(msg: str, level: str = 'info', logger_instance=None):
    """Log OpenAI-side events with counter"""
    if not logger_instance:
        logger_instance = logging.getLogger(__name__)
    
    # Log using the appropriate level
    if level == 'debug':
        logger_instance.debug(msg, extra={'conversation_type': 'openai'})
    elif level == 'info':
        logger_instance.info(msg, extra={'conversation_type': 'openai'})
    elif level == 'warning':
        logger_instance.warning(msg, extra={'conversation_type': 'openai'})
    elif level == 'error':
        logger_instance.error(msg, extra={'conversation_type': 'openai'})
    else:
        logger_instance.info(msg, extra={'conversation_type': 'openai'})

def log_conversation(user_msg: str = "", agent_msg: str = "", channel_id: str = "", logger_instance=None):
    """Log conversation exchanges between user and agent"""
    if not Config.ENABLE_CONVERSATION_LOGGING:
        return
        
    if not logger_instance:
        logger_instance = logging.getLogger(__name__)
    
    if user_msg:
        log_openai(f"[USER] {channel_id}: {user_msg}", 'info', logger_instance)
    
    if agent_msg:
        log_client(f"[AGENT] {channel_id}: {agent_msg}", 'info', logger_instance)

# Validate configuration
def validate_config():
    if not Config.OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY is missing in config.conf")
    if not Config.SYSTEM_PROMPT or Config.SYSTEM_PROMPT.strip() == '':
        raise ValueError("SYSTEM_PROMPT is missing or empty in config.conf")
    if Config.CALL_DURATION_LIMIT_SECONDS < 0:
        raise ValueError("CALL_DURATION_LIMIT_SECONDS cannot be negative in config.conf")
    
    console.print("✅ Configuration validated successfully", style="green")
    return True

# Export configuration and logging functions
config = Config()
