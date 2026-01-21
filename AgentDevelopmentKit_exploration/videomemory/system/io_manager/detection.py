"""Cross-platform device detection for input/output streams."""

import os
import glob
import platform
import subprocess
from typing import Dict, List, Optional


class DeviceDetector:
    """Detects input devices across different operating systems."""
    
    def __init__(self):
        """Initialize the detector with platform-specific settings."""
        self.platform = platform.system().lower()
        self.is_linux = self.platform == 'linux'
        self.is_mac = self.platform == 'darwin'
        self.is_windows = self.platform == 'windows'
    
    def _run_command(self, cmd: List[str], timeout: int = 2) -> Optional[str]:
        """Run a system command and return stdout, or None on failure."""
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            return result.stdout if result.returncode == 0 else None
        except (subprocess.TimeoutExpired, FileNotFoundError, subprocess.SubprocessError):
            return None
    
    def _read_file(self, path: str) -> Optional[str]:
        """Read a file and return its content, or None on failure."""
        try:
            with open(path, 'r') as f:
                return f.read().strip()
        except (IOError, OSError):
            return None
    
    def detect_keyboards(self) -> List[str]:
        """Detect keyboard devices."""
        if self.is_linux:
            return self._detect_linux_keyboards()
        elif self.is_mac:
            return self._detect_mac_keyboards()
        else:
            return ["Keyboard (detected)"]
    
    def detect_mice(self) -> List[str]:
        """Detect mouse and trackpad devices."""
        if self.is_linux:
            return self._detect_linux_mice()
        elif self.is_mac:
            return self._detect_mac_mice()
        else:
            return ["Mouse/Trackpad (detected)"]
    
    def detect_screens(self) -> List[str]:
        """Detect display/monitor devices."""
        if self.is_linux:
            return self._detect_linux_screens()
        elif self.is_mac:
            return self._detect_mac_screens()
        else:
            return ["Display (detected)"]
    
    def detect_cameras(self) -> List[str]:
        """Detect camera devices."""
        if self.is_linux:
            return self._detect_linux_cameras()
        elif self.is_mac:
            return self._detect_mac_cameras()
        else:
            return []
    
    def detect_com_ports(self) -> List[str]:
        """Detect COM/serial ports."""
        if self.is_linux:
            return self._detect_linux_com_ports()
        elif self.is_mac:
            return self._detect_mac_com_ports()
        else:
            return []
    
    def detect_audio_input(self) -> List[str]:
        """Detect audio input devices."""
        if self.is_linux:
            return self._detect_linux_audio_input()
        elif self.is_mac:
            return self._detect_mac_audio_input()
        else:
            return ["Microphone (detected)"]
    
    def detect_all(self) -> Dict[str, List[str]]:
        """Detect all available input devices.
        
        Returns:
            dict: A dictionary containing lists of available input devices by category
        """
        return {
            # "keyboard": self.detect_keyboards(),
            # "mouse": self.detect_mice(),
            # "screen": self.detect_screens(),
            "camera": self.detect_cameras(),
            # "com_ports": self.detect_com_ports(),
            # "audio_input": self.detect_audio_input(),
        }
    
    # Linux-specific detection methods
    def _detect_linux_keyboards(self) -> List[str]:
        """Detect keyboard devices on Linux."""
        devices = []
        try:
            for suffix in ["kbd", "keyboard"]:
                for path in glob.glob(f"/dev/input/by-id/*-{suffix}"):
                    name = os.path.basename(path).replace(f"-{suffix}", "")
                    devices.append(name)
            
            for device_file in glob.glob("/sys/class/input/input*/name"):
                device_name = self._read_file(device_file)
                if device_name and any(filt in device_name.lower() for filt in ["keyboard", "kbd"]):
                    input_dir = os.path.dirname(device_file)
                    caps_file = os.path.join(input_dir, "capabilities", "ev")
                    caps_str = self._read_file(caps_file)
                    if caps_str:
                        try:
                            if int(caps_str, 16) & 0x2:  # EV_KEY capability
                                devices.append(device_name)
                        except ValueError:
                            continue
        except Exception:
            pass
        return list(set(devices)) if devices else ["Keyboard (detected)"]
    
    def _detect_linux_mice(self) -> List[str]:
        """Detect mouse and trackpad devices on Linux."""
        devices = []
        try:
            for suffix in ["mouse", "trackpad"]:
                for path in glob.glob(f"/dev/input/by-id/*-{suffix}"):
                    name = os.path.basename(path).replace(f"-{suffix}", "")
                    devices.append(name)
            
            for device_file in glob.glob("/sys/class/input/input*/name"):
                device_name = self._read_file(device_file)
                if device_name and any(filt in device_name.lower() for filt in ["mouse", "trackpad", "touchpad"]):
                    input_dir = os.path.dirname(device_file)
                    caps_file = os.path.join(input_dir, "capabilities", "ev")
                    caps_str = self._read_file(caps_file)
                    if caps_str:
                        try:
                            if int(caps_str, 16) & 0x2:
                                devices.append(device_name)
                        except ValueError:
                            continue
        except Exception:
            pass
        return list(set(devices)) if devices else ["Mouse/Trackpad (detected)"]
    
    def _detect_linux_screens(self) -> List[str]:
        """Detect display/monitor devices on Linux."""
        screens = []
        output = self._run_command(["xrandr", "--query"])
        if output:
            for line in output.split('\n'):
                if ' connected' in line:
                    parts = line.split()
                    if len(parts) >= 2:
                        screen_name = parts[0]
                        resolution = next((p for p in parts if 'x' in p and p[0].isdigit()), None)
                        screens.append(f"{screen_name} ({resolution})" if resolution else screen_name)
        
        if not screens:
            for status_file in glob.glob("/sys/class/drm/card*/status"):
                if self._read_file(status_file) == "connected":
                    card_name = os.path.basename(os.path.dirname(status_file))
                    screens.append(f"Display ({card_name})")
        
        return screens if screens else ["Display (detected)"]
    
    def _detect_linux_cameras(self) -> List[str]:
        """Detect camera devices on Linux using Video4Linux2."""
        cameras = []
        for device in sorted(glob.glob("/dev/video*")):
            output = self._run_command(["v4l2-ctl", "--device", device, "--info"], timeout=1)
            if output:
                name = next((line.split(':', 1)[1].strip() for line in output.split('\n') 
                           if 'Card type' in line or 'Driver name' in line), None)
                cameras.append(f"{name} ({device})" if name else f"Camera ({device})")
            else:
                cameras.append(f"Camera ({device})")
        return cameras
    
    def _detect_linux_com_ports(self) -> List[str]:
        """Detect COM/serial ports on Linux."""
        ports = []
        patterns = ["/dev/ttyUSB*", "/dev/ttyACM*", "/dev/ttyS*", "/dev/ttyAMA*"]
        for pattern in patterns:
            ports.extend([d for d in glob.glob(pattern) if os.path.exists(d)])
        
        try:
            import serial.tools.list_ports
            ports.extend(f"{p.device} ({p.description})" for p in serial.tools.list_ports.comports())
        except ImportError:
            pass
        
        return list(set(sorted(ports)))
    
    def _detect_linux_audio_input(self) -> List[str]:
        """Detect audio input devices on Linux."""
        output = self._run_command(["pactl", "list", "short", "sources"])
        if output:
            audio_inputs = [line.split('\t')[1] for line in output.split('\n') 
                          if line.strip() and len(line.split('\t')) >= 2 
                          and 'monitor' not in line.split('\t')[1].lower()]
            if audio_inputs:
                return audio_inputs
        
        output = self._run_command(["arecord", "-l"])
        if output:
            audio_inputs = [line.split("'")[1] for line in output.split('\n')
                          if 'card' in line.lower() and 'device' in line.lower() and "'" in line]
            if audio_inputs:
                return audio_inputs
        
        return ["Microphone (detected)"]
    
    # macOS-specific detection methods
    def _detect_mac_keyboards(self) -> List[str]:
        """Detect keyboard devices on macOS."""
        devices = []
        output = self._run_command(["system_profiler", "SPUSBDataType"])
        if output:
            for line in output.split('\n'):
                if 'keyboard' in line.lower() or 'kbd' in line.lower():
                    # Extract device name
                    parts = line.split(':')
                    if len(parts) >= 2:
                        devices.append(parts[1].strip())
        
        # Also check IOKit
        output = self._run_command(["ioreg", "-p", "IOUSB", "-w0"])
        if output:
            for line in output.split('\n'):
                if 'keyboard' in line.lower():
                    # Extract device name from IORegistry
                    if '"Product Name"' in line:
                        name = line.split('=')[-1].strip().strip('"')
                        if name:
                            devices.append(name)
        
        return list(set(devices)) if devices else ["Keyboard (detected)"]
    
    def _detect_mac_mice(self) -> List[str]:
        """Detect mouse and trackpad devices on macOS."""
        devices = []
        output = self._run_command(["system_profiler", "SPUSBDataType"])
        if output:
            for line in output.split('\n'):
                if any(term in line.lower() for term in ["mouse", "trackpad", "touchpad"]):
                    parts = line.split(':')
                    if len(parts) >= 2:
                        devices.append(parts[1].strip())
        
        # Built-in trackpad
        output = self._run_command(["system_profiler", "SPTrackpadDataType"])
        if output:
            devices.append("Built-in Trackpad")
        
        return list(set(devices)) if devices else ["Mouse/Trackpad (detected)"]
    
    def _detect_mac_screens(self) -> List[str]:
        """Detect display/monitor devices on macOS."""
        screens = []
        output = self._run_command(["system_profiler", "SPDisplaysDataType"])
        if output:
            for line in output.split('\n'):
                if 'Resolution:' in line or 'Display Type:' in line:
                    # Extract display info
                    parts = line.split(':')
                    if len(parts) >= 2:
                        screens.append(f"Display ({parts[1].strip()})")
        
        # Also try displayplacer (if available)
        output = self._run_command(["displayplacer", "list"])
        if output:
            for line in output.split('\n'):
                if 'Resolution:' in line:
                    screens.append(line.strip())
        
        return screens if screens else ["Display (detected)"]
    
    def _detect_mac_cameras(self) -> List[str]:
        """Detect camera devices on macOS."""
        cameras = []
        output = self._run_command(["system_profiler", "SPCameraDataType"])
        if output:
            for line in output.split('\n'):
                if 'Camera' in line or 'iSight' in line:
                    parts = line.split(':')
                    if len(parts) >= 2:
                        cameras.append(parts[1].strip())
        
        # Check AVFoundation devices
        try:
            result = subprocess.run(["ffmpeg", "-f", "avfoundation", "-list_devices", "true", "-i", ""],
                                  capture_output=True, text=True, timeout=2)
            if result.returncode == 0:
                for line in result.stdout.split('\n'):
                    if 'AVFoundation video device' in line:
                        name = line.split(']')[-1].strip()
                        if name:
                            cameras.append(name)
        except Exception:
            pass
        
        return cameras if cameras else []
    
    def _detect_mac_com_ports(self) -> List[str]:
        """Detect COM/serial ports on macOS."""
        ports = []
        # macOS uses /dev/cu.* for serial ports
        for pattern in ["/dev/cu.*", "/dev/tty.*"]:
            ports.extend([d for d in glob.glob(pattern) if os.path.exists(d)])
        
        try:
            import serial.tools.list_ports
            ports.extend(f"{p.device} ({p.description})" for p in serial.tools.list_ports.comports())
        except ImportError:
            pass
        
        return list(set(sorted(ports)))
    
    def _detect_mac_audio_input(self) -> List[str]:
        """Detect audio input devices on macOS."""
        audio_inputs = []
        output = self._run_command(["system_profiler", "SPAudioDataType"])
        if output:
            for line in output.split('\n'):
                if 'Input' in line or 'Microphone' in line:
                    parts = line.split(':')
                    if len(parts) >= 2:
                        audio_inputs.append(parts[1].strip())
        
        # Also try ffmpeg/AVFoundation
        try:
            result = subprocess.run(["ffmpeg", "-f", "avfoundation", "-list_devices", "true", "-i", ""],
                                  capture_output=True, text=True, timeout=2)
            if result.returncode == 0:
                for line in result.stdout.split('\n'):
                    if 'AVFoundation audio device' in line:
                        name = line.split(']')[-1].strip()
                        if name:
                            audio_inputs.append(name)
        except Exception:
            pass
        
        return audio_inputs if audio_inputs else ["Microphone (detected)"]


def main():
    """Test all device detection methods and display results."""
    print("=" * 80)
    print("Device Detection Test")
    print("=" * 80)
    
    detector = DeviceDetector()
    
    # Display platform information
    print(f"\nPlatform: {platform.system()} ({platform.release()})")
    print(f"Platform flags: Linux={detector.is_linux}, macOS={detector.is_mac}, Windows={detector.is_windows}")
    print()
    
    # Test all detection methods
    detection_tests = [
        ("Cameras", detector.detect_cameras),
        ("Screens/Displays", detector.detect_screens),
        ("Keyboards", detector.detect_keyboards),
        ("Mice/Trackpads", detector.detect_mice),
        ("Audio Input", detector.detect_audio_input),
        ("COM/Serial Ports", detector.detect_com_ports),
    ]
    
    results = {}
    
    for category, detection_func in detection_tests:
        print(f"{'=' * 80}")
        print(f"Testing {category}...")
        print(f"{'=' * 80}")
        try:
            devices = detection_func()
            results[category] = devices
            if devices:
                print(f"Found {len(devices)} device(s):")
                for i, device in enumerate(devices, 1):
                    print(f"  {i}. {device}")
            else:
                print("  No devices found.")
        except Exception as e:
            print(f"  ERROR: {type(e).__name__}: {e}")
            results[category] = []
        print()
    
    # Test detect_all()
    print(f"{'=' * 80}")
    print("Testing detect_all()...")
    print(f"{'=' * 80}")
    try:
        all_devices = detector.detect_all()
        for category, devices in all_devices.items():
            print(f"{category}: {len(devices)} device(s)")
            for device in devices:
                print(f"  - {device}")
    except Exception as e:
        print(f"ERROR: {type(e).__name__}: {e}")
    print()
    
    # Summary
    print(f"{'=' * 80}")
    print("SUMMARY")
    print(f"{'=' * 80}")
    total_devices = 0
    for category, devices in results.items():
        count = len(devices)
        total_devices += count
        status = "✓" if count > 0 else "✗"
        print(f"{status} {category}: {count} device(s)")
        if count > 0:
            for device in devices:
                print(f"    - {device}")
    
    print(f"\nTotal devices detected: {total_devices}")
    print("=" * 80)


if __name__ == "__main__":
    main()

