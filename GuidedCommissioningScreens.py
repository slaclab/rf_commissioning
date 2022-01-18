from pydm import Display
from PyQt5 import QtGui

import utilities as util

class GuidedCommissioningScreens(Display):

    def __init__(self, parent=None, args=None):
        super(GuidedCommissioningScreens, self).__init__(parent=parent, args=args)
        
        #setup: initial setup tab
        self.setup_combo_boxes()

        #setup: magnet tab
        self.ui.label_7.setText('Current cryomodule is:')
        self.ui.label_8.setText('not defined yet')

        #on press of start button read entries from initial setup tab
        self.ui.start_button.clicked.connect(self.read_initial_setup)


    def ui_filename(self):
        return 'GuidedCommissioningScreens.ui'

    def setup_combo_boxes(self):
        self.ui.TestLead.addItems(["First", "Second", "Third"])
        self.ui.TestLead.setEnabled(True)

        self.ui.PickCavity.addItems(util.cavity_list)
        self.ui.PickCavity.setEnabled(True)

        self.ui.PickRadMonitor.addItems(["DecaRad 1", "DecaRad 2"])
        self.ui.PickRadMonitor.setEnabled(True)

        self.ui.PickCM.addItems(util.cryomodule_list)
        self.ui.PickCM.setEnabled(True)
    
    def read_initial_setup(self):
        current_cm = self.ui.PickCM.currentText()
        self.ui.label_8.setText(current_cm)
    

       

