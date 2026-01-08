"""Logging configuration for the video memory system."""

import logging
from pathlib import Path


def setup_logging(log_dir: Path = None) -> Path:
    """Configure logging to write to a log file.
    
    Args:
        log_dir: Optional directory path for logs. If None, uses a 'logs' directory
                 relative to the project root (where main.py is located).
    
    Returns:
        Path to the log file that was created.
    """
    # Determine log directory
    if log_dir is None:
        # Get the project root (assuming this file is in system/, go up two levels)
        project_root = Path(__file__).parent.parent
        log_dir = project_root / "logs"
    
    # Create logs directory if it doesn't exist
    log_dir.mkdir(exist_ok=True)
    
    # Set up log file path
    log_file = log_dir / "videomemory.log"
    
    # Configure logging
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file, mode='w'),  # Write mode - clears file on each run
            # Optionally, you can also log to console with a higher level
            # logging.StreamHandler()  # Uncomment if you want console output too
        ]
    )
    
    # Set specific logger levels
    logging.getLogger('VideoStreamIngestor').setLevel(logging.DEBUG)
    logging.getLogger('TaskManager').setLevel(logging.DEBUG)
    logging.getLogger('tasks').setLevel(logging.DEBUG)
    logging.getLogger('main').setLevel(logging.DEBUG)
    
    print(f"Logging to: {log_file}")
    return log_file

