import sys
from functools import partial
from os import path
from typing import Dict, List, Tuple

from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QCheckBox
from pydm import Display
from pydm.widgets import PyDMEmbeddedDisplay

import checkout_utils as utils
from lcls_tools.common.pydm_tools.displayUtils import make_info_popup, showDisplay
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
                checkbox.stateChanged.connect(partial(self.checkbox_clicked, checkbox))
                self.ui.checkbox_layout.addWidget(checkbox, i, j)
                list_index += 1
        
        self.magnet_control_window = Display(ui_filename=self.getPath("magnet_screen.ui"))
        self.livesignals_window = Display(ui_filename=self.getPath("livesignals.ui"))
        self.ui.start_button.clicked.connect(self.magnet_button_clicked)
        self.ui.signals_button.clicked.connect(partial(showDisplay, self.livesignals_window))
        
        self.quadMagnetScreen: MagnetScreen = MagnetScreen()
        self.xcorMagnetScreen: MagnetScreen = MagnetScreen()
        self.ycorMagnetScreen: MagnetScreen = MagnetScreen()
        
        self.setupMagnetScreen()
        
        self.current_cm = None
        
        control_plot_params: TimePlotParams = TimePlotParams(plot=self.magnet_control_window.ui.plot_magnet,
                                                             formLayout=self.magnet_control_window.ui.magnet_plot_layout)
        
        liveplot_params: TimePlotParams = TimePlotParams(plot=self.livesignals_window.ui.magnet_timeplot,
                                                         formLayout=self.livesignals_window.ui.magnet_layout)
        
        self.magnet_plot_updater: TimePlotUpdater = TimePlotUpdater({utils.CONTROL_PLOT_KEY: control_plot_params,
                                                                     utils.LIVE_PLOT_KEY   : liveplot_params})
        
        self.magnet_control_window.ui.magnet_combobox.currentIndexChanged.connect(self.update_magnetscreen)
        
        self.ui.controls_button.clicked.connect(partial(showDisplay, self.magnet_control_window))
    
    def getPath(self, fileName):
        return path.join(self.pathHere, fileName)
    
    def update_magnetscreen(self):
        self.current_cm = self.selected_cryomodules[self.magnet_control_window.ui.magnet_combobox.currentText()]
        self.quadMagnetScreen.connectSignals(self.current_cm.quad)
        self.xcorMagnetScreen.connectSignals(self.current_cm.xcor)
        self.ycorMagnetScreen.connectSignals(self.current_cm.ycor)
        
        self.magnet_plot_updater.updatePlot(key=utils.CONTROL_PLOT_KEY,
                                            newChannels=(self.current_cm.magnet_pv_pairs + [
                                                (self.current_cm.quad.bactPV.pvname, None),
                                                (self.current_cm.xcor.bactPV.pvname, None),
                                                (self.current_cm.ycor.bactPV.pvname, None)]))
    
    def end_checkout(self):
        for cryomodule in self.selected_cryomodules.values():
            cryomodule.quad.end_checkout()
            cryomodule.xcor.end_checkout()
            cryomodule.ycor.end_checkout()
        make_info_popup('Magnet checkout is done')
    
    def magnet_button_clicked(self):
        
        showDisplay(self.livesignals_window)
        for cryomodule in self.selected_cryomodules.values():
            cryomodule.quad.start_checkout()
            cryomodule.xcor.start_checkout()
            cryomodule.ycor.start_checkout()
        make_info_popup('Magnets will be running for 1 hour. Press ok to start timer.')
        QTimer.singleShot(3600, self.end_checkout)
    
    def setupMagnetScreen(self):
        
        for magnetScreen in [self.quadMagnetScreen, self.xcorMagnetScreen,
                             self.ycorMagnetScreen]:
            embeddedDisplay: PyDMEmbeddedDisplay = PyDMEmbeddedDisplay()
            embeddedDisplay.embedded_widget = magnetScreen
            self.magnet_control_window.ui.magnet_layout.addWidget(embeddedDisplay)
    
    def ui_filename(self):
        return 'checkout.ui'
    
    def checkbox_clicked(self, checkbox: QCheckBox):
        if checkbox.isChecked():
            self.selected_cryomodules[checkbox.text()] = self.cryomodule_dict[checkbox.text()]
        else:
            self.selected_cryomodules.pop(checkbox.text())
        self.populate_combobox()
        new_channel_list: List[Tuple] = []
        for cryomodule in self.selected_cryomodules.values():
            new_channel_list += cryomodule.magnet_pv_pairs
            new_channel_list += [(cryomodule.quad.bactPV.pvname, None),
                                 (cryomodule.xcor.bactPV.pvname, None),
                                 (cryomodule.ycor.bactPV.pvname, None)]
        self.magnet_plot_updater.updatePlot(key=utils.LIVE_PLOT_KEY, newChannels=new_channel_list)
    
    def start_checkout(self):
        for cryomodule in self.selected_cryomodules.values():
            cryomodule.quad.checkout()
            cryomodule.xcor.checkout()
            cryomodule.ycor.checkout()
    
    def populate_combobox(self):
        self.magnet_control_window.ui.magnet_combobox.clear()
        for cryomodule in self.selected_cryomodules.keys():
            self.magnet_control_window.ui.magnet_combobox.addItem(cryomodule)
