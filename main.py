"""
Main application for Python-based Asterisk calling agent
"""
import asyncio
import signal
import sys
import logging
from config import setup_logging, validate_config, config
from asterisk_client import asterisk_client
from openai_realtime_client import openai_realtime_client
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

# Initialize console and logging
console = Console()
logger = setup_logging()

class AsteriskCallingAgent:
    """Main application class for the calling agent"""
    
    def __init__(self):
        self.is_running = False
        self.shutdown_event = asyncio.Event()
        
    async def start(self):
        """Start the calling agent"""
        try:
            console.print(Panel.fit(
                "[bold blue]Asterisk Calling Agent[/bold blue]\n"
                "[green]Python-based calling agent with OpenAI Realtime[/green]",
                title="🚀 Starting Up",
                border_style="blue"
            ))
            
            # Validate configuration
            validate_config()
            
            # Health checks
            await self._perform_health_checks()
            
            # Connect to Asterisk
            console.print("[yellow]Connecting to Asterisk ARI...[/yellow]")
            await asterisk_client.connect()
            
            # Start the main loop
            self.is_running = True
            console.print(Panel.fit(
                "[bold green]✅ Agent started successfully![/bold green]\n"
                f"Listening for calls on extension [bold]9999[/bold]\n"
                f"Active calls: [bold]0[/bold]\n"
                f"Max concurrent calls: [bold]{config.MAX_CONCURRENT_CALLS}[/bold]",
                title="🎯 Ready for Calls",
                border_style="green"
            ))
            
            # Wait for shutdown signal
            await self.shutdown_event.wait()
            
        except Exception as e:
            console.print(f"[bold red]❌ Failed to start agent: {str(e)}[/bold red]")
            logger.error(f"Startup failed: {str(e)}")
            sys.exit(1)
            
    async def _perform_health_checks(self):
        """Perform health checks for external services"""
        console.print("[yellow]Performing health checks...[/yellow]")
        
        # Check OpenAI Realtime WS accessibility
        console.print("[blue]Checking OpenAI Realtime...[/blue]")
        ok = await openai_realtime_client.health_check()
        if ok:
            console.print("[green]✅ OpenAI Realtime: OK[/green]")
        else:
            console.print("[red]❌ OpenAI Realtime: Failed[/red]")
            raise Exception("OpenAI Realtime health check failed")
            
        console.print("[green]✅ All health checks passed![/green]")
        
    async def stop(self):
        """Stop the calling agent"""
        if not self.is_running:
            return
            
        console.print("[yellow]Shutting down calling agent...[/yellow]")
        
        try:
            # Close Asterisk connection
            if asterisk_client.is_connection_active():
                await asterisk_client.close()
                
            # Set shutdown event
            self.shutdown_event.set()
            self.is_running = False
            
            console.print("[green]✅ Agent stopped successfully[/green]")
            
        except Exception as e:
            console.print(f"[red]❌ Error during shutdown: {str(e)}[/red]")
            logger.error(f"Shutdown error: {str(e)}")
            
    def signal_handler(self, signum, frame):
        """Handle shutdown signals"""
        console.print(f"\n[yellow]Received signal {signum}, shutting down...[/yellow]")
        asyncio.create_task(self.stop())

async def main():
    """Main application entry point"""
    agent = AsteriskCallingAgent()
    
    # Set up signal handlers
    signal.signal(signal.SIGINT, agent.signal_handler)
    signal.signal(signal.SIGTERM, agent.signal_handler)
    
    try:
        await agent.start()
    except KeyboardInterrupt:
        console.print("\n[yellow]Received keyboard interrupt[/yellow]")
    finally:
        await agent.stop()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        console.print("\n[yellow]Application interrupted[/yellow]")
    except Exception as e:
        console.print(f"[bold red]Fatal error: {str(e)}[/bold red]")
        logger.error(f"Fatal error: {str(e)}")
        sys.exit(1)
