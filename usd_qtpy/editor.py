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

        if HAS_VIEWER:
            self._build_render_menu(menubar)

        layout = self.layout()
        layout.setMenuBar(menubar)

    def _build_render_menu(self, menubar):

        # Import here because we only want to import this dependency
        # if the viewer libraries exist
        from . import render_util

        # Render menu
        render_menu = menubar.addMenu("Render")
        labels = (
            "Snapshot View",
            "Snapshot Framing Camera",
            "Playblast Stage",
            "Turntable Stage"
        )
        actions = {label: render_menu.addAction(label) for label in labels}

        def render_snap():
            """Render still frame from current view"""
            # TODO: Allow picking resolution
            filepath = render_util.prompt_output_path("Save frame")
            if not filepath:
                return
            render_util.dialog.save_image_from_stageview(self._stageview,
                                                         filepath)

        def render_snap_framed():
            """Render still frame from a 'framed camera'"""
            filepath = render_util.prompt_output_path("Save frame with framing camera")
            if not filepath:
                return
            stage = self._stage
            camera = render_util.create_framing_camera_in_stage(stage, fit=1.1)
            render_util.render_playblast(stage, 
                                         filepath,
                                         "1", 
                                         1920, 
                                         renderer="GL", 
                                         camera=camera)
            stage.RemovePrim(camera.GetPath())

        def playblast_stage_dialog():
            dialog = render_util.PlayblastDialog(self,
                                                 self._stage,
                                                 self._stageview)
            dialog.show()

        def turntable_stage_dialog():
            dialog = render_util.TurntableDialog(self,
                                                 self._stage,
                                                 self._stageview)
            dialog.show()

        actions["Snapshot View"].triggered.connect(render_snap)
        actions["Snapshot Framing Camera"].triggered.connect(render_snap_framed)
        actions["Playblast Stage"].triggered.connect(playblast_stage_dialog)
        actions["Turntable Stage"].triggered.connect(turntable_stage_dialog)
