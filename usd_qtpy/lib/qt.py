import sys
import logging
from qtpy import QtCore


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
