#!/usr/bin/env python3
"""
Test script to demonstrate the new conversation logging system
"""
import asyncio
import logging
from config import setup_logging, log_client, log_openai, log_conversation

async def test_conversation_logging():
    """Test the conversation logging system"""
    # Setup logging
    logger = setup_logging()
    
    print("🚀 Testing Conversation Logging System")
    print("=" * 50)
    
    # Test basic logging
    logger.info("Regular log message")
    
    # Test client-side logging (C-0001, C-0002, etc.)
    log_client("WebSocket connected for channel_123")
    log_client("Session created for channel_123")
    log_client("Requested response for channel_123")
    
    # Test OpenAI-side logging (O-0001, O-0002, etc.)
    log_openai("Session updated for channel_123")
    log_openai("User transcript for channel_123: Hello, how are you?")
    log_openai("Barge-in detected for channel_123; canceling playback")
    
    # Test conversation logging
    log_conversation(
        user_msg="I want to travel from Dhaka to Sylhet",
        agent_msg="I understand you want to travel from Dhaka to Sylhet. When would you like to travel?",
        channel_id="channel_123"
    )
    
    # Test more client events
    log_client("Assistant response for channel_123: I understand you want to travel from Dhaka to Sylhet. When would you like to travel?")
    log_client("Response audio done for channel_123, total bytes: 15000")
    
    # Test more OpenAI events
    log_openai("Transcript delta for channel_123: I want to travel")
    log_openai("User transcript completed for channel_123: I want to travel from Dhaka to Sylhet")
    
    print("\n✅ Conversation logging test completed!")
    print("Check the console output above to see the counter system (C-0001, O-0001, etc.)")

if __name__ == "__main__":
    asyncio.run(test_conversation_logging())
