# Dialog functions and wrappers to do with the rendering API.

import os
import re
from typing import Any
from functools import partial

from qtpy import QtWidgets, QtCore
from pxr import Usd
from pxr.Usdviewq.stageView import StageView

from . import playblast
from ..resources import get_icon


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
    file.replace("#", "")
    file += "#" * padding

    return os.path.join(base, file + extension)


def prompt_output_path(caption="Save frame"):
    """Prompt for render filename, ensure frame hashes are present in path"""
    filename, _ = QtWidgets.QFileDialog.getSaveFileName(
        caption=caption,
        filter="PNG (*.png);;JPEG (*.jpg, *.jpeg)"
    )

    # ensure there's at least two or more hashes, if not, put in 4.
    REGEX_HASH = r"(#{2,})"

    hash_match = re.match(REGEX_HASH, filename)
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
    

class PlayblastDialog(QtWidgets.QDialog):
    def __init__(self, parent: QtCore.QObject) -> Any:
        super(PlayblastDialog,self).__init__(parent=parent)
        self.setWindowTitle("USD Playblast")

        self.setStyleSheet("QToolButton::menu-indicator {"
                           "width: 0px;"
                           "}")

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

        self.btn_playblast = QtWidgets.QPushButton()
        self.btn_playblast.setText("Playblast!")

        self.hlayout = QtWidgets.QFormLayout()
        self.hlayout.setHorizontalSpacing(200)

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

        resolution_horlayout = QtWidgets.QHBoxLayout()
        resolution_horlayout.addWidget(self.spinbox_horresolution)
        resolution_horlayout.addWidget(self.spinbox_verresolution)
        resolution_horlayout.addWidget(self.btn_resolution)
        self.hlayout.addRow("Resolution", resolution_horlayout)


        # Renderer Combobox
        cbox_renderer = QtWidgets.QComboBox()
        cbox_renderer.addItems(playblast.iter_renderplugin_names())
        cbox_renderer.setCurrentIndex(0)
        self.hlayout.addRow("Test",cbox_renderer)
        

        self.vlayout.addLayout(self.hlayout)
        self.vlayout.addWidget(self.btn_playblast)

    def _update_resolution(self, res_tuple: tuple[int,int]):
        self.spinbox_horresolution.setValue(res_tuple[0])
        self.spinbox_verresolution.setValue(res_tuple[1])