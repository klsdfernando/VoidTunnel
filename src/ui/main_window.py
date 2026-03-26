"""
Main Window - Primary application UI
"""

import os
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QLabel, QPushButton, QStackedWidget, QFrame,
    QSystemTrayIcon, QMenu, QMessageBox, QStatusBar,
    QSplitter, QApplication
)
from PyQt6.QtCore import Qt, QSize, pyqtSlot, QTimer
from PyQt6.QtGui import QIcon, QAction, QFont, QPixmap

from src.ui.connect_widget import ConnectWidget
from src.ui.profile_widget import ProfileWidget
from src.ui.settings_dialog import SettingsDialog
from src.ui.log_viewer import LogViewer
from src.ui.payload_editor import PayloadEditor

from src.core.xray_controller import XrayController
from src.core.profile_manager import ProfileManager
from src.core.config_manager import ConfigManager
from src.core.proxy_manager import ProxyManager
from src.core.singbox_manager import SingBoxManager
from src.utils.helpers import load_settings, save_settings
from src.utils.network import check_proxy_connection


class MainWindow(QMainWindow):
    """Main application window"""
    
    def __init__(self):
        super().__init__()
        
        # Initialize managers
        self.settings = load_settings()
        self.profile_manager = ProfileManager()
        self.config_manager = ConfigManager()
        self.proxy_manager = ProxyManager(
            socks_port=self.settings.get("socks_port", 10808),
            http_port=self.settings.get("http_port", 10809)
        )
        self.xray_controller = XrayController()
        self.singbox_manager = SingBoxManager()
        
        # Connect signals
        self.xray_controller.status_changed.connect(self._on_connection_status_changed)
        self.xray_controller.log_received.connect(self._on_log_received)
        self.xray_controller.error_occurred.connect(self._on_error)
        self.singbox_manager.status_changed.connect(self._on_log_received)
        self.singbox_manager.error_occurred.connect(self._on_error)
        
        # State
        self.is_connected = False
        self.connection_time = 0
        
        # Setup UI
        self._setup_ui()
        self._setup_tray()
        self._load_stylesheet()
        
        # Connection timer
        self.connection_timer = QTimer()
        self.connection_timer.timeout.connect(self._update_connection_time)
        
        # Check if Xray exists
        if not self.xray_controller.check_xray_exists():
            QTimer.singleShot(1000, self._prompt_download_xray)
    
    def _setup_ui(self):
        """Setup the main UI"""
        self.setWindowTitle("VoidTunnel")
        self.setMinimumSize(900, 600)
        self.resize(1000, 650)
        
        # Set window icon
        icon_path = os.path.join(os.path.dirname(__file__), "..", "resources", "icons", "voidtunnel.jpg")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        
        # Central widget
        central = QWidget()
        self.setCentralWidget(central)
        
        # Main layout
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # Sidebar
        sidebar = self._create_sidebar()
        main_layout.addWidget(sidebar)
        
        # Content area
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        
        # Header
        header = self._create_header()
        content_layout.addWidget(header)
        
        # Stacked widget for pages
        self.stack = QStackedWidget()
        
        # Create pages
        self.connect_widget = ConnectWidget(
            self.profile_manager,
            self.xray_controller,
            self.config_manager,
            self.proxy_manager,
            self.singbox_manager,
            self.settings
        )
        self.profile_widget = ProfileWidget(self.profile_manager)
        self.log_viewer = LogViewer()
        self.payload_editor = PayloadEditor(self.profile_manager)
        
        self.stack.addWidget(self.connect_widget)      # 0
        self.stack.addWidget(self.profile_widget)      # 1
        self.stack.addWidget(self.log_viewer)          # 2
        self.stack.addWidget(self.payload_editor)      # 3
        
        content_layout.addWidget(self.stack, 1)
        
        main_layout.addWidget(content, 1)
        
        # Status bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self._update_status_bar()
        
        # Connect profile widget signals
        self.profile_widget.profile_selected.connect(self.connect_widget.on_profile_selected)
        self.connect_widget.connection_changed.connect(self._on_connection_changed)
    
    def _create_sidebar(self) -> QFrame:
        """Create the sidebar navigation"""
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(200)
        
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(12, 16, 12, 16)
        layout.setSpacing(8)
        
        # App title
        title = QLabel("VoidTunnel")
        title.setObjectName("titleLabel")
        title.setFont(QFont("Inter", 16, QFont.Weight.Bold))
        layout.addWidget(title)
        
        subtitle = QLabel("VPN/Proxy Client")
        subtitle.setObjectName("subtitleLabel")
        layout.addWidget(subtitle)
        
        layout.addSpacing(24)
        
        # Navigation buttons
        self.nav_buttons = []
        
        nav_items = [
            ("🔌  Connect", 0),
            ("📋  Servers", 1),
            ("📝  Logs", 2),
            ("⚙️  Payload", 3),
        ]
        
        for label, index in nav_items:
            btn = QPushButton(label)
            btn.setObjectName("navButton")
            btn.setCheckable(True)
            btn.setChecked(index == 0)
            btn.setStyleSheet("""
                QPushButton#navButton {
                    text-align: left;
                    padding: 12px 16px;
                    border-radius: 8px;
                    font-size: 14px;
                    background-color: transparent;
                    border: none;
                }
                QPushButton#navButton:hover {
                    background-color: #21262d;
                }
                QPushButton#navButton:checked {
                    background-color: #21262d;
                    color: #58a6ff;
                }
            """)
            btn.clicked.connect(lambda checked, i=index: self._navigate(i))
            layout.addWidget(btn)
            self.nav_buttons.append(btn)
        
        layout.addStretch()
        
        # Settings button
        settings_btn = QPushButton("⚙️  Settings")
        settings_btn.setObjectName("navButton")
        settings_btn.setStyleSheet("""
            QPushButton {
                text-align: left;
                padding: 12px 16px;
                border-radius: 8px;
                font-size: 14px;
                background-color: transparent;
                border: none;
            }
            QPushButton:hover {
                background-color: #21262d;
            }
        """)
        settings_btn.clicked.connect(self._open_settings)
        layout.addWidget(settings_btn)
        
        return sidebar
    
    def _create_header(self) -> QFrame:
        """Create the header with connection status"""
        header = QFrame()
        header.setObjectName("header")
        header.setFixedHeight(60)
        
        layout = QHBoxLayout(header)
        layout.setContentsMargins(24, 0, 24, 0)
        
        # Status indicator
        self.status_indicator = QFrame()
        self.status_indicator.setObjectName("statusIndicator")
        self.status_indicator.setProperty("status", "disconnected")
        layout.addWidget(self.status_indicator)
        
        # Status text
        self.status_label = QLabel("Disconnected")
        self.status_label.setObjectName("statusLabel")
        self.status_label.setProperty("status", "disconnected")
        layout.addWidget(self.status_label)
        
        layout.addStretch()
        
        # Connection time
        self.time_label = QLabel("")
        self.time_label.setObjectName("subtitleLabel")
        layout.addWidget(self.time_label)
        
        # Quick connect button
        self.quick_connect_btn = QPushButton("Connect")
        self.quick_connect_btn.setObjectName("connectButton")
        self.quick_connect_btn.setProperty("connected", False)
        self.quick_connect_btn.setFixedWidth(100)
        self.quick_connect_btn.clicked.connect(self._toggle_connection)
        layout.addWidget(self.quick_connect_btn)
        
        return header
    
    def _setup_tray(self):
        """Setup system tray icon"""
        self.tray_icon = QSystemTrayIcon(self)
        
        # Set tray icon
        icon_path = os.path.join(os.path.dirname(__file__), "..", "resources", "icons", "voidtunnel.jpg")
        if os.path.exists(icon_path):
            self.tray_icon.setIcon(QIcon(icon_path))
        
        tray_menu = QMenu()
        
        show_action = QAction("Show", self)
        show_action.triggered.connect(self.show)
        tray_menu.addAction(show_action)
        
        tray_menu.addSeparator()
        
        self.tray_connect_action = QAction("Connect", self)
        self.tray_connect_action.triggered.connect(self._toggle_connection)
        tray_menu.addAction(self.tray_connect_action)
        
        tray_menu.addSeparator()
        
        quit_action = QAction("Quit", self)
        quit_action.triggered.connect(self._quit_app)
        tray_menu.addAction(quit_action)
        
        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self._on_tray_activated)
        self.tray_icon.show()
    
    def _load_stylesheet(self):
        """Load the application stylesheet"""
        style_path = os.path.join(
            os.path.dirname(__file__), 
            "..", "resources", "styles", "dark_theme.qss"
        )
        
        if os.path.exists(style_path):
            with open(style_path, 'r') as f:
                self.setStyleSheet(f.read())
    
    def _navigate(self, index: int):
        """Navigate to a page"""
        self.stack.setCurrentIndex(index)
        for i, btn in enumerate(self.nav_buttons):
            btn.setChecked(i == index)
    
    def _toggle_connection(self):
        """Toggle VPN connection"""
        if self.is_connected:
            self.connect_widget.disconnect()
        else:
            self.connect_widget.connect()
    
    @pyqtSlot(bool)
    def _on_connection_changed(self, connected: bool):
        """Handle connection state changes"""
        self.is_connected = connected
        self._update_connection_ui()
        
        if connected:
            self.connection_time = 0
            self.connection_timer.start(1000)
        else:
            self.connection_timer.stop()
            self.time_label.setText("")
    
    @pyqtSlot(bool)
    def _on_connection_status_changed(self, connected: bool):
        """Handle Xray connection status changes"""
        self._on_connection_changed(connected)
    
    def _update_connection_ui(self):
        """Update UI elements based on connection state"""
        status = "connected" if self.is_connected else "disconnected"
        
        self.status_indicator.setProperty("status", status)
        self.status_indicator.style().unpolish(self.status_indicator)
        self.status_indicator.style().polish(self.status_indicator)
        
        self.status_label.setText("Connected" if self.is_connected else "Disconnected")
        self.status_label.setProperty("status", status)
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)
        
        self.quick_connect_btn.setText("Disconnect" if self.is_connected else "Connect")
        self.quick_connect_btn.setProperty("connected", self.is_connected)
        self.quick_connect_btn.style().unpolish(self.quick_connect_btn)
        self.quick_connect_btn.style().polish(self.quick_connect_btn)
        
        self.tray_connect_action.setText("Disconnect" if self.is_connected else "Connect")
        
        self._update_status_bar()
    
    def _update_connection_time(self):
        """Update connection time display"""
        self.connection_time += 1
        hours = self.connection_time // 3600
        minutes = (self.connection_time % 3600) // 60
        seconds = self.connection_time % 60
        
        if hours > 0:
            self.time_label.setText(f"{hours:02d}:{minutes:02d}:{seconds:02d}")
        else:
            self.time_label.setText(f"{minutes:02d}:{seconds:02d}")
    
    def _update_status_bar(self):
        """Update status bar"""
        xray_version = self.xray_controller.get_version()
        proxy_status = "Proxy: ON" if self.is_connected else "Proxy: OFF"
        ports = f"SOCKS: {self.settings.get('socks_port', 10808)} | HTTP: {self.settings.get('http_port', 10809)}"
        
        self.status_bar.showMessage(f"Xray: {xray_version}  |  {proxy_status}  |  {ports}")
    
    @pyqtSlot(str)
    def _on_log_received(self, log: str):
        """Handle log messages"""
        self.log_viewer.append_log(log)
    
    @pyqtSlot(str)
    def _on_error(self, error: str):
        """Handle errors"""
        QMessageBox.warning(self, "Error", error)
    
    def _open_settings(self):
        """Open settings dialog"""
        dialog = SettingsDialog(self.settings, self)
        if dialog.exec():
            self.settings = dialog.get_settings()
            save_settings(self.settings)
            
            # Propagate settings to all components
            self.connect_widget.settings = self.settings
            self.proxy_manager.update_ports(
                socks_port=self.settings.get("socks_port", 10808),
                http_port=self.settings.get("http_port", 10809)
            )
            
            self._update_status_bar()
    
    def _prompt_download_xray(self):
        """Prompt user to download Xray-core"""
        reply = QMessageBox.question(
            self,
            "Xray-core Not Found",
            "Xray-core is required but not installed.\n\nWould you like to download it now?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            self._download_xray()
    
    def _download_xray(self):
        """Download Xray-core"""
        from .download_dialog import DownloadDialog
        dialog = DownloadDialog(self.xray_controller, self)
        dialog.exec()
    
    def _on_tray_activated(self, reason):
        """Handle tray icon activation"""
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.show()
            self.raise_()
            self.activateWindow()
    
    def closeEvent(self, event):
        """Handle window close"""
        if self.settings.get("minimize_to_tray", True):
            event.ignore()
            self.hide()
        else:
            self._quit_app()
    
    def _quit_app(self):
        """Quit the application"""
        if self.is_connected:
            self.connect_widget.disconnect()
        # Ensure sing-box cleanup even if disconnect failed
        if self.singbox_manager.is_active:
            self.singbox_manager.stop()
        self.tray_icon.hide()
        QApplication.quit()
