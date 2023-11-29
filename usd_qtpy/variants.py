from qtpy import QtWidgets, QtCore


class CreateVariantSetDialog(QtWidgets.QDialog):
    """Prompt for variant set name"""
    def __init__(self, parent=None):
        super(CreateVariantSetDialog, self).__init__(parent=parent)

        self.setWindowTitle("Create Variant Set")

        form = QtWidgets.QFormLayout(self)

        name = QtWidgets.QLineEdit()
        form.addRow(QtWidgets.QLabel("Variant Set Name:"), name)

        # Add some standard buttons (Cancel/Ok) at the bottom of the dialog
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok |
            QtWidgets.QDialogButtonBox.Cancel,
            QtCore.Qt.Horizontal,
            self
        )
        form.addRow(buttons)

        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        self.name = name

    @classmethod
    def get_variant_set_name(cls, parent=None):
        prompt = cls(parent=parent)
        if prompt.exec_() == QtWidgets.QDialog.Accepted:
            name = prompt.name.text()
            if name:
                return name
