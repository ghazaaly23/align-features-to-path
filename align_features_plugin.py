# -*- coding: utf-8 -*-
"""
align_features_plugin.py
=========================
Main plugin class. Registers the toolbar button, menu entry,
and manages the lifecycle of the dock panel.

Author: Mustafa Elghazaly
"""

import os

from qgis.PyQt.QtCore import Qt, QTranslator, QCoreApplication
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QDockWidget
# QAction lives in QtWidgets under Qt5 (QGIS 3.x) but was moved to QtGui under
# Qt6 (QGIS 4).  Import from whichever location the running bindings expose so
# the plugin loads on both 3.x and 4.x without a hard ImportError.
try:
    from qgis.PyQt.QtWidgets import QAction
except ImportError:  # Qt6 / PyQt6
    from qgis.PyQt.QtGui import QAction
from qgis.core import QgsMessageLog, Qgis


class AlignFeaturesToPathPlugin:
    """QGIS Plugin Implementation."""

    def __init__(self, iface):
        """
        Constructor.

        :param iface: QGIS interface instance (QgsInterface).
        """
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.actions = []
        self.menu = self.tr("&Align Features to Path")
        self.dock_widget = None
        self._action_show_panel = None

    # ------------------------------------------------------------------
    # i18n helper
    # ------------------------------------------------------------------
    def tr(self, message):
        return QCoreApplication.translate("AlignFeaturesToPath", message)

    # ------------------------------------------------------------------
    # Plugin lifecycle
    # ------------------------------------------------------------------
    def initGui(self):
        """Create the menu entry and toolbar button."""
        icon_path = os.path.join(self.plugin_dir, "icon.png")
        icon = QIcon(icon_path) if os.path.exists(icon_path) else QIcon()

        self._action_show_panel = QAction(
            icon,
            self.tr("Align Features to Path"),
            self.iface.mainWindow(),
        )
        self._action_show_panel.setCheckable(True)
        self._action_show_panel.setToolTip(
            self.tr("Open the Align Features to Path panel")
        )
        self._action_show_panel.triggered.connect(self._toggle_panel)

        self.iface.addPluginToVectorMenu(self.menu, self._action_show_panel)
        self.iface.addToolBarIcon(self._action_show_panel)
        self.actions.append(self._action_show_panel)

        QgsMessageLog.logMessage(
            "Align Features to Path plugin loaded.", "AlignFeatures", Qgis.MessageLevel.Info
        )

    def unload(self):
        """Remove the plugin menu item and toolbar icon."""
        for action in self.actions:
            self.iface.removePluginVectorMenu(self.menu, action)
            self.iface.removeToolBarIcon(action)

        if self.dock_widget is not None:
            self.iface.removeDockWidget(self.dock_widget)
            self.dock_widget.deleteLater()
            self.dock_widget = None

    # ------------------------------------------------------------------
    # Panel management
    # ------------------------------------------------------------------
    def _toggle_panel(self, checked):
        """Show or hide the dock panel."""
        if checked:
            self._show_panel()
        else:
            self._hide_panel()

    def _show_panel(self):
        """Create (if needed) and show the dock widget."""
        if self.dock_widget is None:
            from .align_to_path_dialog import AlignToPathDockWidget

            self.dock_widget = AlignToPathDockWidget(self.iface, self.iface.mainWindow())
            self.dock_widget.setWindowTitle(self.tr("Align Features to Path"))
            self.dock_widget.visibilityChanged.connect(self._on_panel_visibility_changed)

            self.iface.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.dock_widget)
        else:
            self.dock_widget.show()

        self._action_show_panel.setChecked(True)

    def _hide_panel(self):
        if self.dock_widget is not None:
            self.dock_widget.hide()
        self._action_show_panel.setChecked(False)

    def _on_panel_visibility_changed(self, visible):
        """Sync toolbar button checked state with dock visibility."""
        self._action_show_panel.setChecked(visible)
