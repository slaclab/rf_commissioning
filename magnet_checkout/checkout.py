import sys
from functools import partial
from os import path
from typing import Dict, List

from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QCheckBox
from pydm import Display
from pydm.widgets import PyDMEmbeddedDisplay

import checkout_utils as utils
from lcls_tools.common.pydm_tools.displayUtils import showDisplay
from lcls_tools.common.pydm_tools.magnet import MagnetScreen
from lcls_tools.common.pydm_tools.pydmPlotUtil import TimePlotParams, TimePlotUpdater
from lcls_tools.superconducting.scLinac import Cryomodule


class MagnetCheckoutGUI(Display):

    def __init__(self, parent=None, args=None):
        super(MagnetCheckoutGUI, self).__init__(parent=parent, args=args)

        self.pathHere = path.dirname(sys.modules[self.__module__].__file__)

        self.selected_cryomodules: Dict = {}

        self.cryomodule_dict = utils.CHECKOUT_CRYOMODULE_OBJECTS
        self.cryomodule_dict.pop('H1')
        self.cryomodule_dict.pop('H2')
        cryomodule_list: List[Cryomodule] = list(self.cryomodule_dict.values())
        list_index = 0
        for i in range(5):
            for j in range(7):
                checkbox = QCheckBox(cryomodule_list[list_index].name)
                self.ui.checkbox_layout.addWidget(checkbox, i, j)
                list_index += 1

        self.magnet_checkout_window = Display(ui_filename=self.getPath("magnet_screen.ui"))
        self.ui.start_button.clicked.connect(self.magnet_button_clicked)

        self.quadMagnetScreen: MagnetScreen = MagnetScreen()
        self.xcorMagnetScreen: MagnetScreen = MagnetScreen()
        self.ycorMagnetScreen: MagnetScreen = MagnetScreen()

        self.setupMagnetScreen()

        self.current_cm = None

        self.magnet_plot_params: TimePlotParams = TimePlotParams(plot=self.magnet_checkout_window.ui.plot_magnet,
                                                                 formLayout=self.magnet_checkout_window.ui.magnet_plot_layout)

        self.magnet_plot_updater: TimePlotUpdater = TimePlotUpdater({'magnetplot': self.magnet_plot_params})

    def getPath(self, fileName):
        return path.join(self.pathHere, fileName)

    def update_magnetscreen(self):
        self.quadMagnetScreen.connectSignals(self.current_cm.quad)
        self.xcorMagnetScreen.connectSignals(self.current_cm.xcor)
        self.ycorMagnetScreen.connectSignals(self.current_cm.ycor)

    def magnet_button_clicked(self):
        showDisplay(self.magnet_checkout_window)
        self.current_cm.quad.start_checkout()
        self.current_cm.xcor.start_checkout()
        self.current_cm.ycor.start_checkout()
        QTimer.singleShot(3600000, partial(self.make_info_popup, 'Magnet has been running for 1 hour'))

    def setupMagnetScreen(self):

        for magnetScreen in [self.quadMagnetScreen, self.xcorMagnetScreen,
                             self.ycorMagnetScreen]:
            embeddedDisplay: PyDMEmbeddedDisplay = PyDMEmbeddedDisplay()
            embeddedDisplay.embedded_widget = magnetScreen
            self.magnet_checkout_window.ui.magnet_layout.addWidget(embeddedDisplay)

    def ui_filename(self):
        return 'checkout.ui'

    def checkbox_clicked(self, checkbox: QCheckBox):
        if checkbox.isChecked():
            self.selected_cryomodules[checkbox.text()] = self.cryomodule_dict[checkbox.text()]
        else:
            self.selected_cryomodules.pop(checkbox.text())

    def start_checkout(self):
        for cryomodule in self.selected_cryomodules.values():
            cryomodule.quad.checkout()
            cryomodule.xcor.checkout()
            cryomodule.ycor.checkout()
