import os
import argparse


parser = argparse.ArgumentParser(
    prog='usd_qtpy',
    description='USD Editor built in Python using Qt',
)
parser.add_argument(
    'filepath',
    help="USD filepath open in the example editor")


def main():
    args = parser.parse_args()
    filepath = args.filepath

    if not os.path.exists(filepath):
        raise RuntimeError(f"USD file does not exist: {filepath}")

    # Import here so that one get the argparse help even if relevant libraries
    # are not installed
    from pxr import Usd  # noqa
    from qtpy import QtWidgets  # noqa
    from usd_qtpy.editor import EditorWindow  # noqa
    from usd_qtpy.style import load_stylesheet

    stage = Usd.Stage.Open(filepath)
    app = QtWidgets.QApplication()
    dialog = EditorWindow(stage=stage)
    dialog.resize(1200, 600)
    dialog.setStyleSheet(load_stylesheet())
    dialog.show()
    app.exec_()


if __name__ == "__main__":
    main()
