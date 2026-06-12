# -*- coding: utf-8 -*-
"""
Align Features to Path - QGIS Plugin
======================================
Mimics the ArcGIS Pro "Align Features" tool using a user-drawn alignment path.

Author: Mustafa Elghazaly
Version: 0.0.2
QGIS Minimum Version: 3.16
"""


def classFactory(iface):
    """
    Load the AlignFeaturesToPath plugin class.

    :param iface: A QGIS interface instance.
    :type iface: QgsInterface
    :return: Plugin instance
    """
    from .align_features_plugin import AlignFeaturesToPathPlugin
    return AlignFeaturesToPathPlugin(iface)
