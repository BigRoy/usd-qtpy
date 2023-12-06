import logging
from functools import partial

from qtpy import QtWidgets, QtCore

from . import (
    prim_hierarchy,
    layer_editor,
    prim_spec_editor,
    render_util
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

        self._stage = stage

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
        self._stageview = None
        if HAS_VIEWER:
            viewer_widget = viewer.Widget(stage=stage)
            self._stageview = viewer_widget.view
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

        # Panels menu

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

        # Render menu
        render_menu = menubar.addMenu("Render")
        render_labels = (
            "Playblast", "Snapshot", "Snapshot Framing Camera",
            "Render Turntable", "Import Turntable"
        )
        render_actions = {label: render_menu.addAction(label) for label in render_labels}
        
        # brings up dialog to snap the current camera view.
        render_snap = partial(render_util.dialog._savepicture_dialog, self._stage, self._stageview)

        def snap_framingcam(stage):
            """Render still frame from a 'framed camera'"""
            filepath = render_util.prompt_output_path("Save frame with framing camera")
            if not filepath:
                return
            camera = render_util.create_framing_camera_in_stage(stage, fit=1.1)
            render_util.render_playblast(stage, 
                                         filepath,
                                         "1", 
                                         1920, 
                                         renderer="GL", 
                                         camera=camera)

        render_snap_with_framingcam = partial(snap_framingcam, self._stage)

        def render_turntable(stage):
            """Render turntable 'framed camera' rotating around stage center"""
            filepath = render_util.prompt_output_path("Render turntable")
            if not filepath:
                return
            framecam = render_util.create_turntable_camera(stage)
            render_util.render_playblast(stage, 
                                         filepath,
                                         "0:99", 
                                         1920, 
                                         renderer="GL", 
                                         camera=framecam)

        render_ttable = partial(render_turntable, self._stage)

        import_ttable = partial(render_util.turntable.turntable_from_file, self._stage)

        render_actions["Snapshot"].triggered.connect(render_snap)
        render_actions["Snapshot Framing Camera"].triggered.connect(render_snap_with_framingcam)
        render_actions["Render Turntable"].triggered.connect(render_ttable)
        render_actions["Import Turntable"].triggered.connect(import_ttable)

        layout = self.layout()
        layout.setMenuBar(menubar)
