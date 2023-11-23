# USD-QtPy

Python Qt components for building custom USD tools.

#### Why not Luma Picture's `usd-qt`?

Unlike [Luma Pictures's  `usd-qt`](https://github.com/LumaPictures/usd-qt) this repository tries to be easily 
redistributable by avoiding the need for extra C++ dependencies and solely
use the USD Python API. This will keep the build matrix simpler but does mean
the repository is not - by design - built for highly optimized large scale 
applications. Nonetheless the intent is still to be able to carry average VFX 
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
- usd-core