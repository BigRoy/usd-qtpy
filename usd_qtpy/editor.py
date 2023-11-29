import logging

from qtpy import QtWidgets, QtCore

from . import (
    prim_hierarchy,
    layer_editor,
    prim_spec_editor
)


try:
    from usd_qtpy import viewer
    HAS_VIEWER = True
except ImportError:
    logging.warning("Unable to import usdview dependencies, skipping view..")
    HAS_VIEWER = False


class EditorWindow(QtWidgets.QWidget):
    """Example editor window containing the available components."""

    def __init__(self, stage, parent=None):
        super(EditorWindow, self).__init__(parent=parent)

        title = "USD Editor"
        if stage:
            name = stage.GetRootLayer().GetDisplayName()
            title = f"{title}: {name}"
        self.setWindowTitle(title)

        self.setWindowFlags(
            self.windowFlags() |
            QtCore.Qt.Dialog
        )

        layout = QtWidgets.QVBoxLayout(self)
        splitter = QtWidgets.QSplitter(self)
        layout.addWidget(splitter)

        layer_tree_widget = layer_editor.LayerTreeWidget(
            stage=stage,
            include_session_layer=False,
            parent=self
        )
        splitter.addWidget(layer_tree_widget)

        hierarchy_widget = prim_hierarchy.HierarchyWidget(stage=stage)
        splitter.addWidget(hierarchy_widget)

        viewer_widget = None
        if HAS_VIEWER:
            viewer_widget = viewer.Widget(stage=stage)
            splitter.addWidget(viewer_widget)

        prim_spec_editor_widget = prim_spec_editor.SpecEditorWindow(stage=stage)
        splitter.addWidget(prim_spec_editor_widget)

        # set up widgets to have a respective entry in Panels menu,
        # and filter them out if they are ill-defined. 
        self._panels = {
            "Layer Editor": layer_tree_widget,
            "Prim Hierarchy": hierarchy_widget,
            "Scene Viewer" : viewer_widget,
            "Prim Spec Editor": prim_spec_editor_widget
        }
        self._panels = {
            label : widget for label, widget
            in self._panels.items() if widget is not None
        }

        self.build_menubar()

    def build_menubar(self):

        menubar = QtWidgets.QMenuBar()

        panels_menu = menubar.addMenu("Panels")
        for label, widget in self._panels.items():
            action = panels_menu.addAction(label)
            action.setCheckable(True)
            action.setData(widget)
            action.toggled.connect(widget.setVisible)

        def update_panel_checkstate():
            """Ensure checked state matches current visibility of panel"""
            for action in panels_menu.actions():
                widget = action.data()
                visible = widget.isVisible()
                if visible != action.isChecked():
                    action.blockSignals(True)
                    action.setChecked(visible)
                    action.blockSignals(False)

        panels_menu.aboutToShow.connect(update_panel_checkstate)

        layout = self.layout()
        layout.setMenuBar(menubar)
