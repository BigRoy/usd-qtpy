# USD-QtPy ![PyPI - Version](https://img.shields.io/pypi/v/usd-qtpy)


Python Qt components for building custom USD tools.


#### How to use?

The Qt components can be embedded in your own Qt interfaces and usually have
a `stage` entrypoint that you should pass a `pxr.Usd.Stage` instance.

However, a simple example Editor UI is also available to run standalone.

![USD Editor](/assets/images/editor_screenshot.png "USD Editor")

If you have the `usd_qtpy` package you can for example run it like:

```
python -m usd_qtpy "/path/to/file.usd"
```

Want to try it within your running Python session it should be as trivial to
do: 

```python
from pxr import Usd
from qtpy import QtWidgets
from usd_qtpy.editor import EditorWindow

filepath = "/path/to/file.usd"
stage = Usd.Stage.Open(filepath)

app = QtWidgets.QApplication()
dialog = EditorWindow(stage=stage)
dialog.resize(600, 600)
dialog.show()
app.exec_()
```

Or if you have a running `QApplication` instance (e.g. when inside Maya):

```python
from pxr import Usd
from usd_qtpy.editor import EditorWindow

filepath = "/path/to/file.usd"
stage = Usd.Stage.Open(filepath)

dialog = EditorWindow(stage=stage)
dialog.resize(600, 600)
dialog.show()
```

#### Why not Luma Picture's `usd-qt`?

Unlike [Luma Pictures's  `usd-qt`](https://github.com/LumaPictures/usd-qt) this repository tries to be easily 
redistributable by avoiding the need for extra C++ dependencies and solely
use the USD Python API. This will keep the build matrix simpler but does mean
the repository is not - by design - built for highly optimized large scale 
applications. Nonetheless, the intent is still to be able to carry average VFX 
scenes for debugging.



## install 
### from pip
```
python -m pip install usd-qtpy
```
### from repo
```
python -m pip install git+https://github.com/BigRoy/usd-qtpy.git@main
```


## Dependencies

The Viewer utilities are basically using `usdviewq` which may or may not
be included in your build. This also requires `PyOpenGL`. However, the other
tools do not and are intended to rely solely on USD core and Qt itself.

- qtpy 
- usd-core (when not using your own usd builds, install with `[usd]`)
- PyOpenGL (needed for usd viewport, install with `[usdview]`; you will still need use a custom `usd` build yourself for `pxr.Usdviewq` dependency)
