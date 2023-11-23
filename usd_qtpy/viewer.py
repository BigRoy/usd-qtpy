import logging
from functools import partial

from qtpy import QtWidgets, QtCore, QtGui

from pxr import Usd, UsdGeom, Tf
from pxr.Usdviewq.stageView import StageView
from pxr.Usdviewq import common

try:
    # Use C++ implementation of USD View
    from pxr.Usdviewq._usdviewq import Utils
    GetAllPrimsOfType = Utils._GetAllPrimsOfType
except ImportError as exc:
    # TODO: Implement a Python implementation
    raise

log = logging.getLogger(__name__)


class QJumpSlider(QtWidgets.QSlider):
    """QSlider that jumps to exactly where you click on it.

    This can also be done using QProxyStyle however that is unavailable
    in PySide, PyQt4 and early releases of PySide2 (e.g. Maya 2019) as
    such we implement it in a slightly less clean way.
    See: https://stackoverflow.com/a/26281608/1838864

    """

    def __init__(self, parent=None):
        super(QJumpSlider, self).__init__(parent)

    def mousePressEvent(self, event):
        # Jump to click position
        self.setValue(QtWidgets.QStyle.sliderValueFromPosition(self.minimum(),
                                                               self.maximum(),
                                                               event.x(),
                                                               self.width()))

    def mouseMoveEvent(self, event):
        # Jump to pointer position while moving
        self.setValue(QtWidgets.QStyle.sliderValueFromPosition(self.minimum(),
                                                               self.maximum(),
                                                               event.x(),
                                                               self.width()))


class TimelineWidget(QtWidgets.QWidget):
    """Timeline widget

    The timeline plays throught time using QTimer and
    will try to match the FPS based on time spent between
    each frame.

    """
    # todo: Allow auto stop on __del__ or cleanup to kill timers

    frameChanged = QtCore.Signal(int, bool)
    playbackStopped = QtCore.Signal()
    playbackStarted = QtCore.Signal()

    def __init__(self, parent=None):
        super(TimelineWidget, self).__init__(parent=parent)

        # Don't take up more space in height than needed
        self.setSizePolicy(QtWidgets.QSizePolicy.Preferred,
                           QtWidgets.QSizePolicy.Fixed)

        self.slider = QJumpSlider(QtCore.Qt.Horizontal)
        self.slider.setStyleSheet("""
        QSlider::groove:horizontal {
    border: 1px solid #999999;
    background-color: #9999A5;
    margin: 0px 0;
}

QSlider::handle:horizontal {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #112233, stop:1 #223344);
    border: 1px solid #5c5c5c;
    width: 15px;
    border-radius: 3px;
}
        """)

        # A bit of a random min/max
        # todo: replace this with sys.minint or alike
        RANGE = 1e6

        self.start = QtWidgets.QSpinBox()
        self.start.setButtonSymbols(QtWidgets.QAbstractSpinBox.NoButtons)
        self.start.setMinimum(-RANGE)
        self.start.setMaximum(RANGE)
        self.start.setKeyboardTracking(False)
        self.end = QtWidgets.QSpinBox()
        self.end.setButtonSymbols(QtWidgets.QAbstractSpinBox.NoButtons)
        self.end.setMinimum(-RANGE)
        self.end.setMaximum(RANGE)
        self.end.setKeyboardTracking(False)
        self.frame = QtWidgets.QSpinBox()
        self.frame.setButtonSymbols(QtWidgets.QAbstractSpinBox.NoButtons)
        self.frame.setMinimum(-RANGE)
        self.frame.setMaximum(RANGE)
        self.frame.setKeyboardTracking(False)
        self.playButton = QtWidgets.QPushButton("Play")

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        layout.addWidget(self.start)
        layout.addWidget(self.slider)
        layout.addWidget(self.end)
        layout.addWidget(self.frame)
        layout.addWidget(self.playButton)

        # Timeout interval in ms. We set it to 0 so it runs as fast as
        # possible. In advanceFrameForPlayback we use the sleep() call
        # to slow down rendering to self.framesPerSecond fps.
        self._timer = QtCore.QTimer(self)

        fps = 25
        interval = 1000 / float(fps)

        self._timer.setInterval(interval)
        self._timer.timeout.connect(self._advanceFrameForPlayback)

        self.playButton.clicked.connect(self.toggle_play)
        self.slider.valueChanged.connect(self.frame.setValue)
        self.frame.valueChanged.connect(self._frameChanged)
        self.start.valueChanged.connect(self.slider.setMinimum)
        self.end.valueChanged.connect(self.slider.setMaximum)

    def setStartFrame(self, start):
        self.start.setValue(start)

    def setEndFrame(self, end):
        self.end.setValue(end)

    @property
    def playing(self):
        return self._timer.isActive()

    @playing.setter
    def playing(self, state):

        if self.playing == state:
            # Do nothing
            return

        # Change play/stop button based on new state
        self.playButton.setText("Stop" if state else "Play")

        if state:
            self._timer.start()
            self.playbackStarted.emit()

            # Set focus to the slider as it helps
            # key shortcuts to be registered on
            # the widgets we actually want it.
            self.slider.setFocus()

        else:
            self._timer.stop()
            self.playbackStopped.emit()

    def toggle_play(self):
        # Toggle play state
        self.playing = not self.playing

    def _advanceFrameForPlayback(self):

        # This should actually make sure that the playback speed
        # matches the FPS of the scene. Currently it will advance
        # as fast as possible. As such a very light scene will run
        # super fast. See `_advanceFrameForPlayback` in USD view
        # on how they manage the playback speed. That code is in:
        # pxr/usdImaging/lib/usdviewq/appController.py

        frame = self.frame.value()
        frame += 1
        # Loop around
        if frame >= self.slider.maximum():
            frame = self.slider.minimum()

        self.slider.setValue(frame)

    def _frameChanged(self, frame):
        """Trigger a frame change callback together with whether it's currently playing."""

        if self.slider.value() != frame:
            # Whenever a manual frame was entered
            # in the frame lineedit then the slider
            # would not have updated along.
            self.slider.blockSignals(True)
            self.slider.setValue(True)
            self.slider.blockSignals(False)

        self.frameChanged.emit(frame, self.playing)


class CustomStageView(StageView):
    """Wrapper around usdview's StageView.

    UsdView's default StageView does not allow disabling the DrawAxis
    behavior where it draws an axis at the origin. This subclass allows
    disabling it.


    """
    draw_axis = False

    def SetDrawAxis(self, state):
        self.draw_axis = state

    def DrawAxis(self, viewProjectionMatrix):
        if self.draw_axis:
            super(CustomStageView, self).DrawAxis(viewProjectionMatrix)


class Widget(QtWidgets.QWidget):
    def __init__(self, stage=None, parent=None):
        super(Widget, self).__init__(parent=parent)

        self.model = StageView.DefaultDataModel()
        self.model.viewSettings.showHUD = False
        self.model.viewSettings.showBBoxes = False
        # self.model.viewSettings.selHighlightMode = "Always"

        self.view = CustomStageView(dataModel=self.model)

        self.timeline = TimelineWidget()

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(self.view)
        layout.addWidget(self.timeline)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        self.timeline.frameChanged.connect(self.on_frame_changed)
        self.timeline.playbackStarted.connect(self.on_playback_started)
        self.timeline.playbackStopped.connect(self.on_playback_stopped)
        # set button context menu policy
        self.view.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.view.customContextMenuRequested.connect(self.on_context_menu)

        self.setAcceptDrops(True)

        if stage:
            self.setStage(stage)

        # Set focus to the widget itself so that it's not the start
        # frame text edit that takes focus
        self.setFocus()

    def refresh(self):
        log.debug("Refresh viewer")
        self.view.recomputeBBox()
        self.view.updateGL()
        self.view.updateView()

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            filename = url.toLocalFile()
            stage = Usd.Stage.Open(filename)
            self.setStage(stage)

            self.refresh()
            return

    def on_context_menu(self, point):
        # TODO: Context menu should not show on "zoom in/out"
        #  but only on right click itself

        menu = QtWidgets.QMenu(parent=self.view)

        def bool_property_action(
                mod, name, label
        ):
            """Create QAction wrapper around a property"""
            action = QtGui.QAction(label, menu)
            action.setCheckable(True)
            value = getattr(mod, name, None)
            if value is None:
                # Attribute does not exist
                log.error("Missing property: %s", name)
                return
            action.setChecked(value)
            action.toggled.connect(partial(setattr, mod, name))
            return action

        def set_rendermode(action):
            """Set rendermode"""
            self.model.viewSettings.renderMode = action.text()

        # Shading modes
        shading_menu = menu.addMenu("Display")
        group = QtWidgets.QActionGroup(menu)
        group.setExclusive(True)
        for mode in common.RenderModes:
            action = QtWidgets.QAction(
                mode,
                checkable=True,
                checked=self.model.viewSettings.renderMode == mode
            )
            shading_menu.addAction(action)
            group.addAction(action)
        group.triggered.connect(set_rendermode)
        # TODO: Set view settings

        purpose_menu = menu.addMenu("Display Purpose")
        for purpose in ["Guide", "Proxy", "Render"]:
            key = f"display{purpose}"
            state = getattr(self.model.viewSettings, key) == purpose
            action = QtWidgets.QAction(
                purpose,
                checkable=True,
                checked=state)
            purpose_menu.addAction(action)
            action.triggered.connect(
                partial(setattr, self.model.viewSettings, key, not state)
            )

        # help(self.model.viewSettings)

        lights_menu = menu.addMenu("Lights")
        action = bool_property_action(self.model.viewSettings,
                                      "enableSceneLights",
                                      "Enable Scene Lights")
        lights_menu.addAction(action)
        action = bool_property_action(self.model.viewSettings,
                                      "ambientLightOnly",
                                      "Enable Default Camera Light")
        lights_menu.addAction(action)
        action = bool_property_action(self.model.viewSettings,
                                      "domeLightEnabled",
                                      "Enable Default Dome Light")
        lights_menu.addAction(action)

        action = bool_property_action(self.model.viewSettings,
                                      "showBBoxes",
                                      "Show Bounding Box")
        menu.addAction(action)
        action = bool_property_action(self.model.viewSettings,
                                      "enableSceneMaterials",
                                      "Enable Scene Materials", )
        menu.addAction(action)
        action = bool_property_action(self.model.viewSettings,
                                      "cullBackfaces",
                                      "Cull Backfaces")
        menu.addAction(action)

        # Get and set cameras
        cameras = GetAllPrimsOfType(self.model.stage,
                                    Tf.Type.Find(UsdGeom.Camera))
        camera_menu = menu.addMenu("Camera")
        fit = camera_menu.addAction("Fit to view")
        fit.triggered.connect(partial(self.view.resetCam, 2.0))
        free_cam = camera_menu.addAction("<Free camera>")
        free_cam.triggered.connect(self.view.switchToFreeCamera)
        for cam in cameras:
            cam_path = str(cam.GetPath())

            action = QtGui.QAction(cam_path, camera_menu)
            action.setCheckable(True)
            action.setChecked(self.model.viewSettings.cameraPrim == cam)
            action.triggered.connect(partial(self.set_camera, cam))

            camera_menu.addAction(action)

        # Set renderer plugin
        renderer_menu = menu.addMenu("Renderer")
        current_renderer = self.view.GetCurrentRendererId()
        group = QtWidgets.QActionGroup(menu)
        group.setExclusive(True)
        for renderer_id in self.view.GetRendererPlugins():
            # TODO: Get nice name for renderer plugin to display to user
            renderer = self.view.GetRendererDisplayName(renderer_id)
            action = renderer_menu.addAction(renderer)
            action.setCheckable(True)
            action.setChecked(renderer_id == current_renderer)
            action.triggered.connect(
                partial(self.view.SetRendererPlugin, renderer_id))
            renderer_menu.addAction(action)
            group.addAction(action)

        renderer_commands_menu = menu.addMenu("Renderer Commands")
        for command in self.view.GetRendererCommands():
            action = renderer_commands_menu.addAction(
                command.commandDescription)
            action.triggered.connect(
                partial(self.view.InvokeRendererCommand, command)
            )
        if not renderer_commands_menu.actions():
            renderer_commands_menu.setEnabled(False)
        # TODO: Expose renderer specific settings like USD view does?

        aov_menu = menu.addMenu("Renderer AOV")
        current_aov = None
        for aov in self.view.GetRendererAovs():
            action = aov_menu.addAction(
                aov,
                checkable=True,
                checked=aov == current_aov
            )
            action.triggered.connect(
                partial(self.view.SetRendererAov, aov)
            )
        if not aov_menu.actions():
            aov_menu.setEnabled(False)

        menu.exec_(self.view.mapToGlobal(point))

    def set_camera(self, prim):
        self.model.viewSettings.cameraPrim = prim

    def setPreviewColors(self, prim, color, alpha):
        # refs:
        # https://graphics.pixar.com/usd/docs/Simple-Shading-in-USD.html
        # https://graphics.pixar.com/usd/docs/UsdPreviewSurface-Proposal.html
        pass

    def setStage(self, stage):
        self.model.stage = stage

        # Set the model to the earliest time so that for animated meshes
        # like Alembicit will be able to display the geometry
        # see: https://github.com/PixarAnimationStudios/USD/issues/1022
        earliest = Usd.TimeCode.EarliestTime()
        self.model.currentFrame = Usd.TimeCode(earliest)

        # TODO: Add listener to redraw on any stage content changes so it
        #   updates the view accordingly (maybe with a slight scheduled delay
        #   to avoid a lot of redrawing if changes were made outside of
        #   `Sdf.ChangeBlock` code? We don't care too much about being instant
        #   on the redraw

        # TODO: Show/hide the timeline and set it to frame range of the
        #  animation if the loaded stage has an authored time code.

        # TODO: If the scene contains lights then disable default camera light
        #   and default dome light so the scene is accurately lit with what
        #   is in the USD file only

    def closeEvent(self, event):

        # Stop timeline so it stops its QTimer
        self.timeline.playing = False

        # Ensure to close the renderer to avoid GlfPostPendingGLErrors
        self.view.closeRenderer()

    def on_frame_changed(self, value, playback):
        self.model.currentFrame = Usd.TimeCode(value)
        if playback:
            self.view.updateForPlayback()
        else:
            self.view.updateView()

    def on_playback_stopped(self):
        self.model.playing = False
        self.view.updateView()

    def on_playback_started(self):
        self.model.playing = True
        self.view.updateForPlayback()

    def keyPressEvent(self, event):
        # Implement some shortcuts for the widget
        # todo: move this code

        key = event.key()
        # TODO: Add CTRL + R for "quick render or playblast"
        if key == QtCore.Qt.Key_Space:
            self.timeline.toggle_play()
        elif key == QtCore.Qt.Key_F:
            # Reframe the objects
            self.view.updateView(resetCam=True,
                                 forceComputeBBox=True)
        elif key == QtCore.Qt.Key_R:
            # Reframe the objects
            self.refresh()
