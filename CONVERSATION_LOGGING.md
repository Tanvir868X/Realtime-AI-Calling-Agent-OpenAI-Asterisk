# Conversation Logging System

This document describes the enhanced conversation logging system implemented in the Asterisk Python calling agent, inspired by the Node.js test implementation.

## Features

### 1. Event Counters
- **Client Events (C-0001, C-0002, ...)**: Track all client-side actions like WebSocket connections, session creation, and response requests
- **OpenAI Events (O-0001, O-0002, ...)**: Track all OpenAI-side events like transcriptions, barge-in detection, and audio processing

### 2. Colored Output
- **Cyan**: Client events (C-0001, C-0002, ...)
- **Yellow**: OpenAI events (O-0001, O-0002, ...)
- **Default**: Regular system messages

### 3. Conversation Tracking
- **User Messages**: Logged with [USER] prefix
- **Agent Responses**: Logged with [AGENT] prefix
- **Transcript Events**: Completed transcriptions only (deltas can be enabled)
- **Barge-in Detection**: When users interrupt the agent

## Configuration

Add these settings to your `config.conf`:

```bash
# Conversation logging settings
ENABLE_CONVERSATION_LOGGING=true
LOG_CONVERSATION_COUNTERS=true
LOG_COLORED_OUTPUT=true
LOG_TRANSCRIPT_DELTAS=false
```

## Usage

### Basic Logging Functions

```python
from config import log_client, log_openai, log_conversation

# Log client-side events
log_client("WebSocket connected for channel_123")

# Log OpenAI-side events
log_openai("User transcript for channel_123: Hello, how are you?")

# Log conversation exchanges
log_conversation(
    user_msg="I want to travel from Dhaka to Sylhet",
    agent_msg="I understand you want to travel from Dhaka to Sylhet. When would you like to travel?",
    channel_id="channel_123"
)
```

### Event Types Logged

#### Client Events (C-0001, C-0002, ...)
- WebSocket connections
- Session creation
- Response requests
- Assistant responses
- Audio processing completion

#### OpenAI Events (O-0001, O-0002, ...)
- Session updates
- User transcriptions
- Barge-in detection
- Completed audio transcripts (deltas configurable)
- Error messages

## Example Output

```
C-0001 | 2024-01-15 10:30:15 - WebSocket connected for channel_123
O-0001 | 2024-01-15 10:30:16 - Session updated for channel_123
C-0002 | 2024-01-15 10:30:17 - Session created for channel_123
O-0002 | 2024-01-15 10:30:18 - User transcript for channel_123: Hello, how are you?
C-0003 | 2024-01-15 10:30:19 - Assistant response for channel_123: Hi there! How can I help you today?
```

## Testing

Run the test script to see the logging system in action:

```bash
python test_conversation_logging.py
```

## Implementation Details

The system uses a custom logging formatter that:
1. Detects conversation log messages via `extra={'conversation_type': 'client'}` or `extra={'conversation_type': 'openai'}`
2. Automatically increments counters for each type
3. Formats output with colored prefixes
4. Maintains chronological order of events

## Benefits

1. **Clear Event Tracking**: Easy to follow conversation flow with numbered events
2. **Visual Distinction**: Color coding helps identify event types at a glance
3. **Debugging Support**: Detailed logging of all conversation components
4. **Performance Monitoring**: Track audio processing and response times
5. **User Experience**: Monitor barge-in detection and transcription accuracy

## Troubleshooting

If conversation logging isn't working:

1. Check that `ENABLE_CONVERSATION_LOGGING=true` in config.conf
2. Verify `LOG_LEVEL` is set to `info` or lower
3. Ensure the logging functions are imported correctly
4. Check console output for any error messages

## Future Enhancements

- Export conversation logs to files
- Add timestamps to individual events
- Implement conversation analytics
- Add performance metrics tracking
