import logging
from functools import partial

from qtpy import QtWidgets, QtCore, QtGui

from pxr import Usd, UsdGeom, Tf
from pxr.Usdviewq.stageView import StageView
from pxr.Usdviewq import common
from pxr.UsdAppUtils.complexityArgs import RefinementComplexities

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

    The timeline plays through time using QTimer and will try to match the FPS
    based on time spent between each frame.

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
        # TODO: Allow this to be user customizable
        self.play_every_frame = False

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
        self._timer.timeout.connect(self._advance_frame_for_playback)
        self.set_fps(24)  # default stage fps
        self._elapsed_timer = QtCore.QElapsedTimer()

        self.playButton.clicked.connect(self.toggle_play)
        self.slider.valueChanged.connect(self.frame.setValue)
        self.frame.valueChanged.connect(self._frame_changed)
        self.start.valueChanged.connect(self.slider.setMinimum)
        self.end.valueChanged.connect(self.slider.setMaximum)

    def set_fps(self, fps):
        """Set FPS for the timeline to play at"""
        self._timer.setInterval(1000 / float(fps))

    def set_start_timecode(self, start: float):
        """Set start timecode (usually the frame) for the timeline"""
        self.start.setValue(start)

    def set_end_timecode(self, end: float):
        """Set end timecode (usually the frame) for the timeline"""
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
            self._elapsed_timer.restart()
            self.playbackStarted.emit()

            # Set focus to the slider as it helps
            # key shortcuts to be registered on
            # the widgets we actually want it.
            self.slider.setFocus()

        else:
            self._timer.stop()
            self._elapsed_timer.invalidate()
            self.playbackStopped.emit()

    def toggle_play(self):
        # Toggle play state
        self.playing = not self.playing

    def _advance_frame_for_playback(self):

        # This should actually make sure that the playback speed
        # matches the FPS of the scene. Currently it will advance
        # as fast as possible. As such a very light scene will run
        # super fast. See `_advanceFrameForPlayback` in USD view
        # on how they manage the playback speed. That code is in:
        # pxr/usdImaging/lib/usdviewq/appController.py
        if not self.play_every_frame and self._elapsed_timer.isValid():
            elapsed = self._elapsed_timer.restart()
            advance_frames = elapsed // self._timer.interval()
            if advance_frames == 0:
                advance_frames = 1  # ensure always a frame is advanced
        else:
            advance_frames = 1

        if advance_frames > 1:
            # The rendering couldn't keep up with the FPS and thus we are
            # skipping frames now
            log.debug("Advanced more than one frame: %s", advance_frames)

        frame = self.frame.value()
        frame += advance_frames
        # Loop around
        if frame >= self.slider.maximum():
            # The time taken for the frame overshoots the end frame.
            # For very short frame ranges it might overshoot it again if FPS
            # is low so taking into account time spent and how much it
            # overshoots we should fine the new frame number.
            start_frame = self.slider.minimum()
            end_frame = self.slider.maximum()
            frame_range = end_frame - start_frame
            frame_in_range = frame - start_frame
            new_frame_in_range = frame_in_range % frame_range
            new_frame_in_range += start_frame
            frame = new_frame_in_range

        self.slider.setValue(frame)

    def _frame_changed(self, frame):
        """Callback on current frame value change in the timeline.

        Emits the `frameChanged` signal with frame number and whether it's
        currently playing the timeline.
        """

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
    """USD Viewer widge containing a view with a playable timeline."""

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
            self.set_stage(stage)

        # Set focus to the widget itself so that it's not the start
        # frame text edit that takes focus
        self.setFocus()

    def refresh(self):
        log.debug("Refresh viewer")
        self.view.recomputeBBox()
        self.view.updateGL()
        self.view.updateView()

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
            action = shading_menu.addAction(mode)
            action.setCheckable(True)
            action.setChecked(self.model.viewSettings.renderMode == mode)
            group.addAction(action)
        group.triggered.connect(set_rendermode)

        # Complexity
        complexity_menu = menu.addMenu("Complexity")
        current_complexity_name = self.model.viewSettings.complexity.name
        for complexity in RefinementComplexities.ordered():
            action = complexity_menu.addAction(complexity.name)
            action.setCheckable(True)
            action.setChecked(complexity.name == current_complexity_name)
            def set_complexity(complexity):
                self.model.viewSettings.complexity = complexity

            action.triggered.connect(partial(set_complexity, complexity))
        # TODO: Set view settings

        purpose_menu = menu.addMenu("Display Purpose")
        for purpose in ["Guide", "Proxy", "Render"]:
            key = f"display{purpose}"
            action = purpose_menu.addAction(purpose)
            action.setCheckable(True)
            action.setChecked(getattr(self.model.viewSettings, key))
            action.toggled.connect(
                partial(setattr, self.model.viewSettings, key)
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
        current_camera_prim = self.model.viewSettings.cameraPrim
        free_cam = camera_menu.addAction("<Free camera>")
        free_cam.setCheckable(True)
        free_cam.setChecked(not current_camera_prim)
        free_cam.triggered.connect(self.view.switchToFreeCamera)
        for cam in cameras:
            cam_path = str(cam.GetPath())

            action = QtGui.QAction(cam_path, camera_menu)
            action.setCheckable(True)
            action.setChecked(current_camera_prim == cam)
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
        current_aov = self.view.rendererAovName
        for aov in self.view.GetRendererAovs():
            action = aov_menu.addAction(aov)
            action.setCheckable(True)
            action.setChecked(aov == current_aov)
            action.triggered.connect(partial(self.view.SetRendererAov, aov))
        if not aov_menu.actions():
            aov_menu.setEnabled(False)

        menu.exec_(self.view.mapToGlobal(point))

    def set_camera(self, prim: Usd.Prim):
        """Set the current active camera"""
        self.model.viewSettings.cameraPrim = prim

    def set_preview_colors(self, prim, color, alpha):
        # refs:
        # https://graphics.pixar.com/usd/docs/Simple-Shading-in-USD.html
        # https://graphics.pixar.com/usd/docs/UsdPreviewSurface-Proposal.html
        pass

    def set_stage(self, stage: Usd.Stage):
        self.model.stage = stage

        # Set the model to the earliest time so that for animated meshes
        # like Alembic it will be able to display the geometry
        # see: https://github.com/PixarAnimationStudios/USD/issues/1022
        earliest = Usd.TimeCode.EarliestTime()
        self.model.currentFrame = Usd.TimeCode(earliest)

        # TODO: Add listener to redraw on any stage content changes so it
        #   updates the view accordingly (maybe with a slight scheduled delay
        #   to avoid a lot of redrawing if changes were made outside of
        #   `Sdf.ChangeBlock` code? We don't care too much about being instant
        #   on the redraw

        # Show/hide the timeline and set it to frame range of the
        # animation if the loaded stage has an authored time code.
        # TODO: Update this on stage event changes to detect when to hide/show?
        has_animation = stage.HasAuthoredTimeCodeRange()
        self.timeline.setVisible(has_animation)
        if has_animation:
            self.timeline.set_start_timecode(stage.GetStartTimeCode())
            self.timeline.set_end_timecode(stage.GetEndTimeCode())
            self.timeline.set_fps(stage.GetTimeCodesPerSecond())

        # TODO: If the scene contains lights then disable default camera light
        #   and default dome light so the scene is accurately lit with what
        #   is in the USD file only

    def _stop_renderer(self):
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

    # region Qt methods
    def hideEvent(self, event):
        # Make sure to stop the rendering whenever the view gets hidden
        # This also ensures it stops the renderer whenever a UI is closed
        # that contains the widget
        # When the UI is shown again the StageView will automatically
        # set up a renderer again to restart rendering.
        # TODO: Preferably we can detect the difference between close and hide
        #  so that we perform a full 'close renderer' call only when closed,
        #  but as a widget used in another UI the `closeEvent` for the widget
        #  does not get called.
        self._stop_renderer()
        super(Widget, self).hideEvent(event)

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
    # endregion
