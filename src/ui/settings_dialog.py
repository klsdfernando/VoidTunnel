"""
Settings Dialog - Application preferences
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFormLayout, QSpinBox, QCheckBox, QLineEdit, QComboBox,
    QGroupBox, QListWidget, QListWidgetItem, QTabWidget, QWidget
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont


class SettingsDialog(QDialog):
    """Application settings dialog"""
    
    def __init__(self, settings: dict, parent=None):
        super().__init__(parent)
        self.settings = settings.copy()
        self.setWindowTitle("Settings")
        self.setMinimumWidth(500)
        self.setMinimumHeight(400)
        self._setup_ui()
    
    def _setup_ui(self):
        """Setup the UI"""
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        
        # Tab widget
        tabs = QTabWidget()
        tabs.addTab(self._create_general_tab(), "General")
        tabs.addTab(self._create_proxy_tab(), "Proxy")
        tabs.addTab(self._create_dns_tab(), "DNS")
        tabs.addTab(self._create_about_tab(), "About")
        layout.addWidget(tabs)
        
        # Buttons
        buttons = QHBoxLayout()
        buttons.addStretch()
        
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        buttons.addWidget(cancel_btn)
        
        save_btn = QPushButton("Save")
        save_btn.setObjectName("primaryButton")
        save_btn.clicked.connect(self.accept)
        buttons.addWidget(save_btn)
        
        layout.addLayout(buttons)
    
    def _create_general_tab(self) -> QWidget:
        """Create general settings tab"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(16)
        
        # Startup group
        startup_group = QGroupBox("Startup")
        startup_layout = QVBoxLayout(startup_group)
        
        self.auto_connect_check = QCheckBox("Auto-connect on startup")
        self.auto_connect_check.setChecked(self.settings.get("auto_connect", False))
        startup_layout.addWidget(self.auto_connect_check)
        
        self.start_minimized_check = QCheckBox("Start minimized")
        self.start_minimized_check.setChecked(self.settings.get("start_minimized", False))
        startup_layout.addWidget(self.start_minimized_check)
        
        layout.addWidget(startup_group)
        
        # Behavior group
        behavior_group = QGroupBox("Behavior")
        behavior_layout = QVBoxLayout(behavior_group)
        
        self.minimize_to_tray_check = QCheckBox("Minimize to system tray")
        self.minimize_to_tray_check.setChecked(self.settings.get("minimize_to_tray", True))
        behavior_layout.addWidget(self.minimize_to_tray_check)
        
        self.enable_system_proxy_check = QCheckBox("Enable system proxy when connected")
        self.enable_system_proxy_check.setChecked(self.settings.get("enable_system_proxy", True))
        behavior_layout.addWidget(self.enable_system_proxy_check)
        
        layout.addWidget(behavior_group)
        
        # Updates group
        updates_group = QGroupBox("Updates")
        updates_layout = QVBoxLayout(updates_group)
        
        self.check_updates_check = QCheckBox("Check for updates automatically")
        self.check_updates_check.setChecked(self.settings.get("check_updates", True))
        updates_layout.addWidget(self.check_updates_check)
        
        layout.addWidget(updates_group)
        
        layout.addStretch()
        return widget
    
    def _create_proxy_tab(self) -> QWidget:
        """Create proxy settings tab"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(16)
        
        # Connection Mode group
        mode_group = QGroupBox("Connection Mode")
        mode_layout = QVBoxLayout(mode_group)
        
        mode_layout.addWidget(QLabel("How to route traffic:"))
        self.connection_mode_combo = QComboBox()
        self.connection_mode_combo.addItems([
            "System Proxy (browser & proxy-aware apps only)",
            "TUN Mode — VPN (all system traffic)"
        ])
        # Set current value
        current_mode = self.settings.get("connection_mode", "proxy")
        self.connection_mode_combo.setCurrentIndex(1 if current_mode == "tun" else 0)
        mode_layout.addWidget(self.connection_mode_combo)
        
        # TUN mode info label
        tun_info = QLabel(
            "ℹ️  TUN Mode creates a virtual network interface (tun0) that captures ALL\n"
            "traffic from every app. Requires root password (pkexec prompt).\n"
            "SNI bypass and payload injection work the same in both modes."
        )
        tun_info.setStyleSheet("color: #8b949e; font-size: 11px; padding: 4px 0;")
        tun_info.setWordWrap(True)
        mode_layout.addWidget(tun_info)
        
        layout.addWidget(mode_group)
        
        # Ports group
        ports_group = QGroupBox("Local Proxy Ports")
        ports_layout = QFormLayout(ports_group)
        
        self.socks_port_spin = QSpinBox()
        self.socks_port_spin.setRange(1024, 65535)
        self.socks_port_spin.setValue(self.settings.get("socks_port", 10808))
        ports_layout.addRow("SOCKS5 Port:", self.socks_port_spin)
        
        self.http_port_spin = QSpinBox()
        self.http_port_spin.setRange(1024, 65535)
        self.http_port_spin.setValue(self.settings.get("http_port", 10809))
        ports_layout.addRow("HTTP Port:", self.http_port_spin)
        
        layout.addWidget(ports_group)
        
        # Routing group
        routing_group = QGroupBox("Routing")
        routing_layout = QVBoxLayout(routing_group)
        
        routing_layout.addWidget(QLabel("Routing mode:"))
        self.routing_combo = QComboBox()
        self.routing_combo.addItems([
            "Global (route all traffic through proxy)",
            "Bypass LAN (exclude local network)",
            "Bypass China (for users in China)",
            "Custom rules"
        ])
        routing_layout.addWidget(self.routing_combo)
        
        layout.addWidget(routing_group)
        
        layout.addStretch()
        return widget
    
    def _create_dns_tab(self) -> QWidget:
        """Create DNS settings tab"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(16)
        
        # DNS servers group
        dns_group = QGroupBox("DNS Servers")
        dns_layout = QVBoxLayout(dns_group)
        
        dns_layout.addWidget(QLabel("DNS servers (one per line):"))
        
        self.dns_list = QListWidget()
        for dns in self.settings.get("dns_servers", ["8.8.8.8", "8.8.4.4"]):
            self.dns_list.addItem(dns)
        dns_layout.addWidget(self.dns_list)
        
        # DNS controls
        dns_controls = QHBoxLayout()
        
        self.dns_input = QLineEdit()
        self.dns_input.setPlaceholderText("Enter DNS server IP...")
        dns_controls.addWidget(self.dns_input, 1)
        
        add_dns_btn = QPushButton("Add")
        add_dns_btn.clicked.connect(self._add_dns)
        dns_controls.addWidget(add_dns_btn)
        
        remove_dns_btn = QPushButton("Remove")
        remove_dns_btn.clicked.connect(self._remove_dns)
        dns_controls.addWidget(remove_dns_btn)
        
        dns_layout.addLayout(dns_controls)
        
        # Presets
        presets_layout = QHBoxLayout()
        presets_layout.addWidget(QLabel("Presets:"))
        
        google_btn = QPushButton("Google")
        google_btn.clicked.connect(lambda: self._set_dns_preset(["8.8.8.8", "8.8.4.4"]))
        presets_layout.addWidget(google_btn)
        
        cloudflare_btn = QPushButton("Cloudflare")
        cloudflare_btn.clicked.connect(lambda: self._set_dns_preset(["1.1.1.1", "1.0.0.1"]))
        presets_layout.addWidget(cloudflare_btn)
        
        opendns_btn = QPushButton("OpenDNS")
        opendns_btn.clicked.connect(lambda: self._set_dns_preset(["208.67.222.222", "208.67.220.220"]))
        presets_layout.addWidget(opendns_btn)
        
        presets_layout.addStretch()
        dns_layout.addLayout(presets_layout)
        
        layout.addWidget(dns_group)
        
        layout.addStretch()
        return widget
    
    def _create_about_tab(self) -> QWidget:
        """Create about tab"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(12)
        
        # App name
        name = QLabel("VoidTunnel")
        name.setFont(QFont("Inter", 28, QFont.Weight.Bold))
        name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name.setStyleSheet("color: #58a6ff;")
        layout.addWidget(name)
        
        # Version
        version = QLabel("Version 1.1")
        version.setObjectName("subtitleLabel")
        version.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(version)
        
        layout.addSpacing(16)
        
        # Description
        desc = QLabel(
            "A powerful VPN/Proxy client for Linux built with Python and PyQt6.\n"
            "VoidTunnel uses Xray-core engine to provide secure, fast, and reliable\n"
            "connections through multiple protocols including VMess, VLESS, Trojan,\n"
            "Shadowsocks, and SSH. Features include payload injection, system proxy\n"
            "configuration, real-time traffic stats, and a modern dark UI."
        )
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc.setStyleSheet("color: #8b949e; line-height: 1.5;")
        layout.addWidget(desc)
        
        layout.addSpacing(20)
        
        # Powered by
        powered = QLabel("⚡ Powered by Xray-core")
        powered.setAlignment(Qt.AlignmentFlag.AlignCenter)
        powered.setStyleSheet("color: #3fb950; font-weight: 600;")
        layout.addWidget(powered)
        
        layout.addSpacing(20)
        
        # Developer credits
        dev_label = QLabel("👨‍💻 Developer")
        dev_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        dev_label.setFont(QFont("Inter", 11, QFont.Weight.Bold))
        layout.addWidget(dev_label)
        
        dev_name = QLabel("klsdfernando")
        dev_name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        dev_name.setStyleSheet("color: #e6edf3;")
        layout.addWidget(dev_name)
        
        layout.addSpacing(12)
        
        # GitHub links
        links_layout = QHBoxLayout()
        links_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        github_btn = QPushButton("🐙 GitHub Profile")
        github_btn.setStyleSheet("""
            QPushButton {
                background-color: #21262d;
                border: 1px solid #30363d;
                border-radius: 6px;
                padding: 8px 16px;
                color: #58a6ff;
            }
            QPushButton:hover {
                background-color: #30363d;
            }
        """)
        github_btn.clicked.connect(lambda: self._open_url("https://github.com/klsdfernando"))
        links_layout.addWidget(github_btn)
        
        repo_btn = QPushButton("📦 Repository")
        repo_btn.setStyleSheet("""
            QPushButton {
                background-color: #21262d;
                border: 1px solid #30363d;
                border-radius: 6px;
                padding: 8px 16px;
                color: #58a6ff;
            }
            QPushButton:hover {
                background-color: #30363d;
            }
        """)
        repo_btn.clicked.connect(lambda: self._open_url("https://github.com/klsdfernando/VoidTunnel"))
        links_layout.addWidget(repo_btn)
        
        layout.addLayout(links_layout)
        
        return widget
    
    def _open_url(self, url: str):
        """Open URL in browser"""
        import webbrowser
        webbrowser.open(url)
    
    def _add_dns(self):
        """Add DNS server"""
        dns = self.dns_input.text().strip()
        if dns:
            self.dns_list.addItem(dns)
            self.dns_input.clear()
    
    def _remove_dns(self):
        """Remove selected DNS server"""
        current = self.dns_list.currentRow()
        if current >= 0:
            self.dns_list.takeItem(current)
    
    def _set_dns_preset(self, servers: list):
        """Set DNS preset"""
        self.dns_list.clear()
        for dns in servers:
            self.dns_list.addItem(dns)
    
    def get_settings(self) -> dict:
        """Get the modified settings"""
        self.settings["auto_connect"] = self.auto_connect_check.isChecked()
        self.settings["start_minimized"] = self.start_minimized_check.isChecked()
        self.settings["minimize_to_tray"] = self.minimize_to_tray_check.isChecked()
        self.settings["enable_system_proxy"] = self.enable_system_proxy_check.isChecked()
        self.settings["check_updates"] = self.check_updates_check.isChecked()
        self.settings["socks_port"] = self.socks_port_spin.value()
        self.settings["http_port"] = self.http_port_spin.value()
        
        # Connection mode
        self.settings["connection_mode"] = "tun" if self.connection_mode_combo.currentIndex() == 1 else "proxy"
        
        # DNS servers
        dns_servers = []
        for i in range(self.dns_list.count()):
            dns_servers.append(self.dns_list.item(i).text())
        self.settings["dns_servers"] = dns_servers
        
        return self.settings
