"""
TUN Manager - Create and manage TUN virtual network interface
Routes all system traffic through Xray-core via tun2socks

Flow: Apps -> tun0 -> tun2socks -> Xray SOCKS5 -> Remote Server
"""

import os
import sys
import signal
import subprocess
import threading
import time
import platform
import stat
import urllib.request
import zipfile
import shutil
from typing import Optional, Tuple
from PyQt6.QtCore import QObject, pyqtSignal


class TunManager(QObject):
    """Manages TUN device and tun2socks for system-wide VPN"""
    
    # Signals
    status_changed = pyqtSignal(str)   # status message
    error_occurred = pyqtSignal(str)   # error message
    download_progress = pyqtSignal(int)  # 0-100
    
    TUN2SOCKS_VERSION = "2.5.2"
    TUN_DEVICE = "tun0"
    TUN_IP = "10.0.0.1"
    TUN_NETMASK = "24"
    TUN_GATEWAY = "10.0.0.2"
    
    def __init__(self, socks_port: int = 10808):
        super().__init__()
        
        self.socks_port = socks_port
        self.tun2socks_process: Optional[subprocess.Popen] = None
        self._active = False
        
        # Store original routing info for cleanup
        self._original_gateway = None
        self._original_interface = None
        self._remote_server_ip = None
        self._original_dns_backed_up = False
        
        # Path to tun2socks binary
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self.tun2socks_path = os.path.join(base_dir, "src", "resources", "tun2socks", "tun2socks")
        
        # Cleanup script path
        self.cleanup_script = os.path.join(base_dir, "src", "resources", "tun2socks", "cleanup.sh")
        
        # Register signal handlers for crash safety
        self._register_signal_handlers()
    
    @property
    def is_active(self) -> bool:
        return self._active
    
    def check_tun2socks_exists(self) -> bool:
        """Check if tun2socks binary exists"""
        return os.path.exists(self.tun2socks_path) and os.access(self.tun2socks_path, os.X_OK)
    
    def download_tun2socks(self) -> bool:
        """Download tun2socks binary from GitHub releases"""
        try:
            machine = platform.machine().lower()
            
            if machine in ["x86_64", "amd64"]:
                arch = "amd64"
            elif machine in ["aarch64", "arm64"]:
                arch = "arm64"
            elif machine.startswith("arm"):
                arch = "armv7"
            else:
                arch = "amd64"
            
            url = (
                f"https://github.com/xjasonlyu/tun2socks/releases/download/"
                f"v{self.TUN2SOCKS_VERSION}/tun2socks-linux-{arch}.zip"
            )
            
            # Create directory
            tun2socks_dir = os.path.dirname(self.tun2socks_path)
            os.makedirs(tun2socks_dir, exist_ok=True)
            
            zip_path = os.path.join(tun2socks_dir, "tun2socks.zip")
            
            # Download with progress
            def report_progress(block_num, block_size, total_size):
                if total_size > 0:
                    progress = int((block_num * block_size / total_size) * 100)
                    self.download_progress.emit(min(progress, 100))
            
            self.status_changed.emit("Downloading tun2socks...")
            urllib.request.urlretrieve(url, zip_path, report_progress)
            
            # Extract
            self.status_changed.emit("Extracting tun2socks...")
            with zipfile.ZipFile(zip_path, 'r') as zf:
                zf.extractall(tun2socks_dir)
            
            # The extracted binary name may differ, find and rename it
            extracted_binary = os.path.join(tun2socks_dir, f"tun2socks-linux-{arch}")
            if os.path.exists(extracted_binary) and not os.path.exists(self.tun2socks_path):
                os.rename(extracted_binary, self.tun2socks_path)
            
            # Make executable
            if os.path.exists(self.tun2socks_path):
                os.chmod(self.tun2socks_path, 
                        os.stat(self.tun2socks_path).st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
            
            # Clean up zip
            if os.path.exists(zip_path):
                os.remove(zip_path)
            
            # Create cleanup script
            self._create_cleanup_script()
            
            self.download_progress.emit(100)
            self.status_changed.emit("tun2socks downloaded successfully")
            return True
            
        except Exception as e:
            self.error_occurred.emit(f"Failed to download tun2socks: {e}")
            return False
    
    def _get_default_gateway(self) -> Tuple[Optional[str], Optional[str]]:
        """Get the current default gateway IP and interface name"""
        try:
            result = subprocess.run(
                ["ip", "route", "show", "default"],
                capture_output=True, text=True
            )
            # Output: "default via 192.168.1.1 dev wlan0 proto ..."
            parts = result.stdout.strip().split()
            if len(parts) >= 5 and parts[0] == "default" and parts[1] == "via":
                gateway_ip = parts[2]
                # Find 'dev' keyword and get the next word
                if "dev" in parts:
                    dev_index = parts.index("dev")
                    interface = parts[dev_index + 1]
                else:
                    interface = None
                return gateway_ip, interface
        except Exception as e:
            self.error_occurred.emit(f"Failed to detect default gateway: {e}")
        
        return None, None
    
    def _run_privileged(self, commands: list, description: str = "") -> Tuple[bool, str]:
        """Run a list of commands with root privileges via pkexec
        
        Each command is a list of strings. They are combined into a single 
        bash script and executed via pkexec.
        """
        try:
            # Build a bash script from all commands
            script_lines = ["#!/bin/bash", "set -e"]
            for cmd in commands:
                # Escape each argument properly
                escaped = " ".join(f"'{arg}'" for arg in cmd)
                script_lines.append(escaped)
            
            script = "\n".join(script_lines)
            
            result = subprocess.run(
                ["pkexec", "bash", "-c", script],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode == 0:
                return True, result.stdout
            else:
                error_msg = result.stderr or f"Command failed with code {result.returncode}"
                return False, error_msg
                
        except subprocess.TimeoutExpired:
            return False, f"Operation timed out: {description}"
        except FileNotFoundError:
            return False, "pkexec not found. Please install polkit."
        except Exception as e:
            return False, str(e)
    
    def enable_tun(self, remote_server_ip: str) -> Tuple[bool, str]:
        """Create TUN device and configure routing
        
        Args:
            remote_server_ip: The IP of the remote VPN server (to exclude from TUN routing)
        """
        if self._active:
            return True, "TUN already active"
        
        # Save remote server IP for cleanup
        self._remote_server_ip = remote_server_ip
        
        # Get current default gateway before we modify routing
        gateway, interface = self._get_default_gateway()
        if not gateway or not interface:
            return False, "Could not detect default gateway. Check your network connection."
        
        self._original_gateway = gateway
        self._original_interface = interface
        
        self.status_changed.emit(f"Setting up TUN device (gateway: {gateway}, interface: {interface})...")
        
        # Backup DNS before modifying
        self._backup_dns()
        
        # All privileged commands to set up TUN
        commands = [
            # ---- IPv6: Disable to prevent leaks ----
            # Google/YouTube prefer IPv6 which bypasses our IPv4-only TUN
            ["sysctl", "-w", "net.ipv6.conf.all.disable_ipv6=1"],
            ["sysctl", "-w", "net.ipv6.conf.default.disable_ipv6=1"],
            
            # ---- Create TUN device ----
            ["ip", "tuntap", "add", "dev", self.TUN_DEVICE, "mode", "tun"],
            # Set IP address on TUN device
            ["ip", "addr", "add", f"{self.TUN_IP}/{self.TUN_NETMASK}", "dev", self.TUN_DEVICE],
            # Set MTU to 1400 to account for encapsulation overhead
            # Without this, large packets (Google, YouTube) get fragmented/dropped
            ["ip", "link", "set", self.TUN_DEVICE, "mtu", "1400"],
            # Bring TUN device up
            ["ip", "link", "set", self.TUN_DEVICE, "up"],
            
            # ---- Routing ----
            # Route remote VPN server IP through the real gateway (prevent routing loop)
            ["ip", "route", "add", f"{remote_server_ip}/32", "via", gateway, "dev", interface],
            # Delete current default route
            ["ip", "route", "del", "default"],
            # Add new default route through TUN device — ALL traffic goes here
            ["ip", "route", "add", "default", "via", self.TUN_GATEWAY, "dev", self.TUN_DEVICE],
            # NOTE: No fallback route! Traffic must go through TUN or not at all.
            # A fallback route causes traffic to silently bypass the tunnel.
        ]
        
        success, output = self._run_privileged(commands, "TUN setup")
        
        if success:
            self._active = True
            # Write cleanup info to file for crash recovery
            self._write_cleanup_state()
            self.status_changed.emit("TUN device active — all traffic routed through VPN")
            return True, "TUN mode enabled"
        else:
            # Try to clean up any partial state
            self._emergency_cleanup()
            return False, f"Failed to set up TUN: {output}"
    
    def start_tun2socks(self) -> bool:
        """Start the tun2socks process"""
        if not self.check_tun2socks_exists():
            self.error_occurred.emit("tun2socks not found. Please download it first.")
            return False
        
        try:
            # Raise file descriptor limit for this process tree
            # Heavy sites (speedtest) create hundreds of connections
            import resource
            try:
                soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
                resource.setrlimit(resource.RLIMIT_NOFILE, (min(65536, hard), hard))
            except Exception:
                pass
            
            self.tun2socks_process = subprocess.Popen(
                [
                    self.tun2socks_path,
                    "-device", self.TUN_DEVICE,
                    "-proxy", f"socks5://127.0.0.1:{self.socks_port}",
                    # Shorter UDP timeout — prevents connection table exhaustion
                    # Default is 5min; heavy sites pile up hundreds of stale UDP entries
                    "-udp-timeout", "30s",
                    # Smaller per-connection TCP buffers to handle more connections
                    "-tcp-sndbuf", "16384",
                    "-tcp-rcvbuf", "16384",
                    "-loglevel", "warning"
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1
            )
            
            # Wait briefly to check if it started OK
            time.sleep(0.5)
            
            if self.tun2socks_process.poll() is not None:
                # Process died immediately
                output = self.tun2socks_process.stdout.read() if self.tun2socks_process.stdout else ""
                self.error_occurred.emit(f"tun2socks failed to start: {output}")
                return False
            
            # Start log reading thread
            log_thread = threading.Thread(target=self._read_tun2socks_logs, daemon=True)
            log_thread.start()
            
            # Start health monitor thread
            health_thread = threading.Thread(target=self._monitor_tun2socks, daemon=True)
            health_thread.start()
            
            self.status_changed.emit("tun2socks running")
            return True
            
        except Exception as e:
            self.error_occurred.emit(f"Failed to start tun2socks: {e}")
            return False
    
    def _read_tun2socks_logs(self):
        """Read and forward tun2socks log output"""
        try:
            while self.tun2socks_process and self.tun2socks_process.stdout:
                line = self.tun2socks_process.stdout.readline()
                if line:
                    self.status_changed.emit(f"[tun2socks] {line.strip()}")
                elif self.tun2socks_process.poll() is not None:
                    break
        except Exception:
            pass
    
    def _monitor_tun2socks(self):
        """Monitor tun2socks process health — alert if it dies unexpectedly"""
        try:
            while self._active and self.tun2socks_process:
                if self.tun2socks_process.poll() is not None:
                    # Process died
                    exit_code = self.tun2socks_process.returncode
                    self.error_occurred.emit(
                        f"tun2socks crashed (exit code: {exit_code}). "
                        f"Your tunnel is broken — please disconnect and reconnect."
                    )
                    break
                time.sleep(3)  # Check every 3 seconds
        except Exception:
            pass
    
    def disable_tun(self) -> Tuple[bool, str]:
        """Stop tun2socks, remove TUN device, restore routing"""
        if not self._active and self.tun2socks_process is None:
            return True, "TUN not active"
        
        self.status_changed.emit("Disabling TUN mode...")
        
        # Stop tun2socks first
        self._stop_tun2socks()
        
        # Restore routing and remove TUN device
        commands = []
        
        if self._original_gateway and self._original_interface:
            commands.extend([
                # Remove TUN default route (ignore errors with || true)
                ["bash", "-c", f"ip route del default via {self.TUN_GATEWAY} dev {self.TUN_DEVICE} 2>/dev/null || true"],
            ])
            
            if self._remote_server_ip:
                commands.append(
                    ["bash", "-c", f"ip route del {self._remote_server_ip}/32 via {self._original_gateway} 2>/dev/null || true"]
                )
            
            # Restore original default route
            commands.append(
                ["ip", "route", "add", "default", "via", self._original_gateway, "dev", self._original_interface]
            )
        
        # Remove TUN device
        commands.extend([
            ["bash", "-c", f"ip link set {self.TUN_DEVICE} down 2>/dev/null || true"],
            ["bash", "-c", f"ip tuntap del dev {self.TUN_DEVICE} mode tun 2>/dev/null || true"],
        ])
        
        # Re-enable IPv6
        commands.extend([
            ["sysctl", "-w", "net.ipv6.conf.all.disable_ipv6=0"],
            ["sysctl", "-w", "net.ipv6.conf.default.disable_ipv6=0"],
        ])
        
        success, output = self._run_privileged(commands, "TUN teardown")
        
        self._active = False
        self._original_dns_backed_up = False
        self._remove_cleanup_state()
        
        if success:
            self.status_changed.emit("TUN mode disabled — routing restored")
            return True, "TUN mode disabled"
        else:
            return False, f"TUN cleanup had issues: {output}"
    
    def _stop_tun2socks(self):
        """Stop the tun2socks process"""
        if self.tun2socks_process:
            try:
                self.tun2socks_process.terminate()
                try:
                    self.tun2socks_process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.tun2socks_process.kill()
                    self.tun2socks_process.wait()
            except Exception:
                pass
            finally:
                self.tun2socks_process = None
    
    def _backup_dns(self):
        """Record that we need to restore DNS on cleanup"""
        self._original_dns_backed_up = True
    
    def _write_cleanup_state(self):
        """Write state info for crash recovery"""
        try:
            config_dir = os.path.expanduser("~/.config/voidtunnel")
            os.makedirs(config_dir, exist_ok=True)
            
            state_path = os.path.join(config_dir, "tun_state.json")
            import json
            state = {
                "active": True,
                "original_gateway": self._original_gateway,
                "original_interface": self._original_interface,
                "remote_server_ip": self._remote_server_ip,
                "tun_device": self.TUN_DEVICE,
                "tun_gateway": self.TUN_GATEWAY,
            }
            with open(state_path, 'w') as f:
                json.dump(state, f, indent=2)
        except Exception:
            pass
    
    def _remove_cleanup_state(self):
        """Remove the crash recovery state file"""
        try:
            state_path = os.path.expanduser("~/.config/voidtunnel/tun_state.json")
            if os.path.exists(state_path):
                os.remove(state_path)
        except Exception:
            pass
    
    def _create_cleanup_script(self):
        """Create a standalone cleanup script for manual crash recovery"""
        try:
            script_content = """#!/bin/bash
# VoidTunnel TUN Cleanup Script
# Run this manually if VoidTunnel crashed and your internet is broken
# Usage: sudo bash cleanup.sh

STATE_FILE="$HOME/.config/voidtunnel/tun_state.json"

echo "VoidTunnel TUN Cleanup"
echo "======================"

# Try to read saved state
if [ -f "$STATE_FILE" ]; then
    GATEWAY=$(python3 -c "import json; print(json.load(open('$STATE_FILE'))['original_gateway'])" 2>/dev/null)
    IFACE=$(python3 -c "import json; print(json.load(open('$STATE_FILE'))['original_interface'])" 2>/dev/null)
    SERVER=$(python3 -c "import json; print(json.load(open('$STATE_FILE'))['remote_server_ip'])" 2>/dev/null)
    echo "Found saved state: gateway=$GATEWAY, interface=$IFACE"
else
    echo "No saved state found. Will try generic cleanup."
fi

# Kill tun2socks if running
pkill -f tun2socks 2>/dev/null && echo "Killed tun2socks" || echo "tun2socks not running"

# Remove TUN routes
ip route del default via 10.0.0.2 dev tun0 2>/dev/null
ip route del default via "${GATEWAY:-0.0.0.0}" metric 100 2>/dev/null

# Remove server-specific route
if [ -n "$SERVER" ]; then
    ip route del "$SERVER/32" via "$GATEWAY" 2>/dev/null
fi

# Remove TUN device
ip link set tun0 down 2>/dev/null
ip tuntap del dev tun0 mode tun 2>/dev/null && echo "Removed tun0" || echo "tun0 not found"

# Restore default route
if [ -n "$GATEWAY" ] && [ -n "$IFACE" ]; then
    ip route add default via "$GATEWAY" dev "$IFACE" 2>/dev/null && echo "Restored default route" || echo "Default route already exists"
fi

# Clean up state file
rm -f "$STATE_FILE" 2>/dev/null

echo ""
echo "Cleanup complete. Try: ping 8.8.8.8"
"""
            tun2socks_dir = os.path.dirname(self.tun2socks_path)
            os.makedirs(tun2socks_dir, exist_ok=True)
            
            with open(self.cleanup_script, 'w') as f:
                f.write(script_content)
            os.chmod(self.cleanup_script, 0o755)
        except Exception:
            pass
    
    def _emergency_cleanup(self):
        """Best-effort cleanup when setup fails partway"""
        try:
            self._stop_tun2socks()
            
            cleanup_commands = [
                ["bash", "-c", f"ip route del default via {self.TUN_GATEWAY} dev {self.TUN_DEVICE} 2>/dev/null || true"],
            ]
            
            if self._original_gateway and self._original_interface:
                if self._remote_server_ip:
                    cleanup_commands.append(
                        ["bash", "-c", f"ip route del {self._remote_server_ip}/32 2>/dev/null || true"]
                    )
                # Try to restore default route
                cleanup_commands.append(
                    ["bash", "-c", f"ip route add default via {self._original_gateway} dev {self._original_interface} 2>/dev/null || true"]
                )
            
            cleanup_commands.extend([
                ["bash", "-c", f"ip link set {self.TUN_DEVICE} down 2>/dev/null || true"],
                ["bash", "-c", f"ip tuntap del dev {self.TUN_DEVICE} mode tun 2>/dev/null || true"],
                # Re-enable IPv6
                ["sysctl", "-w", "net.ipv6.conf.all.disable_ipv6=0"],
                ["sysctl", "-w", "net.ipv6.conf.default.disable_ipv6=0"],
            ])
            
            self._run_privileged(cleanup_commands, "emergency cleanup")
        except Exception:
            pass
        
        self._active = False
        self._original_dns_backed_up = False
        self._remove_cleanup_state()
    
    def recover_from_crash(self) -> Tuple[bool, str]:
        """Check for and recover from a previous crash where TUN was left active"""
        try:
            import json
            state_path = os.path.expanduser("~/.config/voidtunnel/tun_state.json")
            
            if not os.path.exists(state_path):
                return False, "No crash recovery needed"
            
            with open(state_path, 'r') as f:
                state = json.load(f)
            
            if not state.get("active"):
                return False, "No active TUN state"
            
            # Restore from saved state
            self._original_gateway = state.get("original_gateway")
            self._original_interface = state.get("original_interface")
            self._remote_server_ip = state.get("remote_server_ip")
            self._active = True
            
            # Run cleanup
            success, msg = self.disable_tun()
            return True, f"Recovered from previous crash: {msg}"
            
        except Exception as e:
            # If recovery fails, just clean up the state file
            self._remove_cleanup_state()
            return False, f"Recovery failed: {e}"
    
    def _register_signal_handlers(self):
        """Register signal handlers for graceful cleanup on crash/kill"""
        try:
            original_sigterm = signal.getsignal(signal.SIGTERM)
            original_sigint = signal.getsignal(signal.SIGINT)
            
            def cleanup_handler(signum, frame):
                if self._active:
                    try:
                        self._stop_tun2socks()
                        # We can't use pkexec in signal handler, so just write state
                        self._write_cleanup_state()
                    except Exception:
                        pass
                
                # Call original handler
                if signum == signal.SIGTERM and callable(original_sigterm):
                    original_sigterm(signum, frame)
                elif signum == signal.SIGINT and callable(original_sigint):
                    original_sigint(signum, frame)
                else:
                    sys.exit(1)
            
            signal.signal(signal.SIGTERM, cleanup_handler)
            signal.signal(signal.SIGINT, cleanup_handler)
        except Exception:
            # Signal handlers may fail in non-main threads
            pass
    
    def update_socks_port(self, port: int):
        """Update the SOCKS port"""
        self.socks_port = port
