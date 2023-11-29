from pxr.Usdviewq.appController import UsdviewDataModel


class DataModel(UsdviewDataModel):
    """Thin wrapper around Usd View's app controller core data model"""

    def __init__(self):
        UsdviewDataModel.__init__(self, None, None)
