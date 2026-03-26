"""
Connect Widget - Main connection control interface
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QGridLayout, QProgressBar
)
from PyQt6.QtCore import Qt, pyqtSignal, pyqtSlot, QTimer
from PyQt6.QtGui import QFont

from src.core.xray_controller import XrayController
from src.core.profile_manager import ProfileManager
from src.core.config_manager import ConfigManager
from src.core.proxy_manager import ProxyManager
from src.core.singbox_manager import SingBoxManager
from src.core.protocol_parser import ServerProfile
from src.utils.network import tcp_ping, get_public_ip
from src.utils.helpers import get_protocol_icon, format_bytes


class ConnectWidget(QWidget):
    """Widget for connection control and status display"""
    
    connection_changed = pyqtSignal(bool)
    
    def __init__(self, profile_manager: ProfileManager,
                 xray_controller: XrayController,
                 config_manager: ConfigManager,
                 proxy_manager: ProxyManager,
                 singbox_manager: SingBoxManager,
                 settings: dict):
        super().__init__()
        
        self.profile_manager = profile_manager
        self.xray_controller = xray_controller
        self.config_manager = config_manager
        self.proxy_manager = proxy_manager
        self.singbox_manager = singbox_manager
        self.settings = settings
        
        self.current_profile: ServerProfile = None
        self.is_connected = False
        
        # Stats tracking
        self.upload_bytes = 0
        self.download_bytes = 0
        self.last_upload = 0
        self.last_download = 0
        
        # Session totals (bytes transferred during this connection)
        self.session_start_upload = 0
        self.session_start_download = 0
        self.total_session_upload = 0
        self.total_session_download = 0
        
        # Stats timer (updates every 1 second)
        self.stats_timer = QTimer()
        self.stats_timer.timeout.connect(self._update_traffic_stats)
        
        self._setup_ui()
    
    def _setup_ui(self):
        """Setup the UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 24, 32, 24)
        layout.setSpacing(24)
        
        # Connection card
        card = QFrame()
        card.setObjectName("card")
        card_layout = QVBoxLayout(card)
        card_layout.setSpacing(20)
        
        # Server info section
        server_section = QHBoxLayout()
        
        # Left side - server details
        server_info = QVBoxLayout()
        server_info.setSpacing(8)
        
        self.server_name_label = QLabel("No Server Selected")
        self.server_name_label.setFont(QFont("Inter", 18, QFont.Weight.Bold))
        server_info.addWidget(self.server_name_label)
        
        self.server_details_label = QLabel("Select a server from the Servers tab")
        self.server_details_label.setObjectName("subtitleLabel")
        server_info.addWidget(self.server_details_label)
        
        server_section.addLayout(server_info)
        server_section.addStretch()
        
        # Right side - protocol badge
        self.protocol_badge = QLabel("")
        self.protocol_badge.setStyleSheet("""
            QLabel {
                background-color: #21262d;
                border-radius: 12px;
                padding: 6px 12px;
                font-size: 12px;
                font-weight: 600;
            }
        """)
        self.protocol_badge.hide()
        server_section.addWidget(self.protocol_badge)
        
        card_layout.addLayout(server_section)
        
        # Connection button
        self.connect_btn = QPushButton("Connect")
        self.connect_btn.setObjectName("connectButton")
        self.connect_btn.setProperty("connected", False)
        self.connect_btn.setMinimumHeight(50)
        self.connect_btn.setFont(QFont("Inter", 14, QFont.Weight.Bold))
        self.connect_btn.clicked.connect(self._toggle_connection)
        card_layout.addWidget(self.connect_btn)
        
        layout.addWidget(card)
        
        # Stats grid - Row 1: Speed stats
        stats_grid = QGridLayout()
        stats_grid.setSpacing(16)
        
        # Latency
        self.latency_card = self._create_stat_card("Latency", "--", "ms")
        stats_grid.addWidget(self.latency_card, 0, 0)
        
        # Upload Speed
        self.upload_card = self._create_stat_card("Upload", "0", "KB/s")
        stats_grid.addWidget(self.upload_card, 0, 1)
        
        # Download Speed
        self.download_card = self._create_stat_card("Download", "0", "KB/s")
        stats_grid.addWidget(self.download_card, 0, 2)
        
        # Row 2: Total data stats
        # Total Upload
        self.total_upload_card = self._create_stat_card("Total ↑", "0", "MB")
        stats_grid.addWidget(self.total_upload_card, 1, 0)
        
        # Total Download
        self.total_download_card = self._create_stat_card("Total ↓", "0", "MB")
        stats_grid.addWidget(self.total_download_card, 1, 1)
        
        # Session time placeholder (can show connection duration)
        self.session_card = self._create_stat_card("Session", "0", "MB")
        stats_grid.addWidget(self.session_card, 1, 2)
        
        layout.addLayout(stats_grid)
        
        # IP Info card
        ip_card = QFrame()
        ip_card.setObjectName("card")
        ip_layout = QHBoxLayout(ip_card)
        
        # Real IP
        real_ip_section = QVBoxLayout()
        real_ip_section.addWidget(QLabel("Real IP"))
        self.real_ip_label = QLabel("---.---.---.---")
        self.real_ip_label.setFont(QFont("Inter", 14, QFont.Weight.Medium))
        real_ip_section.addWidget(self.real_ip_label)
        ip_layout.addLayout(real_ip_section)
        
        # Divider
        divider = QFrame()
        divider.setFixedWidth(1)
        divider.setStyleSheet("background-color: #21262d;")
        ip_layout.addWidget(divider)
        
        # Proxy IP
        proxy_ip_section = QVBoxLayout()
        proxy_ip_section.addWidget(QLabel("Proxy IP"))
        self.proxy_ip_label = QLabel("---.---.---.---")
        self.proxy_ip_label.setFont(QFont("Inter", 14, QFont.Weight.Medium))
        self.proxy_ip_label.setStyleSheet("color: #3fb950;")
        proxy_ip_section.addWidget(self.proxy_ip_label)
        ip_layout.addLayout(proxy_ip_section)
        
        # Refresh button
        refresh_btn = QPushButton("🔄")
        refresh_btn.setObjectName("iconButton")
        refresh_btn.setToolTip("Refresh IP addresses")
        refresh_btn.clicked.connect(self._refresh_ips)
        ip_layout.addWidget(refresh_btn)
        
        # Eye toggle button for IP privacy
        self.ip_visible = False
        self.real_ip_actual = ""
        self.proxy_ip_actual = ""
        
        self.eye_btn = QPushButton("👁️")
        self.eye_btn.setObjectName("iconButton")
        self.eye_btn.setToolTip("Show/Hide IP addresses")
        self.eye_btn.clicked.connect(self._toggle_ip_visibility)
        ip_layout.addWidget(self.eye_btn)
        
        layout.addWidget(ip_card)
        
        layout.addStretch()
        
        # Load active profile if any
        active = self.profile_manager.get_active()
        if active:
            self.on_profile_selected(active)
    
    def _create_stat_card(self, title: str, value: str, unit: str) -> QFrame:
        """Create a statistics card"""
        card = QFrame()
        card.setObjectName("card")
        card.setMinimumHeight(100)
        
        layout = QVBoxLayout(card)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        title_label = QLabel(title)
        title_label.setObjectName("subtitleLabel")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title_label)
        
        value_layout = QHBoxLayout()
        value_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        value_label = QLabel(value)
        value_label.setFont(QFont("Inter", 24, QFont.Weight.Bold))
        value_label.setObjectName(f"{title.lower()}Value")
        value_layout.addWidget(value_label)
        
        unit_label = QLabel(unit)
        unit_label.setObjectName("subtitleLabel")
        value_layout.addWidget(unit_label)
        
        layout.addLayout(value_layout)
        
        return card
    
    @pyqtSlot(object)
    def on_profile_selected(self, profile: ServerProfile):
        """Handle profile selection"""
        self.current_profile = profile
        self.profile_manager.set_active(profile.id)
        
        self.server_name_label.setText(profile.name)
        self.server_details_label.setText(f"{profile.address}:{profile.port}")
        
        icon = get_protocol_icon(profile.protocol)
        self.protocol_badge.setText(f"{icon} {profile.protocol.upper()}")
        self.protocol_badge.show()
        
        # Update latency
        if profile.latency >= 0:
            self._update_latency(profile.latency)
    
    def _toggle_connection(self):
        """Toggle VPN connection"""
        if self.is_connected:
            self.disconnect()
        else:
            self.connect()
    
    def connect(self):
        """Connect to VPN"""
        if not self.current_profile:
            return
        
        connection_mode = self.settings.get("connection_mode", "proxy")
        
        if connection_mode == "tun":
            # TUN Mode: use sing-box (single process, native TUN)
            self._connect_tun_mode()
        else:
            # Proxy Mode: use Xray + system proxy (original behavior)
            self._connect_proxy_mode()
    
    def _connect_proxy_mode(self):
        """Connect using Xray + system proxy"""
        # Generate config
        config = self.config_manager.generate_config(
            self.current_profile,
            local_port=self.settings.get("socks_port", 10808),
            http_port=self.settings.get("http_port", 10809),
            dns_servers=self.settings.get("dns_servers", ["8.8.8.8", "8.8.4.4"])
        )
        
        # Save config
        config_path = self.config_manager.save_config(config)
        
        # Start Xray
        if self.xray_controller.start(config_path):
            self.is_connected = True
            self._update_connection_ui()
            
            if self.settings.get("enable_system_proxy", True):
                self.proxy_manager.enable_system_proxy()
            
            self.connection_changed.emit(True)
            self._start_stats_tracking()
            QTimer.singleShot(2000, lambda: self._refresh_proxy_ip())
    
    def _connect_tun_mode(self):
        """Connect using sing-box with native TUN"""
        from PyQt6.QtWidgets import QMessageBox
        
        # Check if sing-box exists, prompt download if not
        if not self.singbox_manager.check_singbox_exists():
            reply = QMessageBox.question(
                self,
                "sing-box Not Found",
                "TUN Mode requires sing-box but it's not installed.\n\n"
                "Would you like to download it now? (~15MB)",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                if not self.singbox_manager.download_singbox():
                    QMessageBox.warning(self, "Error", "Failed to download sing-box.")
                    return
            else:
                return
        
        # Start sing-box with current profile (handles TUN, routing, DNS — all in one)
        dns_servers = self.settings.get("dns_servers", ["8.8.8.8", "8.8.4.4"])
        if self.singbox_manager.start(self.current_profile, dns_servers):
            self.is_connected = True
            self._update_connection_ui()
            self.connection_changed.emit(True)
            self._start_stats_tracking()
            QTimer.singleShot(2000, lambda: self._refresh_proxy_ip())
        else:
            QMessageBox.warning(
                self, "TUN Error",
                "Failed to start sing-box TUN mode.\n"
                "Check the logs for details."
            )
    
    def _start_stats_tracking(self):
        """Start upload/download stats tracking"""
        import psutil
        net_io = psutil.net_io_counters()
        self.session_start_upload = net_io.bytes_sent
        self.session_start_download = net_io.bytes_recv
        self.last_upload = 0
        self.last_download = 0
        self.stats_timer.start(1000)
    
    def disconnect(self):
        """Disconnect from VPN"""
        # Stop stats timer
        self.stats_timer.stop()
        
        # Reset speed displays
        self._update_speed_display("upload", 0)
        self._update_speed_display("download", 0)
        
        # Stop sing-box if active, otherwise stop Xray + proxy
        if self.singbox_manager.is_active:
            self.singbox_manager.stop()
        else:
            self.proxy_manager.disable_system_proxy()
            self.xray_controller.stop()
        
        self.is_connected = False
        self._update_connection_ui()
        self.connection_changed.emit(False)
        
        self.proxy_ip_label.setText("---.---.---.---")
    
    def _update_connection_ui(self):
        """Update UI based on connection state"""
        if self.is_connected:
            self.connect_btn.setText("Disconnect")
            self.connect_btn.setProperty("connected", True)
        else:
            self.connect_btn.setText("Connect")
            self.connect_btn.setProperty("connected", False)
        
        self.connect_btn.style().unpolish(self.connect_btn)
        self.connect_btn.style().polish(self.connect_btn)
    
    def _update_latency(self, latency: int):
        """Update latency display"""
        value_label = self.latency_card.findChild(QLabel, "latencyValue")
        if value_label:
            if latency >= 0:
                value_label.setText(str(latency))
                if latency < 100:
                    value_label.setStyleSheet("color: #3fb950;")
                elif latency < 300:
                    value_label.setStyleSheet("color: #d29922;")
                else:
                    value_label.setStyleSheet("color: #f85149;")
            else:
                value_label.setText("--")
                value_label.setStyleSheet("")
    
    def _refresh_ips(self):
        """Refresh IP addresses"""
        self._refresh_real_ip()
        if self.is_connected:
            self._refresh_proxy_ip()
    
    def _refresh_real_ip(self):
        """Refresh real IP"""
        import threading
        def get_ip():
            ip = get_public_ip(use_proxy=False)
            if ip:
                self.real_ip_actual = ip
                self._update_ip_display()
        
        threading.Thread(target=get_ip, daemon=True).start()
    
    def _refresh_proxy_ip(self):
        """Refresh proxy IP"""
        import threading
        def get_ip():
            ip = get_public_ip(
                use_proxy=True,
                proxy_host="127.0.0.1",
                proxy_port=self.settings.get("http_port", 10809)
            )
            if ip:
                self.proxy_ip_actual = ip
                self._update_ip_display()
        
        threading.Thread(target=get_ip, daemon=True).start()
    
    def _toggle_ip_visibility(self):
        """Toggle IP address visibility"""
        self.ip_visible = not self.ip_visible
        self.eye_btn.setText("🙈" if self.ip_visible else "👁️")
        self.eye_btn.setToolTip("Hide IP addresses" if self.ip_visible else "Show IP addresses")
        self._update_ip_display()
    
    def _update_ip_display(self):
        """Update IP labels based on visibility setting"""
        if self.ip_visible:
            # Show actual IPs
            if self.real_ip_actual:
                self.real_ip_label.setText(self.real_ip_actual)
            if self.proxy_ip_actual:
                self.proxy_ip_label.setText(self.proxy_ip_actual)
        else:
            # Show masked IPs
            if self.real_ip_actual:
                self.real_ip_label.setText(self._mask_ip(self.real_ip_actual))
            else:
                self.real_ip_label.setText("xxx.xxx.xxx.xxx")
            if self.proxy_ip_actual:
                self.proxy_ip_label.setText(self._mask_ip(self.proxy_ip_actual))
            else:
                self.proxy_ip_label.setText("xxx.xxx.xxx.xxx")
    
    def _mask_ip(self, ip: str) -> str:
        """Mask an IP address for privacy"""
        parts = ip.split('.')
        if len(parts) == 4:
            return f"xxx.xxx.{parts[2]}.xxx"
        return "xxx.xxx.xxx.xxx"
    
    def _update_traffic_stats(self):
        """Update traffic statistics by reading network stats"""
        try:
            import psutil
            
            # Get network stats for all interfaces
            net_io = psutil.net_io_counters()
            
            current_upload = net_io.bytes_sent
            current_download = net_io.bytes_recv
            
            # Calculate speed (bytes per second)
            if self.last_upload > 0:
                upload_speed = current_upload - self.last_upload
                download_speed = current_download - self.last_download
                
                # Convert to KB/s
                upload_kbs = upload_speed / 1024
                download_kbs = download_speed / 1024
                
                self._update_speed_display("upload", upload_kbs)
                self._update_speed_display("download", download_kbs)
            
            # Calculate session totals
            if self.session_start_upload > 0:
                self.total_session_upload = current_upload - self.session_start_upload
                self.total_session_download = current_download - self.session_start_download
                
                # Update total displays (in MB)
                upload_mb = self.total_session_upload / (1024 * 1024)
                download_mb = self.total_session_download / (1024 * 1024)
                session_total_mb = upload_mb + download_mb
                
                self._update_total_display("total_upload", upload_mb)
                self._update_total_display("total_download", download_mb)
                self._update_total_display("session", session_total_mb)
            
            self.last_upload = current_upload
            self.last_download = current_download
            
        except Exception as e:
            print(f"Stats error: {e}")
    
    def _update_speed_display(self, stat_type: str, speed_kbs: float):
        """Update speed display for upload or download"""
        card = self.upload_card if stat_type == "upload" else self.download_card
        value_label = card.findChild(QLabel, f"{stat_type}Value")
        
        if value_label:
            if speed_kbs >= 1024:
                # Show as MB/s
                value_label.setText(f"{speed_kbs/1024:.1f}")
                # Find and update unit label
                for child in card.findChildren(QLabel):
                    if child.objectName() == "subtitleLabel":
                        child.setText("MB/s")
            else:
                value_label.setText(f"{int(speed_kbs)}")
                for child in card.findChildren(QLabel):
                    if child.objectName() == "subtitleLabel":
                        child.setText("KB/s")
            
            # Color based on speed
            if speed_kbs > 500:
                value_label.setStyleSheet("color: #3fb950;")  # Green for fast
            elif speed_kbs > 100:
                value_label.setStyleSheet("color: #58a6ff;")  # Blue for medium
            else:
                value_label.setStyleSheet("")  # Default
    
    def _update_total_display(self, stat_type: str, total_mb: float):
        """Update total data display (MB or GB)"""
        if stat_type == "total_upload":
            card = self.total_upload_card
        elif stat_type == "total_download":
            card = self.total_download_card
        else:
            card = self.session_card
        
        # Find the value label (using Total ↑, Total ↓, or Session as name prefix)
        for child in card.findChildren(QLabel):
            font = child.font()
            if font.pointSize() >= 20 or font.weight() >= 600:  # Large bold label = value
                if total_mb >= 1024:
                    # Show as GB
                    child.setText(f"{total_mb/1024:.2f}")
                    child.setStyleSheet("color: #3fb950;")  # Green for GB
                elif total_mb >= 100:
                    child.setText(f"{total_mb:.1f}")
                    child.setStyleSheet("color: #58a6ff;")  # Blue
                else:
                    child.setText(f"{total_mb:.1f}")
                    child.setStyleSheet("")
            elif child.objectName() == "subtitleLabel":
                if total_mb >= 1024:
                    child.setText("GB")
                else:
                    child.setText("MB")
