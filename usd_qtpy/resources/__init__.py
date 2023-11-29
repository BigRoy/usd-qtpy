import os
from qtpy import QtGui


FEATHERICONS_ROOT = os.path.join(os.path.dirname(__file__), "feathericons")


def get_icon_path(name):
    return os.path.join(FEATHERICONS_ROOT, f"{name}.svg")


def get_icon(name):
    return QtGui.QIcon(get_icon_path(name))
