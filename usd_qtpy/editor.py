import logging

from qtpy import QtWidgets

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


class EditorWindow(QtWidgets.QDialog):
    """Example editor window containing the available components."""
    def __init__(self, stage, parent=None):
        super(EditorWindow, self).__init__(parent=parent)

        self.setWindowTitle("USD Editor")

        layout = QtWidgets.QVBoxLayout(self)
        splitter = QtWidgets.QSplitter(self)
        layout.addWidget(splitter)

        # Menu bar
        menubar = QtWidgets.QMenuBar()

        file_action = menubar.addAction("File")
        tools_action = menubar.addAction("Tools")
        about_action = menubar.addAction("About")

        def print_label(action : QtWidgets.QAction):
            print(action.text())

        menubar.triggered.connect(print_label)

        file_menu = QtWidgets.QMenu()
        tools_menu = QtWidgets.QMenu()
        about_menu = QtWidgets.QMenu()

        file_action.setMenu(file_menu)
        tools_action.setMenu(tools_menu)
        about_action.setMenu(about_menu)

        test_actions = [f"test_{i}" for i in range(5)]
        menus = [file_menu,tools_menu,about_menu]

        for m in menus:
            for label in test_actions:
                action = m.addAction(f"{m.title()}_{label}")
            #m.triggered.connect(print_label)        

        layout.setMenuBar(menubar)

        layer_tree_widget = layer_editor.LayerTreeWidget(
            stage=stage,
            include_session_layer=False,
            parent=self
        )
        splitter.addWidget(layer_tree_widget)

        hierarchy_widget = prim_hierarchy.HierarchyWidget(stage=stage)
        splitter.addWidget(hierarchy_widget)

        if HAS_VIEWER:
            viewer_widget = viewer.Widget(stage=stage)
            splitter.addWidget(viewer_widget)

        prim_spec_editor_widget = prim_spec_editor.SpecEditorWindow(stage=stage)
        splitter.addWidget(prim_spec_editor_widget)
