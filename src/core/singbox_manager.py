"""
Sing-Box Manager — Native TUN mode using sing-box

Replaces the fragile tun2socks + Xray SOCKS5 chain.
sing-box handles TUN, routing, DNS, and proxy all in one process.

Flow: Apps → tun0 → sing-box → Remote VPN Server
      (single process, no SOCKS5 bottleneck)
"""

import os
import json
import subprocess
import threading
import time
import platform
import stat
import signal
import sys
import urllib.request
import tarfile
import shutil
from typing import Optional, Tuple, Dict, Any
from PyQt6.QtCore import QObject, pyqtSignal

from .protocol_parser import ServerProfile, Protocol


class SingBoxManager(QObject):
    """Manages sing-box binary for native TUN-based VPN"""

    # Signals
    status_changed = pyqtSignal(str)
    error_occurred = pyqtSignal(str)
    download_progress = pyqtSignal(int)

    SINGBOX_VERSION = "1.13.3"

    def __init__(self):
        super().__init__()

        self.singbox_process: Optional[subprocess.Popen] = None
        self._active = False

        # Paths
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self.singbox_dir = os.path.join(base_dir, "src", "resources", "singbox")
        self.singbox_path = os.path.join(self.singbox_dir, "sing-box")

        config_dir = os.path.expanduser("~/.config/voidtunnel")
        os.makedirs(config_dir, exist_ok=True)
        self.config_path = os.path.join(config_dir, "singbox_config.json")

    @property
    def is_active(self) -> bool:
        return self._active

    # ── Binary Management ─────────────────────────────────────────

    def check_singbox_exists(self) -> bool:
        """Check if sing-box binary exists and is executable"""
        return os.path.exists(self.singbox_path) and os.access(self.singbox_path, os.X_OK)

    def download_singbox(self) -> bool:
        """Download sing-box from GitHub releases"""
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
                f"https://github.com/SagerNet/sing-box/releases/download/"
                f"v{self.SINGBOX_VERSION}/sing-box-{self.SINGBOX_VERSION}-linux-{arch}.tar.gz"
            )

            os.makedirs(self.singbox_dir, exist_ok=True)
            tar_path = os.path.join(self.singbox_dir, "sing-box.tar.gz")

            def report_progress(block_num, block_size, total_size):
                if total_size > 0:
                    progress = int((block_num * block_size / total_size) * 100)
                    self.download_progress.emit(min(progress, 100))

            self.status_changed.emit("Downloading sing-box...")
            urllib.request.urlretrieve(url, tar_path, report_progress)

            # Extract
            self.status_changed.emit("Extracting sing-box...")
            with tarfile.open(tar_path, "r:gz") as tf:
                tf.extractall(self.singbox_dir)

            # Find the binary (it's in a subdirectory)
            extracted_dir = os.path.join(
                self.singbox_dir,
                f"sing-box-{self.SINGBOX_VERSION}-linux-{arch}"
            )
            extracted_binary = os.path.join(extracted_dir, "sing-box")

            if os.path.exists(extracted_binary):
                shutil.move(extracted_binary, self.singbox_path)
                # Clean up extracted directory
                shutil.rmtree(extracted_dir, ignore_errors=True)

            # Make executable
            if os.path.exists(self.singbox_path):
                os.chmod(
                    self.singbox_path,
                    os.stat(self.singbox_path).st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH
                )

            # Clean up tar
            if os.path.exists(tar_path):
                os.remove(tar_path)

            self.download_progress.emit(100)
            self.status_changed.emit("sing-box downloaded successfully")
            return True

        except Exception as e:
            self.error_occurred.emit(f"Failed to download sing-box: {e}")
            return False

    # ── Config Generation ─────────────────────────────────────────

    def generate_config(self, profile: ServerProfile,
                        dns_servers: list = None) -> Dict[str, Any]:
        """Generate sing-box config with native TUN inbound from a ServerProfile.
        
        Fully compatible with sing-box v1.13.3 — all deprecated features removed:
          v1.10: address[] instead of inet4_address
          v1.11: rule actions (sniff, hijack-dns) instead of special outbounds
          v1.12: new DNS server format (type+server instead of address)
          v1.12: domain_resolver instead of deprecated outbound DNS rules
        """

        if dns_servers is None:
            dns_servers = ["8.8.8.8", "8.8.4.4"]

        config = {
            "log": {
                "level": "info",
                "timestamp": True
            },
            "dns": {
                "servers": [
                    {
                        "tag": "remote-dns",
                        "type": "udp",
                        "server": dns_servers[0],
                        "server_port": 53,
                        "detour": "proxy"
                    },
                    {
                        "tag": "local-dns",
                        "type": "local"
                    }
                ]
            },
            "inbounds": [
                {
                    "type": "tun",
                    "tag": "tun-in",
                    "interface_name": "tun0",
                    "address": ["172.19.0.1/30"],
                    "mtu": 1400,
                    "auto_route": True,
                    "strict_route": True,
                    "stack": "system"
                }
            ],
            "outbounds": [
                self._generate_outbound(profile),
                {
                    "type": "direct",
                    "tag": "direct"
                }
            ],
            "route": {
                "rules": [
                    {
                        "action": "sniff"
                    },
                    {
                        "protocol": "dns",
                        "action": "hijack-dns"
                    },
                    {
                        "ip_is_private": True,
                        "outbound": "direct"
                    }
                ],
                "auto_detect_interface": True,
                "final": "proxy",
                "default_domain_resolver": {
                    "server": "local-dns",
                    "strategy": "ipv4_only"
                }
            }
        }

        return config

    def _generate_outbound(self, profile: ServerProfile) -> Dict[str, Any]:
        """Convert a ServerProfile to a sing-box outbound"""

        if profile.protocol == Protocol.VMESS.value:
            return self._vmess_outbound(profile)
        elif profile.protocol == Protocol.VLESS.value:
            return self._vless_outbound(profile)
        elif profile.protocol == Protocol.TROJAN.value:
            return self._trojan_outbound(profile)
        elif profile.protocol == Protocol.SHADOWSOCKS.value:
            return self._shadowsocks_outbound(profile)
        else:
            raise ValueError(f"Unsupported protocol: {profile.protocol}")

    def _vmess_outbound(self, profile: ServerProfile) -> Dict[str, Any]:
        outbound = {
            "type": "vmess",
            "tag": "proxy",
            "server": profile.address,
            "server_port": profile.port,
            "uuid": profile.uuid,
            "alter_id": profile.alter_id,
            "security": profile.security,
        }
        self._apply_tls(outbound, profile)
        self._apply_transport(outbound, profile)
        return outbound

    def _vless_outbound(self, profile: ServerProfile) -> Dict[str, Any]:
        outbound = {
            "type": "vless",
            "tag": "proxy",
            "server": profile.address,
            "server_port": profile.port,
            "uuid": profile.uuid,
        }
        self._apply_tls(outbound, profile)
        self._apply_transport(outbound, profile)
        return outbound

    def _trojan_outbound(self, profile: ServerProfile) -> Dict[str, Any]:
        outbound = {
            "type": "trojan",
            "tag": "proxy",
            "server": profile.address,
            "server_port": profile.port,
            "password": profile.password,
        }
        self._apply_tls(outbound, profile)
        self._apply_transport(outbound, profile)
        return outbound

    def _shadowsocks_outbound(self, profile: ServerProfile) -> Dict[str, Any]:
        outbound = {
            "type": "shadowsocks",
            "tag": "proxy",
            "server": profile.address,
            "server_port": profile.port,
            "password": profile.password,
            "method": profile.ss_method,
        }
        return outbound

    def _apply_tls(self, outbound: dict, profile: ServerProfile):
        """Apply TLS settings to an outbound"""
        if profile.tls:
            tls_config = {
                "enabled": True,
                "insecure": True,  # Allow insecure for SNI bypass
            }
            if profile.sni:
                tls_config["server_name"] = profile.sni
            if profile.fingerprint:
                tls_config["utls"] = {
                    "enabled": True,
                    "fingerprint": profile.fingerprint
                }
            if profile.alpn:
                tls_config["alpn"] = profile.alpn.split(",")
            outbound["tls"] = tls_config

    def _apply_transport(self, outbound: dict, profile: ServerProfile):
        """Apply transport settings to an outbound"""

        if profile.network == "ws":
            transport = {"type": "ws"}
            if profile.ws_path:
                transport["path"] = profile.ws_path
            if profile.ws_host or profile.custom_headers:
                headers = dict(profile.custom_headers) if profile.custom_headers else {}
                if profile.ws_host:
                    headers["Host"] = profile.ws_host
                transport["headers"] = headers
            outbound["transport"] = transport

        elif profile.network == "grpc":
            transport = {
                "type": "grpc",
            }
            if profile.grpc_service_name:
                transport["service_name"] = profile.grpc_service_name
            outbound["transport"] = transport

        elif profile.network in ("http", "h2"):
            transport = {"type": "http"}
            if profile.http_path:
                transport["path"] = profile.http_path
            if profile.http_host:
                transport["host"] = [profile.http_host]
            outbound["transport"] = transport
        # tcp = no transport config needed

    # ── Process Lifecycle ─────────────────────────────────────────

    def start(self, profile: ServerProfile,
              dns_servers: list = None) -> bool:
        """Generate config, save it, and start sing-box with TUN"""
        if self._active:
            self.stop()

        # Generate and save config
        config = self.generate_config(profile, dns_servers)
        with open(self.config_path, 'w') as f:
            json.dump(config, f, indent=2)

        self.status_changed.emit("Waiting for authentication...")

        # sing-box needs root to create TUN device
        # Run via pkexec for graphical sudo
        try:
            self.singbox_process = subprocess.Popen(
                [
                    "pkexec", self.singbox_path,
                    "run", "-c", self.config_path
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1
            )

            # Wait for sing-box to actually produce output (means pkexec auth is done)
            # pkexec shows a password dialog — we must wait for that to complete
            started = False
            for _ in range(120):  # Up to 60 seconds for user to type password
                if self.singbox_process.poll() is not None:
                    # Process exited already — auth cancelled or config error
                    output = ""
                    if self.singbox_process.stdout:
                        output = self.singbox_process.stdout.read()
                    exit_code = self.singbox_process.returncode
                    if exit_code == 126:
                        self.error_occurred.emit("Authentication cancelled.")
                    else:
                        self.error_occurred.emit(
                            f"sing-box failed (exit code {exit_code}):\n{output[:500]}"
                        )
                    self.singbox_process = None
                    return False
                
                # Check if process has started producing output
                # (means pkexec auth succeeded and sing-box is running)
                import select
                if self.singbox_process.stdout:
                    readable, _, _ = select.select(
                        [self.singbox_process.stdout], [], [], 0.5
                    )
                    if readable:
                        started = True
                        break
                else:
                    time.sleep(0.5)
            
            if not started:
                # Double-check: process might be running fine but with no output yet
                if self.singbox_process and self.singbox_process.poll() is None:
                    started = True
            
            if not started:
                self.error_occurred.emit("sing-box failed to start (timed out).")
                self._kill_process()
                return False

            # Wait a bit more and verify it's still alive
            time.sleep(1.0)
            if self.singbox_process.poll() is not None:
                output = ""
                if self.singbox_process.stdout:
                    output = self.singbox_process.stdout.read()
                exit_code = self.singbox_process.returncode
                self.error_occurred.emit(
                    f"sing-box exited immediately (code {exit_code}):\n{output[:500]}"
                )
                self.singbox_process = None
                return False

            self._active = True

            # Start log reader
            log_thread = threading.Thread(target=self._read_logs, daemon=True)
            log_thread.start()

            # Start health monitor
            health_thread = threading.Thread(target=self._monitor_health, daemon=True)
            health_thread.start()

            self.status_changed.emit("sing-box TUN active — all traffic routed through VPN")
            return True

        except FileNotFoundError:
            self.error_occurred.emit("pkexec not found. Please install polkit.")
            return False
        except Exception as e:
            self.error_occurred.emit(f"Failed to start sing-box: {e}")
            return False
    
    def _kill_process(self):
        """Kill the sing-box process"""
        if self.singbox_process:
            try:
                self.singbox_process.kill()
                self.singbox_process.wait(timeout=3)
            except Exception:
                pass
            self.singbox_process = None

    def stop(self):
        """Stop sing-box process"""
        self._active = False

        if self.singbox_process:
            try:
                # sing-box was started with pkexec, so we need to kill it via pkexec too
                # First try graceful shutdown
                self.singbox_process.terminate()
                try:
                    self.singbox_process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    # Force kill sing-box (may be running as root)
                    subprocess.run(
                        ["pkexec", "kill", "-9", str(self.singbox_process.pid)],
                        capture_output=True, timeout=10
                    )
                    try:
                        self.singbox_process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        pass
            except Exception:
                pass
            finally:
                self.singbox_process = None

        # Also kill any orphaned sing-box processes
        try:
            subprocess.run(
                ["pkexec", "bash", "-c", "pkill -f 'sing-box run' 2>/dev/null || true"],
                capture_output=True, timeout=10
            )
        except Exception:
            pass

        self.status_changed.emit("sing-box stopped — routing restored")

    def _read_logs(self):
        """Read sing-box log output and forward to UI"""
        try:
            while self._active and self.singbox_process and self.singbox_process.stdout:
                line = self.singbox_process.stdout.readline()
                if line:
                    stripped = line.strip()
                    if stripped:
                        self.status_changed.emit(f"[sing-box] {stripped}")
                elif self.singbox_process.poll() is not None:
                    break
        except Exception:
            pass

    def _monitor_health(self):
        """Monitor sing-box process health"""
        try:
            while self._active and self.singbox_process:
                if self.singbox_process.poll() is not None:
                    exit_code = self.singbox_process.returncode
                    self._active = False
                    self.error_occurred.emit(
                        f"sing-box stopped unexpectedly (exit code: {exit_code}). "
                        f"Please disconnect and reconnect."
                    )
                    break
                time.sleep(3)
        except Exception:
            pass
