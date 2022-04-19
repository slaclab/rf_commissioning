import sys
from functools import partial
from os import path
from typing import List, Dict

from PyQt5.QtWidgets import QVBoxLayout, QWidget, QPushButton
from edmbutton import PyDMEDMDisplayButton
from lcls_tools.devices.scLinac import CRYOMODULE_OBJECTS
from pydm import Display
from qtpy.QtCore import Slot

import utilities as util


class GuidedCommissioningScreens(Display):

    def __init__(self, parent=None, args=None):
        super(GuidedCommissioningScreens, self).__init__(parent=parent, args=args)

        self.pathHere = path.dirname(sys.modules[self.__module__].__file__)

        # declare class variables
        self.current_cm: util.CommissioningCryomodule = None
        self.current_cavity: util.CommissioningCavity = None
        self.current_decarad = None
        self.current_pvprefix = None

        self.magnet_checkout_window = Display(ui_filename=self.getPath("MagnetScreen.ui"))
        self.ui.button_magnet_checkout.clicked.connect(partial(self.showDisplay, self.magnet_checkout_window))

        self._magnet_edm_buttons: Dict[str, PyDMEDMDisplayButton] = {}

        # setup: initial setup tab
        self.setup_combo_boxes()

        self.update_current_cavity_and_cm()

        # setup: StripTool & Interlock
        # button_decaradgui is an PyDMRelatedDisplayButton
        self.ui.button_decaradgui.filenames = ["$TOOLS/pydm/display/ads/decarad_main.ui"]
        self.ui.button_decaradgui.openInNewWindow = True
        self.update_current_decarad()

        self.initial_setup()

        magnet_VBoxLayout_list: List[
            QVBoxLayout] = self.magnet_checkout_window.ui.magnet_template_repeater.findChildren(QVBoxLayout)
        for VBoxLayout in magnet_VBoxLayout_list:
            # the magnet reset button is the second item in the ui-file, hence '1'
            reset_button: QPushButton = VBoxLayout.itemAt(1).widget()
            reset_button.clicked.connect(partial(self.magnet_control, reset_button.accessibleName(),
                                                 util.MAGNET_RESET_VALUE))
            # the power supply on button is the 1st item in a horizontal layout in 4th place in the ui-file,
            # hence '3' and then '0'
            on_button: QPushButton = VBoxLayout.itemAt(3).itemAt(0).widget()
            on_button.clicked.connect(partial(self.magnet_control, on_button.accessibleName(), util.MAGNET_ON_VALUE))
            # the power supply off button is the 2st item in a horizontal layout in 4th place in the ui-file,
            # hence '3' and then '1'
            off_button: QPushButton = VBoxLayout.itemAt(3).itemAt(1).widget()
            off_button.clicked.connect(partial(self.magnet_control, off_button.accessibleName(), util.MAGNET_OFF_VALUE))
            # the degauss button is the 5th item in the ui-file, hence '4'
            degauss_button: QPushButton = VBoxLayout.itemAt(4).widget()
            degauss_button.clicked.connect(
                partial(self.magnet_control, degauss_button.accessibleName(), util.MAGNET_DEGAUSS_VALUE))
            # the nominal trim button is the 6th element in the ui-file, hence '5'
            nominal_trim_button: QPushButton = VBoxLayout.itemAt(5).widget()
            nominal_trim_button.setText('Set BDES to {nominalbdes} and trim'.format(nominalbdes=util.NOMINAL_BDES))
            nominal_trim_button.clicked.connect(
                partial(self.magnet_trim, nominal_trim_button.accessibleName(), util.NOMINAL_BDES))
            # the zero trim button is the 7th element in the ui-file, hence '6'
            zero_trim_button: QPushButton = VBoxLayout.itemAt(6).widget()
            zero_trim_button.clicked.connect(
                partial(self.magnet_trim, zero_trim_button.accessibleName(), 0))
            # the edm expert display button is the 8th element in the ui-file, hence '7'
            magnet_expert_button: PyDMEDMDisplayButton = VBoxLayout.itemAt(7).widget()
            self._magnet_edm_buttons[magnet_expert_button.accessibleName()] = magnet_expert_button

    def magnet_control(self, accessible_name, enum_value):
        self.current_cm.controlPV(accessible_name).put(enum_value)

    def magnet_trim(self, accessible_name, bdes):
        self.current_cm.bdesPV(accessible_name).put(bdes)
        self.magnet_control(accessible_name, util.MAGNET_TRIM_VALUE)

    def ui_filename(self):
        return 'GuidedCommissioningScreens.ui'

    def getPath(self, fileName):
        return path.join(self.pathHere, fileName)

    def setup_combo_boxes(self):
        self.ui.testlead.addItems(util.TESTLEAD_LIST)

        self.ui.pick_cavity.currentIndexChanged.connect(self.update_current_cavity_and_cm)

        self.ui.pick_radmonitor.currentIndexChanged.connect(self.update_current_decarad)

        self.ui.pick_cm.addItems(CRYOMODULE_OBJECTS.keys())

        self.ui.pick_cm.currentIndexChanged.connect(self.update_current_cavity_and_cm)

    def update_current_cavity_and_cm(self):
        self.current_cm: util.CommissioningCryomodule = util.COMMISSIONING_CRYOMODULE_OBJECTS[
            self.ui.pick_cm.currentText()]
        self.current_cavity: util.CommissioningCavity = self.current_cm.cavities[int(self.ui.pick_cavity.currentText())]

        # button_interlockoverview is an PyDMEDMDisplaybutton
        self.ui.button_interlockoverview.macros = [self.macro_string]

        for magnettype, edmbutton in self._magnet_edm_buttons.items():
            edmbutton.macros = ["DEV={dev}".format(dev=self.current_cm.magnetPVs[magnettype].prefix)]

        self.magnet_checkout_window.ui.magnet_groupbox.setTitle('CM{cm}'.format(cm=self.current_cm.name))

    def update_current_decarad(self):
        self.current_decarad = self.ui.pick_radmonitor.currentText()
        P = "RADM:SYS0:{decarad}00".format(decarad=self.current_decarad)
        self.ui.button_decaradgui.macros = ["P={pstring}".format(pstring=P),
                                            "M={mstring}".format(mstring=self.current_decarad)]

    def initial_setup(self):
        # set variables for other tabs
        # Striptool + Interlock tab

        self.ui.button_striptools.commands = [
            'srf_stavDisplayCfg.py st cmcryos {prefix}; StripTool $STRIP_CONFIGFILE_DIR/srf_cmcryos.stp'.format(
                prefix=self.current_cm.pvPrefix[:-2])
        ]

    @property
    def macro_string(self):

        c = str(self.current_cavity.number)

        if self.current_cavity.number in (1, 2):
            rfs = '1A'
        elif self.current_cavity.number in (3, 4):
            rfs = '2A'
        elif self.current_cavity.number in (5, 6):
            rfs = '1B'
        else:
            rfs = '2B'

        if 1 <= self.current_cavity.number <= 4:
            r = 'A'
        else:
            r = 'B'

        cm = self.current_cm.pvPrefix[:-3]  # need to remove trailing colon and zeroes to match needed format

        id = self.current_cm.name

        if self.current_cavity.number in (2, 4):
            ch = 2
        else:
            ch = 1

        macro_string = ",".join(
            ["C={c}".format(c=c), "RFS={rfs}".format(rfs=rfs), "R={r}".format(r=r), "CM={cm}".format(cm=cm),
             "ID={id}".format(id=id), "CH={ch}".format(ch=ch)])
        return macro_string

    @Slot()
    def showDisplay(self, display: QWidget):
        display.show()

        # brings the display to the front
        display.raise_()

        # gives the display focus
        display.activateWindow()
