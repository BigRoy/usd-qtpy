from qtpy import QtWidgets
from pxr import Usd

from usd_qtpy import prim_hierarchy, layer_editor, prim_spec_editor

try:
    from usd_qtpy import viewer
    HAS_VIEWER = True
except ImportError:
    print("Unable to import usdview dependencies, skipping view..")
    HAS_VIEWER = False


class Window(QtWidgets.QDialog):
    def __init__(self, stage, parent=None):
        super(Window, self).__init__(parent=parent)

        self.setWindowTitle("USD Editor")

        layout = QtWidgets.QVBoxLayout(self)
        splitter = QtWidgets.QSplitter(self)
        layout.addWidget(splitter)

        layers = layer_editor.LayerTreeWidget(
            stage=stage,
            include_session_layer=False,
            parent=self
        )
        splitter.addWidget(layers)

        hierarchy = prim_hierarchy.HierarchyWidget(stage=stage)
        splitter.addWidget(hierarchy)

        if HAS_VIEWER:
            viewer_widget = viewer.Widget(stage=stage)
            splitter.addWidget(viewer_widget)

        prim_spec_editor_widget = prim_spec_editor.SpecEditorWindow(stage=stage)
        splitter.addWidget(prim_spec_editor_widget)


if __name__ == "__main__":
    path = "/path/to/usd/file.usda"
    stage = Usd.Stage.Open(path)
    app = QtWidgets.QApplication()
    dialog = Window(stage=stage)
    dialog.show()
    dialog.resize(600, 600)
    app.exec_()
