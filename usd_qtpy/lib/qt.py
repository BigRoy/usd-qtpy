import re
import sys
import logging
from qtpy import QtCore, QtGui, QtWidgets


class SharedObjects:
    jobs = {}


def schedule(func, time, channel="default"):
    """Run `func` at a later `time` in a dedicated `channel`

    Given an arbitrary function, call this function after a given
    timeout. It will ensure that only one "job" is running within
    the given channel at any one time and cancel any currently
    running job if a new job is submitted before the timeout.

    """

    try:
        SharedObjects.jobs[channel].stop()
    except (AttributeError, KeyError, RuntimeError):
        pass

    timer = QtCore.QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(func)
    timer.start(time)

    SharedObjects.jobs[channel] = timer


def iter_model_rows(model, column, include_root=False):
    """Iterate over all row indices in a model"""
    indices = [QtCore.QModelIndex()]  # start iteration at root

    for index in indices:
        # Add children to the iterations
        child_rows = model.rowCount(index)
        for child_row in range(child_rows):
            child_index = model.index(child_row, column, index)
            indices.append(child_index)

        if not include_root and not index.isValid():
            continue

        yield index


def report_error(fn):
    """Decorator that logs any errors raised by the function.

    This can be useful for functions that are connected to e.g. USD's
    `Tf.Notice` registry because those do not output the errors that occur.
    
    """
    def wrap(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            logging.error(exc, exc_info=sys.exc_info())
            raise RuntimeError(f"Error from {fn}") from exc

    return wrap


class DifflibSyntaxHighlighter(QtGui.QSyntaxHighlighter):
    """Simple Syntax highlighter for output from Python's `difflib` module"""

    def __init__(self, parent=None):
        super(DifflibSyntaxHighlighter, self).__init__(parent)

        self._highlight_rules = {}
        rules = {
            r"^-{3} .*$": "#FF8B28",     # file before
            r"^\+{3} .*$": "#FF8B28",    # file after
            r"^[+].*": "#55FF55",        # added line
            r"^-.*": "#FF5555",          # removed line
            r" .*": "#999999",           # unchanged line
            r"^@@ .* @@$": "#0D98BA",    # line number indicator
        }
        for pattern, color in rules.items():
            char_format = QtGui.QTextCharFormat()
            char_format.setForeground(QtGui.QColor(color))
            self._highlight_rules[re.compile(pattern)] = char_format

    def highlightBlock(self, text):

        for regex, char_format in self._highlight_rules.items():
            match = regex.match(text)
            if match:
                # Format the full block
                self.setFormat(0, len(text), char_format)
                return


class DropFilesPushButton(QtWidgets.QPushButton):
    """QPushButton that emits files_dropped signal when dropping files on it"""

    files_dropped = QtCore.Signal(list)

    def __init__(self, *args, **kwargs):
        super(DropFilesPushButton, self).__init__(*args, **kwargs)
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super(DropFilesPushButton, self).dragEnterEvent(event)

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            self.files_dropped.emit(event.mimeData().urls())
            event.acceptProposedAction()
        else:
            super(DropFilesPushButton, self).dropEvent(event)
