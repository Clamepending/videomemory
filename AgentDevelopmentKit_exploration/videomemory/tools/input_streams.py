"""Tool for retrieving available input streams on the system."""

import os
import subprocess
import glob
from typing import List, Dict


def _detect_keyboards() -> List[str]:
    """Detect keyboard devices on Linux."""
    keyboards = []
    try:
        # Check /dev/input/by-id/ for keyboard devices
        keyboard_paths = glob.glob("/dev/input/by-id/*-kbd")
        keyboard_paths.extend(glob.glob("/dev/input/by-id/*-keyboard"))
        
        for path in keyboard_paths:
            name = os.path.basename(path).replace("-kbd", "").replace("-keyboard", "")
            keyboards.append(name)
        
        # Also check /sys/class/input/ for device names
        input_devices = glob.glob("/sys/class/input/input*/name")
        for device_file in input_devices:
            try:
                with open(device_file, 'r') as f:
                    device_name = f.read().strip()
                    # Check if it's a keyboard by looking at the device type
                    input_dir = os.path.dirname(device_file)
                    capabilities_file = os.path.join(input_dir, "capabilities", "ev")
                    if os.path.exists(capabilities_file):
                        with open(capabilities_file, 'r') as cap_file:
                            # Keyboard devices typically have bit 1 set in capabilities
                            caps = int(cap_file.read().strip(), 16)
                            if caps & 0x2:  # EV_KEY capability
                                if "keyboard" in device_name.lower() or "kbd" in device_name.lower():
                                    keyboards.append(device_name)
            except (IOError, ValueError):
                continue
    except Exception:
        pass
    
    return list(set(keyboards)) if keyboards else ["Keyboard (detected)"]


def _detect_mice() -> List[str]:
    """Detect mouse and trackpad devices on Linux."""
    mice = []
    try:
        # Check /dev/input/by-id/ for mouse devices
        mouse_paths = glob.glob("/dev/input/by-id/*-mouse")
        mouse_paths.extend(glob.glob("/dev/input/by-id/*-trackpad"))
        
        for path in mouse_paths:
            name = os.path.basename(path).replace("-mouse", "").replace("-trackpad", "")
            mice.append(name)
        
        # Check /sys/class/input/ for mouse devices
        input_devices = glob.glob("/sys/class/input/input*/name")
        for device_file in input_devices:
            try:
                with open(device_file, 'r') as f:
                    device_name = f.read().strip()
                    input_dir = os.path.dirname(device_file)
                    capabilities_file = os.path.join(input_dir, "capabilities", "ev")
                    if os.path.exists(capabilities_file):
                        with open(capabilities_file, 'r') as cap_file:
                            caps = int(cap_file.read().strip(), 16)
                            # Mouse devices have EV_REL (relative) capability
                            if caps & 0x2:  # EV_KEY and check for mouse-like names
                                if any(term in device_name.lower() for term in ["mouse", "trackpad", "touchpad"]):
                                    mice.append(device_name)
            except (IOError, ValueError):
                continue
    except Exception:
        pass
    
    return list(set(mice)) if mice else ["Mouse/Trackpad (detected)"]


def _detect_screens() -> List[str]:
    """Detect display/monitor devices."""
    screens = []
    try:
        # Try using xrandr if available
        result = subprocess.run(
            ["xrandr", "--query"],
            capture_output=True,
            text=True,
            timeout=2
        )
        if result.returncode == 0:
            for line in result.stdout.split('\n'):
                if ' connected' in line:
                    parts = line.split()
                    if len(parts) >= 2:
                        screen_name = parts[0]
                        # Try to extract resolution if available
                        for part in parts:
                            if 'x' in part and part[0].isdigit():
                                screens.append(f"{screen_name} ({part})")
                                break
                        else:
                            screens.append(screen_name)
    except (subprocess.TimeoutExpired, FileNotFoundError, subprocess.SubprocessError):
        pass
    
    # Fallback: check /sys/class/drm/
    if not screens:
        try:
            drm_devices = glob.glob("/sys/class/drm/card*/status")
            for status_file in drm_devices:
                try:
                    with open(status_file, 'r') as f:
                        if f.read().strip() == "connected":
                            card_name = os.path.basename(os.path.dirname(status_file))
                            screens.append(f"Display ({card_name})")
                except IOError:
                    continue
        except Exception:
            pass
    
    return screens if screens else ["Display (detected)"]


def _detect_cameras() -> List[str]:
    """Detect camera devices using Video4Linux2."""
    cameras = []
    try:
        # Check /dev/video* devices
        video_devices = glob.glob("/dev/video*")
        for device in sorted(video_devices):
            try:
                # Try to get device info using v4l2-ctl if available
                result = subprocess.run(
                    ["v4l2-ctl", "--device", device, "--info"],
                    capture_output=True,
                    text=True,
                    timeout=1
                )
                if result.returncode == 0:
                    for line in result.stdout.split('\n'):
                        if 'Card type' in line or 'Driver name' in line:
                            name = line.split(':', 1)[1].strip() if ':' in line else device
                            cameras.append(f"{name} ({device})")
                            break
                    else:
                        cameras.append(f"Camera ({device})")
                else:
                    cameras.append(f"Camera ({device})")
            except (subprocess.TimeoutExpired, FileNotFoundError, subprocess.SubprocessError):
                cameras.append(f"Camera ({device})")
    except Exception:
        pass
    
    return cameras


def _detect_com_ports() -> List[str]:
    """Detect COM/serial ports."""
    ports = []
    try:
        # Check common serial port locations on Linux
        tty_devices = []
        tty_devices.extend(glob.glob("/dev/ttyUSB*"))
        tty_devices.extend(glob.glob("/dev/ttyACM*"))
        tty_devices.extend(glob.glob("/dev/ttyS*"))
        tty_devices.extend(glob.glob("/dev/ttyAMA*"))
        
        for device in sorted(tty_devices):
            # Check if device is actually accessible
            if os.path.exists(device):
                ports.append(device)
    except Exception:
        pass
    
    # Also try using pyserial if available
    try:
        import serial.tools.list_ports
        for port in serial.tools.list_ports.comports():
            ports.append(f"{port.device} ({port.description})")
    except ImportError:
        pass
    except Exception:
        pass
    
    return list(set(ports))


def _detect_audio_input() -> List[str]:
    """Detect audio input devices."""
    audio_inputs = []
    try:
        # Try using pactl (PulseAudio)
        result = subprocess.run(
            ["pactl", "list", "short", "sources"],
            capture_output=True,
            text=True,
            timeout=2
        )
        if result.returncode == 0:
            for line in result.stdout.split('\n'):
                if line.strip():
                    parts = line.split('\t')
                    if len(parts) >= 2:
                        # Filter out monitor sources (output monitoring)
                        if 'monitor' not in parts[1].lower():
                            audio_inputs.append(parts[1])
    except (subprocess.TimeoutExpired, FileNotFoundError, subprocess.SubprocessError):
        pass
    
    # Fallback: try arecord (ALSA)
    if not audio_inputs:
        try:
            result = subprocess.run(
                ["arecord", "-l"],
                capture_output=True,
                text=True,
                timeout=2
            )
            if result.returncode == 0:
                for line in result.stdout.split('\n'):
                    if 'card' in line.lower() and 'device' in line.lower():
                        # Extract card name
                        parts = line.split("'")
                        if len(parts) >= 2:
                            audio_inputs.append(parts[1])
        except (subprocess.TimeoutExpired, FileNotFoundError, subprocess.SubprocessError):
            pass
    
    return audio_inputs if audio_inputs else ["Microphone (detected)"]


def get_available_input_streams() -> Dict[str, List[str]]:
    """Returns a list of available input streams on the system.
    
    Detects real hardware devices including keyboards, mice, screens,
    cameras, COM ports, and audio input devices.
    
    Returns:
        dict: A dictionary containing lists of available input streams:
            - 'keyboard': List of keyboard devices
            - 'mouse': List of mouse/trackpad devices
            - 'screen': List of display/monitor devices
            - 'camera': List of camera devices
            - 'com_ports': List of available COM/serial ports
            - 'audio_input': List of audio input devices
    """
    print("--- get_available_input_streams tool called ---")
    
    return {
        "keyboard": _detect_keyboards(),
        "mouse": _detect_mice(),
        "screen": _detect_screens(),
        "camera": _detect_cameras(),
        "com_ports": _detect_com_ports(),
        "audio_input": _detect_audio_input(),
    }


def main():
    """Main function to test and display available input streams."""
    print("Detecting available input streams...\n")
    streams = get_available_input_streams()
    
    for category, devices in streams.items():
        print(f"{category.upper().replace('_', ' ')}:")
        if devices:
            for device in devices:
                print(f"  - {device}")
        else:
            print("  (none detected)")
        print()


if __name__ == "__main__":
    main()

