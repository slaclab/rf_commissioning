from typing import Dict, List

from PyQt5.QtWidgets import QCheckBox
from pydm import Display
from lcls_tools.superconducting.scLinac import Cryomodule
import checkout_utils as utils


class MagnetCheckoutGUI(Display):

    def __init__(self, parent=None, args=None):
        super(MagnetCheckoutGUI, self).__init__(parent=parent, args=args)

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


