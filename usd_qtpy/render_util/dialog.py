# Dialog functions and wrappers to do with the rendering API.

import os
import re
from functools import partial
from contextlib import ExitStack

from qtpy import QtWidgets, QtCore
from pxr import Usd, UsdGeom, Sdf
from pxr.Usdviewq.stageView import StageView

from . import playblast, framing_camera, turntable
from .base import (RenderReportable,
                   TempStageOpen,
                   get_tempfolder,
                   using_tempfolder, 
                   defer_primpath_deletion,
                   defer_file_deletion)
from ..resources import get_icon


REGEX_HASH = re.compile(r"(#{2,})")
REGEX_FRAMENUM = re.compile(r"(\d+)")


def _rectify_path_framenumberspec(path: str, padding: int =  4):
    """Ensure a placeholder for framenumbers exists in the path.

    >>> _rectify_path_framenumberspec("filename##.png")
    "filename####.png"
    >>> _rectify_path_framenumberspec("filename###.png")
    "filename####.png"

    Returns:
        str: The path with an ensured frame number hash.

    """
    base, file = os.path.split(path)
    file, extension = os.path.splitext(file)
    # if too little hashes were present, remove them.
    file = file.replace("#", "")
    file += "#" * padding

    return os.path.join(base, file + extension)


def _path_sequence_to_framenumberspec(path: str):
    """ get the last found element of a filename that is a sequence of numbers,
     and modify them to hashes (#) """

    framenum_match = list(REGEX_FRAMENUM.finditer(path))

    if framenum_match:
        last_match = framenum_match[-1]
        start, end = last_match.span()
        hash_padding = len(last_match.group(0))
        path = f"{path[:start]}{hash_padding * '#'}{path[end:]}"

    return path


def prompt_input_path(caption: str="Load item", folder: str = None) -> str:
    
    filename, _ = QtWidgets.QFileDialog.getOpenFileName(
        caption=caption,
        filter="USD (*.usd *.usda *.usdc)",
        directory=folder
    )
    return filename


def prompt_output_path(caption="Save frame", folder: str = None):
    """Prompt for render filename, ensure frame hashes are present in path"""
    filename, _ = QtWidgets.QFileDialog.getSaveFileName(
        caption=caption,
        filter="PNG (*.png);;JPEG (*.jpg, *.jpeg)",
        directory=folder
    )

    # Attempt to replace last occurring sequence of numbers
    # in filename with hashes
    filename = _path_sequence_to_framenumberspec(filename)

    # ensure there's at least two or more hashes, if not, put in 4.
    hash_match = REGEX_HASH.search(filename)
    if not hash_match:
        filename = _rectify_path_framenumberspec(filename)

    return filename


def _savepicture_dialog(stage: Usd.Stage,
                        stageview: StageView, 
                        width: int = 16, 
                        height: int = 9):
    """
    Save a simple snap of the scene to a given folder.
    """

    filename = prompt_output_path()

    camera = playblast.camera_from_stageview(stage, stageview, "viewerCamera")
    
    # ensure camera aspect ratio
    # Aperture size (24) is based on the size of a full frame SLR camera sensor
    # https://en.wikipedia.org/wiki/Image_sensor_format#Common_image_sensor_formats
    aspect_ratio: float = width / float(height)
    camera.CreateHorizontalApertureAttr(24 * aspect_ratio)
    camera.CreateHorizontalApertureOffsetAttr(0)
    camera.CreateVerticalApertureAttr(24)
    camera.CreateVerticalApertureOffsetAttr(0)

    frame_timecode: Usd.TimeCode = stageview._dataModel.currentFrame
    
    # cannot be earliest timecode when passing as argument.
    if frame_timecode == Usd.TimeCode.EarliestTime():
        frame_timecode = None

    frame = 0 if frame_timecode is None else frame_timecode.GetValue()

    playblast.render_playblast(stage,
                               filename,
                               frames=f"{frame}",
                               width=1920,
                               camera=camera)

    stage.RemovePrim(camera.GetPath())


class PlayblastDialog(QtWidgets.QDialog, RenderReportable):
    def __init__(self, parent: QtCore.QObject, stage: Usd.Stage, stageview: StageView = None):
        super(PlayblastDialog,self).__init__(parent=parent)
        self.setWindowTitle("USD Playblast")

        self.setStyleSheet("QToolButton::menu-indicator {              " 
                                                       "    width: 0px;"
                                                       "}              ")
        self._parent = parent
        self._stage = stage
        self._stageview = stageview
        self._has_viewer = "Scene Viewer" in parent._panels

        self.total_frames.connect(self._set_total_frames)
        self.render_progress.connect(self._set_render_progress)

        width, height, margin = 600, 800, 15
        geometry = QtCore.QRect(margin, margin, 
                                width - margin * 2, height - margin * 2)

        self.resize(QtCore.QSize(width,height))

        self._container = QtWidgets.QGroupBox(self)
        self._container.setTitle("Playblast settings...")
        self._container.setGeometry(geometry)

        self.vlayout = QtWidgets.QVBoxLayout()
        self.vlayout.addSpacing(30) # add some spacing from the top
        self._container.setLayout(self.vlayout)

        self.formlayout = QtWidgets.QFormLayout()
        self.formlayout.setHorizontalSpacing(50)

        # UI pre hook
        self.ui_pre_hook(self.vlayout)

        # File name browser
        lbl_filedest = QtWidgets.QLabel(self)
        lbl_filedest.setText("Path to save render to...")
        lbl_filedest.setFixedHeight(30)
        self.vlayout.addWidget(lbl_filedest)

        self.txt_filename = QtWidgets.QLineEdit()
        self.txt_filename.setPlaceholderText("Path to render...")
        self.btn_browse = QtWidgets.QPushButton(icon=get_icon("folder"))
        self.btn_browse.setFixedSize(QtCore.QSize(30, 30))

        self.btn_browse.clicked.connect(self._prompt_renderoutput)

        filename_hlayout = QtWidgets.QHBoxLayout()
        filename_hlayout.addWidget(self.txt_filename)
        filename_hlayout.addWidget(self.btn_browse)
        self.vlayout.addLayout(filename_hlayout)

        self.vlayout.addSpacing(15)

        # Frame range
        self.frame_range_callback(self.formlayout)

        separator_1 = QtWidgets.QFrame()
        separator_1.setFrameShape(QtWidgets.QFrame.HLine)
        self.formlayout.addWidget(separator_1)

        # Resolution
        self.spinbox_horresolution = QtWidgets.QSpinBox()
        self.spinbox_verresolution = QtWidgets.QSpinBox()
        self.spinbox_horresolution.setMaximum(4096)
        self.spinbox_horresolution.setMinimum(1)
        self.spinbox_verresolution.setMaximum(4096)
        self.spinbox_verresolution.setMinimum(1)
        self.spinbox_horresolution.setValue(1920)
        self.spinbox_verresolution.setValue(1080)
        
        self.btn_resolution = QtWidgets.QToolButton(icon=get_icon("chevron-down"))
        self.btn_resolution.clicked.connect(self.btn_resolution.showMenu)
        self.btn_resolution.setFixedSize(QtCore.QSize(30, 30))

        self.btn_resolution_menu = QtWidgets.QMenu(self)
        resolution_presets = {"SD 480p"   : (640, 480),
                              "HD 720p"   : (1280, 720),
                              "HD 1080p"  : (1920, 1080),
                              "UHD 4K"    : (3840, 2160),
                              "1k Square" : (1024, 1024),
                              "2k Square" : (2048, 2048),
                              "4k Square" : (4096, 4096)
                              }

        for label, res_tuple in resolution_presets.items():
            action = self.btn_resolution_menu.addAction(label)
            action.triggered.connect(partial(self._update_resolution, res_tuple))
            action.setData(res_tuple)

        self.btn_resolution.setMenu(self.btn_resolution_menu)

        resolution_hlayout = QtWidgets.QHBoxLayout()
        resolution_hlayout.addWidget(self.spinbox_horresolution)
        resolution_hlayout.addWidget(self.spinbox_verresolution)
        resolution_hlayout.addWidget(self.btn_resolution)
        self.formlayout.addRow("Resolution", resolution_hlayout)

        # Camera selection
        self.cbox_camera = QtWidgets.QComboBox()
        self.populate_camera_combobox(self.cbox_camera)

        self.cbox_camera.setCurrentIndex(0)
        self.formlayout.addRow("Camera",self.cbox_camera)

        self.spinbox_fit = QtWidgets.QDoubleSpinBox()
        self.spinbox_fit.setMinimum(0.01)
        self.spinbox_fit.setMaximum(10)
        self.spinbox_fit.setValue(1.2)
        self.cbox_camera.currentIndexChanged.connect(self._update_fit)
        self.lbl_fit = QtWidgets.QLabel()
        self.lbl_fit.setText("Fit stage:")

        self.formlayout.addRow(self.lbl_fit,self.spinbox_fit)

        separator_2 = QtWidgets.QFrame()
        separator_2.setFrameShape(QtWidgets.QFrame.HLine)
        self.formlayout.addWidget(separator_2)

        # Purposes
        self.chk_purpose_default = QtWidgets.QCheckBox()
        self.chk_purpose_render = QtWidgets.QCheckBox()
        self.chk_purpose_proxy = QtWidgets.QCheckBox()
        self.chk_purpose_guide = QtWidgets.QCheckBox()

        self.chk_purpose_default.setText("Default")
        self.chk_purpose_render.setText("Render")
        self.chk_purpose_proxy.setText("Proxy")
        self.chk_purpose_guide.setText("Guide")

        self.chk_purpose_default.setChecked(True)
        self.chk_purpose_render.setChecked(True)
        self.chk_purpose_proxy.setChecked(True)
        self.chk_purpose_guide.setChecked(False)

        purpose_vlayout = QtWidgets.QVBoxLayout()
        purpose_vlayout.addWidget(self.chk_purpose_default)
        purpose_vlayout.addWidget(self.chk_purpose_render)
        purpose_vlayout.addWidget(self.chk_purpose_proxy)
        purpose_vlayout.addWidget(self.chk_purpose_guide)

        self.formlayout.addRow("Included purposes:",purpose_vlayout)

        # Complexity combobox
        self.cbox_complexity = QtWidgets.QComboBox()
        self.cbox_complexity.addItems(playblast.get_complexity_levels())
        self.cbox_complexity.setCurrentIndex(2)
        self.formlayout.addRow("Complexity / Quality",self.cbox_complexity)

        # Renderer Combobox
        self.cbox_renderer = QtWidgets.QComboBox()
        self.cbox_renderer.addItems(playblast.iter_renderplugin_names())
        self.cbox_renderer.setCurrentIndex(0)
        self.formlayout.addRow("Renderer",self.cbox_renderer)
        
        self.vlayout.addLayout(self.formlayout)

        # Ui post hook
        self.ui_post_hook(self.vlayout)

        self.vlayout.addStretch()

        # Playblast button

        self.btn_playblast = QtWidgets.QPushButton()
        self.btn_playblast.setText("Playblast!")
        self.vlayout.addWidget(self.btn_playblast)

        self.btn_playblast.clicked.connect(self.playblast_callback)

        # Progress bar
        self.progressbar = QtWidgets.QProgressBar(self)
        self.progressbar.setFormat("Not started...")
        self.vlayout.addWidget(self.progressbar)

    def _update_fit(self):
        if "New: Framing Camera" in self.cbox_camera.currentText():
            self.spinbox_fit.setDisabled(False)
            self.lbl_fit.setDisabled(False)
        else:
            self.spinbox_fit.setDisabled(True)
            self.lbl_fit.setDisabled(True)

    def _update_resolution(self, res_tuple: tuple[int,int]):
        self.spinbox_horresolution.setValue(res_tuple[0])
        self.spinbox_verresolution.setValue(res_tuple[1])

    def _update_framerange_options(self):
        index = self.cbox_framerange_options.currentIndex()
        if index == 0:
            self.spinbox_frame_start.setDisabled(False)
            self.spinbox_frame_end.setDisabled(True)
            self.spinbox_frame_stride.setDisabled(True)
        elif index == 1:
            self.spinbox_frame_start.setDisabled(False)
            self.spinbox_frame_end.setDisabled(False)
            self.spinbox_frame_stride.setDisabled(False)
        elif index == 2:
            self.spinbox_frame_start.setDisabled(True)
            self.spinbox_frame_end.setDisabled(True)
            self.spinbox_frame_stride.setDisabled(True)

    def _prompt_renderoutput(self):
        filename = prompt_output_path("Render result to...",
                                      os.path.dirname(self.txt_filename.text()))
        if filename:
            self.txt_filename.setText(os.path.normpath(filename))

    def _gather_purposes(self) -> list[str]:
        purposes = []
        
        if self.chk_purpose_default.isChecked():
            purposes.append("default")
        
        if self.chk_purpose_render.isChecked():
            purposes.append("render")

        if self.chk_purpose_proxy.isChecked():
            purposes.append("proxy")

        if self.chk_purpose_guide.isChecked():
            purposes.append("guide")
        
        return purposes

    def _set_total_frames(self, frames: int):
        """
        Update progress bar with reported maximum frames
        """
        self.progressbar.setFormat(f"Rendering %v / {frames} frames...")
        self.progressbar.setMinimum(1)
        self.progressbar.setMaximum(frames)
    
    def _set_render_progress(self, frame: int):
        """
        Increment progress bar with reported rendered frames.
        """
        self.progressbar.setValue(frame)

    def _construct_frames_argument(self) -> str:
        start = self.spinbox_frame_start.value()
        end = self.spinbox_frame_end.value()
        stride = self.spinbox_frame_stride.value()

        opt_index = self.cbox_framerange_options.currentIndex()

        if opt_index == 0: # Single Frame
            return f"{start}"
        elif opt_index == 1: # Frame range
            return playblast.get_frames_string(start,end,stride)  
        elif opt_index == 2: # Frame from Viewer
            if self._stageview:
                return playblast.get_stageview_frame(self._stageview)      

    def _get_camera(self) -> tuple[UsdGeom.Camera,bool]:
        """
        Returns a camera and whether it should be destroyed afterwards.
        -> UsdGeom.Camera, should_destroy()
        """

        box_text = self.cbox_camera.currentText()
        data = self.cbox_camera.currentData()

        width = self.spinbox_horresolution.value()
        height = self.spinbox_verresolution.value()

        aspect_ratio: float = float(width) / float(height)

        if data is not None:
            data = UsdGeom.Camera(data)
            v_aperture = data.GetVerticalApertureAttr()
            # ensure that camera can render desired aspect ratio.
            if not v_aperture.IsValid():
                v_aperture = 24
            else:
                v_aperture = v_aperture.Get(0)

            data.CreateHorizontalApertureAttr(v_aperture * aspect_ratio)
            data.CreateHorizontalApertureOffsetAttr(0)
            data.CreateVerticalApertureAttr(v_aperture)
            data.CreateVerticalApertureOffsetAttr(0)

            # Camera is in scene, doesn't need to be deleted.
            return data, False

        elif "New: Framing Camera" in box_text:
            camera = framing_camera.create_framing_camera_in_stage(
                self._stage,
                name="Playblast_framingCam",
                fit=self.spinbox_fit.value(),
                width=width,
                height=height
                )
            return camera, True
        elif "New: Camera from View" in box_text:
            camera = playblast.camera_from_stageview(self._stage, self._stageview, "Playblast_viewerCam")
            # ensure camera aspect ratio
            # Aperture size (24) is based on the size of a full frame SLR camera sensor
            # https://en.wikipedia.org/wiki/Image_sensor_format#Common_image_sensor_formats
            aspect_ratio: float = width / float(height)
            camera.CreateHorizontalApertureAttr(24 * aspect_ratio)
            camera.CreateHorizontalApertureOffsetAttr(0)
            camera.CreateVerticalApertureAttr(24)
            camera.CreateVerticalApertureOffsetAttr(0)
            return camera, True
        
        return None, False
    
    class _CameraContext:
        def __init__(self, parent):
            self._camera: UsdGeom.Camera
            self._camera, self._delete = parent._get_camera()
            self._parent = parent

        def __enter__(self) -> UsdGeom.Camera:
            return self._camera
        
        def __exit__(self, *args):
            if self._delete:
                self._parent._stage.RemovePrim(self._camera.GetPath())


    def playblast_callback(self):
        frames = self._construct_frames_argument()
        with self._CameraContext(self) as camera:
            path = self.txt_filename.text()

            if not path:
                return

            width = self.spinbox_horresolution.value()
            complexity = self.cbox_complexity.currentText()
            render_engine = self.cbox_renderer.currentText()
            purposes = self._gather_purposes()

            playblast.render_playblast(stage=self._stage,
                                       outputpath=path,
                                       frames=frames,
                                       width=width,
                                       camera=camera,
                                       complexity=complexity,
                                       renderer=render_engine,
                                       colormode="sRGB",
                                       purposes=purposes,
                                       qt_report_instance=self
                                       )

            self.progressbar.setFormat("Rendered %v frames!")

    def frame_range_callback(self, formlayout: QtWidgets.QFormLayout):
        """
        Override this hook to change frame range widget
        """
        self.cbox_framerange_options = QtWidgets.QComboBox()
        self.cbox_framerange_options.addItems(("Single frame", "Frame range"))

        if self._has_viewer:
            self.cbox_framerange_options.addItem("Frame from view")
        
        self.cbox_framerange_options.setCurrentIndex(0)

        self.formlayout.addRow("Frame range options",self.cbox_framerange_options)

        self.spinbox_frame_start = QtWidgets.QSpinBox()
        self.spinbox_frame_end = QtWidgets.QSpinBox()
        self.spinbox_frame_stride = QtWidgets.QDoubleSpinBox()

        self.spinbox_frame_start.setMinimum(-9999)
        self.spinbox_frame_start.setMaximum(9999)
        self.spinbox_frame_end.setMinimum(-9999)
        self.spinbox_frame_end.setMaximum(9999)

        self.spinbox_frame_start.setValue(0)
        self.spinbox_frame_end.setValue(100)
        self.spinbox_frame_stride.setValue(1)
        
        self.cbox_framerange_options.currentIndexChanged.connect(self._update_framerange_options)
        self._update_framerange_options()

        framerange_hlayout = QtWidgets.QHBoxLayout()
        framerange_hlayout.addWidget(self.spinbox_frame_start)
        framerange_hlayout.addWidget(self.spinbox_frame_end)
        framerange_hlayout.addWidget(self.spinbox_frame_stride)
        formlayout.addRow("Frame Start / End / Stride", framerange_hlayout)

    def populate_camera_combobox(self, cbox_camera: QtWidgets.QComboBox):
        """
        Override hook to populate camera choices.
        """
        
        for cam in playblast.iter_stage_cameras(self._stage):
            cam: UsdGeom.Camera
            cam_name = os.path.basename(cam.GetPath().pathString)
            cbox_camera.addItem(f"Cam: {cam_name}", cam)
        
        cbox_camera.addItem("New: Framing Camera")
        if self._has_viewer:
            cbox_camera.addItem("New: Camera from View")

        cbox_camera.setCurrentIndex(0)

    def ui_pre_hook(self, vlayout: QtWidgets.QVBoxLayout):
        """
        Override hook to insert QtWidgets BEFORE the main playblast interface.
        """
        pass
        # Example: add some text
        # txt = QtWidgets.QLabel()
        # txt.setText("I go before the interface!")
        # txt.setFixedHeight(30)
        # vlayout.addWidget(txt)

    def ui_post_hook(self, vlayout: QtWidgets.QVBoxLayout):
        """
        Override hook to insert QtWidgets after the main playblast interface,
        but before the playblast button.
        """
        pass
        # Example: add some text
        # txt = QtWidgets.QLabel()
        # txt.setText("I go after the interface!")
        # txt.setFixedHeight(30)
        # vlayout.addWidget(txt)


class TurntableDialog(PlayblastDialog):
    def __init__(self, parent: QtCore.QObject, 
                 stage: Usd.Stage, 
                 stageview: StageView = None):
        self._turntablefile = R"./assets/turntable/turntable_preset.usda"
        
        super(TurntableDialog,self).__init__(parent,stage,stageview)
        self.setWindowTitle("USD Turntable Playblast")

        repopulate_cam = partial(self.populate_camera_combobox,self.cbox_camera)
        self.cbox_turntable_type.currentIndexChanged.connect(
            repopulate_cam
            )

        # if turntable filename loses focus, attempt to repopulate camera field.
        self.txt_turntable_filename.editingFinished.connect(repopulate_cam)
        self.btn_playblast.setText("Playblast Turntable!")

    def _prompt_turntablefile(self):
        filename = prompt_input_path(
            "Get Turntable from...",
            os.path.dirname(self._turntablefile)
        )
        if filename:
            self.txt_turntable_filename.setText(os.path.normpath(filename))
            self.populate_camera_combobox(self.cbox_camera)

    def populate_camera_combobox(self, 
                                 cbox_camera: QtWidgets.QComboBox, 
                                 index: int = None):
        """
        (re)populate camera box when it's needed.
        Catches a signal argument in index.
        """
        if index is None or not isinstance(index, int):
            index = self.cbox_turntable_type.currentIndex()

        if index == 2:
            cbox_camera.clear()
            cbox_camera.setDisabled(False)
            self.btn_playblast.setDisabled(False)
            
            self._turntablefile = self.txt_turntable_filename.text()
            
            if not self._turntablefile:
                self._turntablefile = R"./assets/turntable/turntable_preset.usda"

            if os.path.isfile(self._turntablefile):
                cams = playblast.get_file_cameras(self._turntablefile)
                cams_string = (str(c.pathString)\
                        .replace("turntable", "turntable_reference") 
                        for c in cams)
                cams = [Sdf.Path(c) for c in cams_string]
                
                if not cams:
                    # No camera, disable
                    cbox_camera.addItem("No camera found...")
                    cbox_camera.setDisabled(True)
                    self.btn_playblast.setDisabled(True)
                else:
                    for cam in cams:
                        cam_name = os.path.basename(cam.pathString)
                        # store path + string in camera combobox
                        cbox_camera.addItem(f"Cam: {cam_name}",cam)
            else:
                # No camera, disable
                cbox_camera.addItem("Turntable file not valid")
                cbox_camera.setDisabled(True)
                self.btn_playblast.setDisabled(True)
        else:
            cbox_camera.clear()
            cbox_camera.setDisabled(False)
            for cam in playblast.iter_stage_cameras(self._stage):
                cam: UsdGeom.Camera
                campath = cam.GetPath().pathString
                cam_name = os.path.basename(campath)
                cbox_camera.addItem(f"Cam: {cam_name}", Sdf.Path(campath))

            cbox_camera.addItem("New: Framing Camera")
            if self._has_viewer:
                cbox_camera.addItem("New: Camera from View")
            # cbox_camera.setDisabled(True)

        cbox_camera.setCurrentIndex(0)
        self.update_textfield_turntablefile(index)

    def update_textfield_turntablefile(self, index: int = 0):
        if index == 2:
            self.txt_turntable_filename.setDisabled(False)
            self.btn_browse_turntable.setDisabled(False)
            self.lbl_turntable_file.setDisabled(False)
        else:
            self.txt_turntable_filename.setDisabled(True)
            self.btn_browse_turntable.setDisabled(True)
            self.lbl_turntable_file.setDisabled(True)

    def frame_range_callback(self, formlayout: QtWidgets.QFormLayout):
        """
        Frame range is a different story for turntables.
        It's defined by a starting frame, and a length
        """
        
        self.spinbox_frame_start = QtWidgets.QSpinBox()
        self.spinbox_frame_length = QtWidgets.QSpinBox()

        self.spinbox_frame_start.setMinimum(-9999)
        self.spinbox_frame_start.setMaximum(9999)
        self.spinbox_frame_length.setMinimum(1)
        self.spinbox_frame_length.setMaximum(9999)

        self.spinbox_frame_start.setValue(1)
        self.spinbox_frame_length.setValue(100)

        framerange_hlayout = QtWidgets.QHBoxLayout()
        framerange_hlayout.addWidget(self.spinbox_frame_start)
        framerange_hlayout.addWidget(self.spinbox_frame_length)

        formlayout.addRow("Starting Frame / Length", framerange_hlayout)

        self.spinbox_loops = QtWidgets.QSpinBox()
        self.spinbox_loops.setMinimum(1)
        self.spinbox_loops.setMaximum(99)
        formlayout.addRow("Repetitions", self.spinbox_loops)

    def ui_pre_hook(self, vlayout: QtWidgets.QVBoxLayout):
                
        pre_form = QtWidgets.QFormLayout()
        pre_form.setHorizontalSpacing(150)

        # Turntable type chooser
        self.cbox_turntable_type = QtWidgets.QComboBox()
        turntable_types = ("Rotate camera",
                           "Rotate subject",
                           "Preset from file")
        self.cbox_turntable_type.addItems(turntable_types)
        pre_form.addRow("Turntable Type", self.cbox_turntable_type)
        
        # Turntable file chooser
        self.lbl_turntable_file = QtWidgets.QLabel(self)
        self.lbl_turntable_file.setText("Path to get turntable from...")
        self.lbl_turntable_file.setFixedHeight(30)
        pre_form.addRow(self.lbl_turntable_file)

        self.txt_turntable_filename = QtWidgets.QLineEdit()
        self.txt_turntable_filename.setPlaceholderText("Empty - Use internal preset")
        self.btn_browse_turntable = QtWidgets.QPushButton(icon=get_icon("folder"))
        self.btn_browse_turntable.setFixedSize(QtCore.QSize(30, 30))
        self.btn_browse_turntable.clicked.connect(self._prompt_turntablefile)

        turntable_filename_hlayout = QtWidgets.QHBoxLayout()
        turntable_filename_hlayout.addWidget(self.txt_turntable_filename)
        turntable_filename_hlayout.addWidget(self.btn_browse_turntable)
        pre_form.addRow(turntable_filename_hlayout)

        vlayout.addLayout(pre_form)
        self.vlayout.addSpacing(15)

    def playblast_callback(self):
        """
        Turntable playblast!
        """
        turn_length = self.spinbox_frame_length.value()
        frame_start = self.spinbox_frame_start.value()
        repetition = self.spinbox_loops.value()

        frames_string = turntable.get_turntable_frames_string(
            turn_length,
            frame_start,
            repetition
        )

        fit = self.spinbox_fit.value()
        width = self.spinbox_horresolution.value()
        height = self.spinbox_verresolution.value()

        render_path = self.txt_filename.text()
        render_engine = self.cbox_renderer.currentText()

        ttable_type = self.cbox_turntable_type.currentIndex()
        if ttable_type == 0:
            # Rotate camera around scene

            turntable_xform = turntable\
                              .create_turntable_xform(
                                  self._stage,
                                  "/",
                                  "turntabledialog_xform",
                                  turn_length,
                                  frame_start,
                                  repetition)
            
            path: Sdf.Path = self.cbox_camera.currentData()
            render_camera: UsdGeom.Camera = None
            cam_name = "turntabledialog_cam"
            # get camera state, to create a valid camera
            if path:
                # take new root into account, split off the old scene root.
                # TODO: support animated cameras from scene?
                # grab camera state
                camera_stage = self._stage.GetPrimAtPath(path)
                camera_geom = UsdGeom.Camera(camera_stage)
                camera_state = camera_geom.GetCamera(frame_start)
                render_camera = UsdGeom.Camera.Define(
                    self._stage,
                    f"/turntabledialog_xform/{cam_name}")
            else:
                if "New: Framing Camera" in self.cbox_camera.currentText():
                    render_camera = framing_camera\
                        .create_framing_camera_in_stage(self._stage,
                                                        "/turntabledialog_xform",
                                                        cam_name,
                                                        fit,
                                                        width,
                                                        height
                                                        )
                    
                elif "New: Camera from View" in self.cbox_camera.currentText():
                    cam = playblast.camera_from_stageview(
                                            self._stage,
                                            self._stageview,
                                            f"viewcam")
                    camera_state = cam.GetCamera(frame_start)
                    self._stage.RemovePrim(cam.GetPath())
                    render_camera = UsdGeom.Camera.Define(
                                        self._stage,
                                        f"/turntabledialog_xform/{cam_name}")
                    render_camera.SetFromCamera(camera_state)

            render_camera = framing_camera.camera_conform_sensor_to_aspect(
                                            render_camera,
                                            width,
                                            height)
            with ExitStack() as stack:
                stack.enter_context(defer_primpath_deletion(
                    self._stage, render_camera.GetPath()))
                stack.enter_context(defer_primpath_deletion(
                    self._stage, turntable_xform.GetPath()))
                
                playblast.render_playblast(self._stage,
                                           render_path,
                                           frames=frames_string,
                                           width=width,
                                           camera=render_camera,
                                           renderer=render_engine,
                                           qt_report_instance=self)

            self.progressbar.setFormat("Rendered %v frames!")
        elif ttable_type == 1:
            # Create temporary stage where the entire stage rotates in front 
            # of a camera

            # make temporary folder to cache current subject session to.
            if not os.path.isdir("./temp"):
                os.mkdir("./temp")

            @using_tempfolder
            def routine_rotate_subject():
                tempfolder = get_tempfolder()

                # collect info about subject
                subject_upaxis = framing_camera.get_stage_up(self._stage)

                # export subject
                subject_filename = R"subject.usda"
                subject_filename = os.path.join(tempfolder,subject_filename)
                subject_filename = os.path.abspath(subject_filename)

                self._stage.Export(subject_filename)

                assemble_stage = Usd.Stage.CreateInMemory()
                UsdGeom.SetStageUpAxis(assemble_stage,subject_upaxis)

                bounds = framing_camera.get_stage_boundingbox(self._stage)

                # Put stage in turntable primitive.
                turntable_xform = turntable\
                                  .create_turntable_xform(
                                      assemble_stage,
                                      "/",
                                      "turntabledialog_xform",
                                      turn_length,
                                      frame_start,
                                      repetition,
                                      bounds)
                # reference root in stage
                root_override= assemble_stage\
                                .OverridePrim("/turntabledialog_xform/root")
                root_override.GetReferences().AddReference(subject_filename)

                path: Sdf.Path = self.cbox_camera.currentData()
                camera_state = None

                # get camera states, to create a valid camera in in-memory stage.
                with ExitStack() as stack:
                    if path:
                        # take new root into account, split off the old scene root.
                        # TODO: support animated cameras from scene?
                        # grab camera state
                        camera_stage = self._stage.GetPrimAtPath(path)
                        camera_geom = UsdGeom.Camera(camera_stage)
                        camera_state = camera_geom.GetCamera(frame_start)
                    else:
                        if "New: Framing Camera" in self.cbox_camera.currentText():
                            cam = framing_camera\
                                .create_framing_camera_in_stage(self._stage,
                                                                "/",
                                                                "framingcam",
                                                                fit,
                                                                width,
                                                                height
                                                                )
                            camera_state = cam.GetCamera(frame_start)
                            # immediatly remove here, because we can.
                            self._stage.RemovePrim(cam.GetPath())
                        elif "New: Camera from View" in self.cbox_camera.currentText():
                            cam = playblast.camera_from_stageview(self._stage,
                                                                  self._stageview,
                                                                  "viewcam")
                            camera_state = cam.GetCamera(frame_start)
                            # immediatly remove here, because we can.
                            self._stage.RemovePrim(cam.GetPath())

                    render_camera: UsdGeom.Camera = None
                    render_camera_name = "turntabledialog_cam"

                    # use camera state to generate proper camera in assemble_stage
                    render_camera = UsdGeom.Camera\
                        .Define(assemble_stage,f"/{render_camera_name}")
                    
                    # Defer deletion of render camera defined from data
                    stack.enter_context(
                        defer_primpath_deletion(self._stage, 
                                                render_camera.GetPath()))

                    render_camera.SetFromCamera(camera_state)

                    render_camera = framing_camera.camera_conform_sensor_to_aspect(
                        render_camera,
                        width,
                        height
                    )

                    # We should now have an assembled stage.

                    realstage_filename = R"turntable_assembly.usd"
                    realstage_filename = os.path.join(tempfolder, realstage_filename)
                    realstage_filename = os.path.abspath(realstage_filename)

                    assemble_stage.Export(realstage_filename)

                    del assemble_stage

                    stack.enter_context(defer_file_deletion(subject_filename))
                    stack.enter_context(defer_file_deletion(realstage_filename))

                    real_stage = stack.enter_context(TempStageOpen(realstage_filename))
   
                    real_render_camera = real_stage.GetPrimAtPath(f"/{render_camera_name}")
                    real_render_camera = UsdGeom.Camera(real_render_camera)
                    
                    playblast.render_playblast(real_stage,
                                               render_path,
                                               frames=frames_string,
                                               width=width,
                                               camera=real_render_camera,
                                               renderer=render_engine,
                                               qt_report_instance=self)
                    
                    # Can't go without this, sorry.
                    # All references to the opened stage have to be deleted 
                    # for the file to be free.
                    del real_stage 
            
            routine_rotate_subject() #IIFE ;)

            self.progressbar.setFormat("Rendered %v frames!")

        elif ttable_type == 2:
            camera_path = self.cbox_camera.currentData()
            turntable.turntable_from_file(self._stage,
                                          self._turntablefile,
                                          export_path=render_path,
                                          renderer=render_engine,
                                          length=turn_length,
                                          frame_start=frame_start,
                                          repeats=repetition,
                                          width=width,
                                          height=height,
                                          camera_path=camera_path,
                                          qt_report_instance=self
                                          )
            self.progressbar.setFormat("Rendered %v frames!")
