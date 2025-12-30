"""Tool for retrieving available input streams on the system."""

from typing import List, Dict


def get_available_input_streams() -> Dict[str, List[str]]:
    """Returns a list of available input streams on the system.
    
    This is a mock implementation that simulates available input devices
    such as keyboard, mouse, screen, cameras, and COM ports.
    
    Returns:
        dict: A dictionary containing lists of available input streams:
            - 'keyboard': List of keyboard devices
            - 'mouse': List of mouse/trackpad devices
            - 'screen': List of display/monitor devices
            - 'camera': List of camera devices
            - 'com_ports': List of available COM/serial ports
            - 'audio_input': List of audio input devices
    """
    print("--- Mock get_available_input_streams tool called ---")
    # Mock data representing available input streams
    return {
        "keyboard": [
            "USB Keyboard (Generic)",
            "Built-in Keyboard",
        ],
        "mouse": [
            "USB Optical Mouse",
            "Trackpad",
        ],
        "screen": [
            "Primary Display (1920x1080)",
            "Secondary Display (2560x1440)",
        ],
        "camera": [
            "Front-facing Camera (Built-in)",
            "USB Webcam (Logitech)",
        ],
        "com_ports": [
            "COM1",
            "COM3",
            "/dev/ttyUSB0",
            "/dev/ttyACM0",
        ],
        "audio_input": [
            "Built-in Microphone",
            "USB Headset Microphone",
        ],
    }

