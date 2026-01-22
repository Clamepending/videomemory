"""Logging configuration for the video memory system."""

import logging
from pathlib import Path


def setup_logging(log_dir: Path = None) -> dict:
    """Configure logging to write to separate log files by severity.
    
    Args:
        log_dir: Optional directory path for logs. If None, uses a 'logs' directory
                 relative to the project root (where main.py is located).
    
    Returns:
        Dictionary mapping log levels to their file paths.
    """
    # Determine log directory
    if log_dir is None:
        # Get the project root (assuming this file is in system/, go up two levels)
        project_root = Path(__file__).parent.parent
        log_dir = project_root / "logs"
    
    # Create logs directory if it doesn't exist
    log_dir.mkdir(exist_ok=True)
    
    # Set up separate log files for each severity level
    log_files = {
        'debug': log_dir / "debug.log",
        'info': log_dir / "info.log",
        'warning': log_dir / "warning.log",
        'error': log_dir / "error.log",
        'critical': log_dir / "critical.log"
    }
    
    # Create handlers for each severity level
    # Each handler will capture that level and all higher levels
    handlers = []
    
    # DEBUG handler - captures DEBUG and above
    debug_handler = logging.FileHandler(log_files['debug'], mode='w')
    debug_handler.setLevel(logging.DEBUG)
    handlers.append(debug_handler)
    
    # INFO handler - captures INFO and above
    info_handler = logging.FileHandler(log_files['info'], mode='w')
    info_handler.setLevel(logging.INFO)
    handlers.append(info_handler)
    
    # WARNING handler - captures WARNING and above
    warning_handler = logging.FileHandler(log_files['warning'], mode='w')
    warning_handler.setLevel(logging.WARNING)
    handlers.append(warning_handler)
    
    # ERROR handler - captures ERROR and above
    error_handler = logging.FileHandler(log_files['error'], mode='w')
    error_handler.setLevel(logging.ERROR)
    handlers.append(error_handler)
    
    # CRITICAL handler - captures CRITICAL only
    critical_handler = logging.FileHandler(log_files['critical'], mode='w')
    critical_handler.setLevel(logging.CRITICAL)
    handlers.append(critical_handler)
    
    # Configure logging with all handlers
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=handlers
    )
    
    # Set specific logger levels
    logging.getLogger('VideoStreamIngestor').setLevel(logging.DEBUG)
    logging.getLogger('TaskManager').setLevel(logging.DEBUG)
    logging.getLogger('tasks').setLevel(logging.DEBUG)
    logging.getLogger('main').setLevel(logging.DEBUG)
    
    # Create dedicated log file for VideoStreamIngestor
    video_ingestor_log_file = log_dir / "video_ingestor.log"
    
    # Get or create the VideoStreamIngestor logger
    video_ingestor_logger = logging.getLogger('VideoStreamIngestor')
    
    # Remove any existing handlers to avoid duplicates if setup_logging() is called multiple times
    for handler in video_ingestor_logger.handlers[:]:
        video_ingestor_logger.removeHandler(handler)
    
    # Create and configure the dedicated handler for video ingestor
    video_ingestor_handler = logging.FileHandler(video_ingestor_log_file, mode='w')
    video_ingestor_handler.setLevel(logging.DEBUG)
    video_ingestor_handler.setFormatter(
        logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    )
    
    # Add handler to VideoStreamIngestor logger only
    video_ingestor_logger.addHandler(video_ingestor_handler)
    # Disable propagation to prevent logs from also appearing in general log files
    video_ingestor_logger.propagate = False
    # Ensure the logger level is set to DEBUG to capture all messages
    video_ingestor_logger.setLevel(logging.DEBUG)
    
    print(f"Logging to separate files by severity:")
    for level, file_path in log_files.items():
        print(f"  {level.upper()}: {file_path}")
    print(f"  VideoStreamIngestor: {video_ingestor_log_file}")
    
    # Add video_ingestor log file to return dict
    log_files['video_ingestor'] = video_ingestor_log_file
    
    return log_files

