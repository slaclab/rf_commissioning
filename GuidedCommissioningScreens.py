import dataclasses
import json
import sys
from functools import partial
from os import path
from time import sleep
from typing import List, Dict, Optional

from PyQt5.QtWidgets import QVBoxLayout, QWidget, QPushButton, QMessageBox
from edmbutton import PyDMEDMDisplayButton
from epics.ca import CASeverityException
from pydm import Display
from pydm.widgets import PyDMByteIndicator, PyDMLabel
from qtpy.QtCore import Slot

import lcls_tools.devices.scLinac.scLinacUtils as scLinacUtils
import utilities as util
from commissioningLinac import CommissioningCryomodule, CommissioningCavity, COMMISSIONING_CRYOMODULE_OBJECTS
from lcls_tools.devices.scLinac.scLinac import CRYOMODULE_OBJECTS
from lcls_tools.pydm_tools.pydmPlotUtil import TimePlotParams, TimePlotUpdater, WaveformPlotParams, WaveformPlotUpdater

FREQ_SEARCH_MODEOVERLAP = 1000

FREQ_SEARCH_RMS_THRESH = 10

FREQ_SEARCH_HIGH = 50000

FREQ_SEARCH_LOW = -900000

STEPPERTEMP_PLOT_KEY = 'steppertemp'
CMVACUUM_PLOT_KEY = 'cmvacuum'
CRYOSIGNALS_PLOT_KEY = 'cryosignals'
MAGNET_PLOT_KEY = 'magnet'
HOMUS_PLOT_KEY = 'homus'
HOMDS_PLOT_KEY = 'homds'
CPLRTOP_PLOT_KEY = 'cplrtop'
CPLRBOT_PLOT_KEY = 'cplrbot'
SINGLE_CAVITY_PLOT_KEY = 'singlecavity'
FREQUENCY_PLOT_KEY = 'frequency'
RFWAVEFORM_PLOT_KEY = 'rfwaveform'


class GuidedCommissioningScreens(Display):

    def __init__(self, parent=None, args=None):
        # TODO add functionality to disable ui buttons that depend on completion of previous steps
        super(GuidedCommissioningScreens, self).__init__(parent=parent, args=args)

        self.pathHere = path.dirname(sys.modules[self.__module__].__file__)

        # declare class variables
        self.current_cm: Optional[CommissioningCryomodule] = None
        self.current_cavity: Optional[CommissioningCavity] = None
        self.current_decarad = None
        self.current_pvprefix = None

        self.magnet_checkout_window = Display(ui_filename=self.getPath("MagnetScreen.ui"))
        self.ui.button_magnet_checkout.clicked.connect(partial(self.showDisplay, self.magnet_checkout_window))

        self._magnet_edm_buttons: Dict[str, PyDMEDMDisplayButton] = {}

        # setup: initial setup tab
        self.setup_combo_boxes()

        # setup: StripTool & Interlock
        # button_decaradgui is an PyDMRelatedDisplayButton
        self.ui.button_decaradgui.filenames = ["$TOOLS/pydm/display/ads/decarad_main.ui"]
        self.ui.button_decaradgui.openInNewWindow = True
        self.update_current_decarad()

        self.magnet_interlock_labels = {}
        self.magnet_interlock_indicators = {}
        self.magnet_ps_status_labels = {}
        self.magnet_ps_status_indicators = {}

        self.get_magnet_labels()

        self.rf_controls_window = Display(ui_filename=self.getPath("RFControls.ui"))

        self.live_signals_window = Display(ui_filename=self.getPath("LiveSignals.ui"))
        self.ui.button_livesignals.clicked.connect(partial(self.showDisplay, self.live_signals_window))

        time_plot_updater = {STEPPERTEMP_PLOT_KEY: TimePlotParams(plot=self.live_signals_window.ui.plot_steppertemps),
                             MAGNET_PLOT_KEY: TimePlotParams(plot=self.live_signals_window.ui.plot_magnet),
                             HOMUS_PLOT_KEY: TimePlotParams(plot=self.live_signals_window.ui.plot_homus_temp),
                             HOMDS_PLOT_KEY: TimePlotParams(plot=self.live_signals_window.ui.plot_homds_temp),
                             CPLRTOP_PLOT_KEY: TimePlotParams(plot=self.live_signals_window.ui.plot_couplertop_temp),
                             CPLRBOT_PLOT_KEY: TimePlotParams(plot=self.live_signals_window.ui.plot_couplerbot_temp),
                             CMVACUUM_PLOT_KEY: TimePlotParams(plot=self.live_signals_window.ui.plot_cmvacuum),
                             CRYOSIGNALS_PLOT_KEY: TimePlotParams(plot=self.live_signals_window.ui.plot_cryosignals),
                             SINGLE_CAVITY_PLOT_KEY: TimePlotParams(
                                 plot=self.live_signals_window.ui.plot_single_cavity_overview),
                             FREQUENCY_PLOT_KEY: TimePlotParams(plot=self.live_signals_window.ui.plot_frequency)
                             }
        self.time_plot_updater = TimePlotUpdater(time_plot_updater)

        self.waveform_plot_updater = WaveformPlotUpdater({RFWAVEFORM_PLOT_KEY: WaveformPlotParams(
            plot=self.rf_controls_window.ui.waveform_rfsignals)})

        self.update_current_cavity_and_cm()

        self.ui.button_ssa_char.clicked.connect(self.ssa_calibration_button_pushed)
        self.ui.button_cavity_calibration.clicked.connect(self.cavity_calibration_button_pushed)
        self.ui.button_measure_8pi9.clicked.connect(self.freq_scan_button_pressed)

    def get_magnet_labels(self):
        magnet_VBoxLayout_list: List[
            QVBoxLayout] = self.magnet_checkout_window.ui.magnet_template_repeater.findChildren(QVBoxLayout)
        for VBoxLayout in magnet_VBoxLayout_list:
            # the interlock status is the first element in the ui-file, with the byte indicator in 2nd and the text label in 3rd position, hence '0' then '1' and '2'
            interlock_indicator: PyDMByteIndicator = VBoxLayout.itemAt(0).itemAt(1).widget()
            interlock_label: PyDMLabel = VBoxLayout.itemAt(0).itemAt(2).widget()
            self.magnet_interlock_labels[interlock_label.accessibleName()] = interlock_label
            self.magnet_interlock_indicators[interlock_indicator.accessibleName()] = interlock_indicator

            # the magnet reset button is the second item in the ui-file, hence '1'
            reset_button: QPushButton = VBoxLayout.itemAt(1).widget()
            reset_button.clicked.connect(partial(self.magnet_control, reset_button.accessibleName(),
                                                 util.MAGNET_RESET_VALUE))

            # the power supply status is the third element in the ui-file, with the byte indicator in 2nd and the text label in 3rd position, hence '2' then '1' and '2'
            ps_status_indicator: PyDMByteIndicator = VBoxLayout.itemAt(2).itemAt(1).widget()
            ps_status_label: PyDMLabel = VBoxLayout.itemAt(2).itemAt(2).widget()
            self.magnet_ps_status_labels[ps_status_label.accessibleName()] = ps_status_label
            self.magnet_ps_status_indicators[ps_status_indicator.accessibleName()] = ps_status_indicator

            # the power supply on button is the 1st item in a horizontal layout in 4th place in the ui-file,
            # hence '3' and then '0'
            on_button: QPushButton = VBoxLayout.itemAt(3).itemAt(0).widget()
            on_button.clicked.connect(partial(self.magnet_control, on_button.accessibleName(), util.MAGNET_ON_VALUE))

            # the power supply off button is the 2nd item in a horizontal layout in 4th place in the ui-file,
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

            # the edm expert display button is the 9th element in the ui-file, hence '8'
            magnet_expert_button: PyDMEDMDisplayButton = VBoxLayout.itemAt(8).widget()
            self._magnet_edm_buttons[magnet_expert_button.accessibleName()] = magnet_expert_button

    def magnet_control(self, accessible_name, enum_value):
        self.current_cm.magnet_name_map[accessible_name].controlPV.put(enum_value)

    def magnet_trim(self, accessible_name, bdes):
        self.current_cm.magnet_name_map[accessible_name].bdesPV.put(bdes)
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

    def populate_status_labels(self):
        @dataclasses.dataclass
        class StatusMap:
            message: str
            color: str

            @property
            def stylesheet(self):
                return 'color: {color};'.format(color=self.color)

        status_map = {True: StatusMap('Complete', 'green'),
                      False: StatusMap('Incomplete', 'red')}

        cm_results = self.current_cm.results
        cav_results = self.current_cavity.results
        overall_completion_status = (cm_results.magnet_checked
                                     and cav_results.piezo_prerf_checked
                                     and cav_results.ssa_characterized
                                     and cav_results.is_tuned
                                     and cav_results.eightpiovernine_frequency_measured
                                     and cav_results.cavity_calibration_run
                                     and cav_results.onehourrun_complete
                                     and cm_results.unit_test_complete
                                     )

        label_status_pairs = [(self.ui.label_checkout_magnet, cm_results.magnet_checked),
                              (self.ui.label_piezo_prerf, cav_results.piezo_prerf_checked),
                              (self.ui.label_ssa_char, cav_results.ssa_characterized),
                              (self.ui.label_tune_cavity, cav_results.is_tuned),
                              (self.ui.label_measure_8pi9,
                               cav_results.eightpiovernine_frequency_measured),
                              (self.ui.label_cavity_calibration, cav_results.cavity_calibration_run),
                              (self.ui.label_selap_rampup, cav_results.onehourrun_complete),
                              (self.ui.label_12hrun, cm_results.unit_test_complete),
                              (self.ui.label_overall_completion, overall_completion_status)]

        for label, status in label_status_pairs:
            label.setText(status_map[status].message)
            label.setStyleSheet(status_map[status].stylesheet)

    def update_current_cavity_and_cm(self):
        self.save_results()

        self.current_cm: CommissioningCryomodule = COMMISSIONING_CRYOMODULE_OBJECTS[
            self.ui.pick_cm.currentText()]
        self.current_cavity: CommissioningCavity = self.current_cm.cavities[int(self.ui.pick_cavity.currentText())]

        self.load_results()

        self.populate_status_labels()

        # button_interlockoverview is an PyDMEDMDisplaybutton
        self.ui.button_interlockoverview.macros = [self.macro_string]

        self.ui.button_striptools.commands = [
            'srf_stavDisplayCfg.py st cmcryos {prefix}; StripTool $STRIP_CONFIGFILE_DIR/srf_cmcryos.stp'.format(
                prefix=self.current_cm.pvPrefix[:-2])
        ]

        self.update_magnets()

        self.update_rf_controls()

        plot_update_map = {STEPPERTEMP_PLOT_KEY: self.current_cm.stepper_temp_PVs,
                           HOMDS_PLOT_KEY: self.current_cm.hom_ds_PVs,
                           HOMUS_PLOT_KEY: self.current_cm.hom_us_PVs,
                           CPLRTOP_PLOT_KEY: self.current_cm.coupler_top_PVs,
                           CPLRBOT_PLOT_KEY: self.current_cm.coupler_bot_PVs,
                           FREQUENCY_PLOT_KEY: self.current_cm.detune_PVs}

        self.time_plot_updater.updatePlots(plot_update_map)

        rfwaveformplot_update_map = {RFWAVEFORM_PLOT_KEY: self.current_cavity.waveformplot_channelpairs}
        self.waveform_plot_updater.updatePlots(rfwaveformplot_update_map)

    def update_rf_controls(self):
        ui = self.rf_controls_window.ui
        ui.button_ssa_on.clicked.connect(self.current_cavity.ssa.turnOn)
        ui.button_ssa_off.clicked.connect(self.current_cavity.ssa.turnOff)
        ui.label_ssa_status.channel = self.current_cavity.ssa.ssaStatusPV.pvname

        ui.button_rfmode_chirp.clicked.connect(partial(self.current_cavity.rfModeCtrlPV.put,
                                                       scLinacUtils.RF_MODE_CHIRP))
        ui.button_rfmode_pulsed.clicked.connect(partial(self.current_cavity.rfModeCtrlPV.put,
                                                        scLinacUtils.RF_MODE_PULSE))
        ui.button_rfmode_sel.clicked.connect(partial(self.current_cavity.rfModeCtrlPV.put,
                                                     scLinacUtils.RF_MODE_SEL))
        ui.button_rfmode_sela.clicked.connect(partial(self.current_cavity.rfModeCtrlPV.put,
                                                      scLinacUtils.RF_MODE_SELA))
        ui.button_rfmode_selap.clicked.connect(partial(self.current_cavity.rfModeCtrlPV.put,
                                                       scLinacUtils.RF_MODE_SELAP))
        ui.label_rfmode_rdbk.channel = self.current_cavity.rfModePV.pvname

        ui.button_rf_on.clicked.connect(self.current_cavity.turnOn)
        ui.button_rf_off.clicked.connect(self.current_cavity.turnOff)
        ui.label_rfstatus_rdbk.channel = self.current_cavity.rfStatePV.pvname

        ui.lineedit_selphaseoffset.channel = self.current_cavity.sel_phaseoffset_PV.pvname
        ui.label_selphaseoffset_rdbk.channel = self.current_cavity.sel_phaseoffset_rdbk_PV.pvname
        ui.slider_selphaseoffset.channel = self.current_cavity.sel_phaseoffset_PV.pvname

        ui.indicator_phas_high.channel = self.current_cavity.feedback_phase_high_PV.pvname
        ui.indicator_phas_low.channel = self.current_cavity.feedback_phase_low_PV.pvname
        ui.indicator_amp_high.channel = self.current_cavity.feedback_amplitude_high_PV.pvname
        ui.indicator_amp_low.channel = self.current_cavity.feedback_amplitude_low_PV.pvname

        ui.label_max_amplitude.channel = self.current_cavity.acceptancetest_max_amplitude_PV.pvname
        ui.label_useable_amplitude.channel = self.current_cavity.acceptancetest_useable_amplitude_PV.pvname
        ui.label_fe_onset.channel = self.current_cavity.acceptancetest_fe_onset_PV.pvname
        ui.label_cavity_limitation.channel = self.current_cavity.acceptancetest_cavity_limitation_PV.pvname

    def update_magnets(self):
        for magnettype, edmbutton in self._magnet_edm_buttons.items():
            edmbutton.macros = ["DEV={dev}".format(dev=self.current_cm.magnet_name_map[magnettype].pvprefix[:-1])]
        self.magnet_checkout_window.ui.magnet_groupbox.setTitle('CM{cm}'.format(cm=self.current_cm.name))
        for magnetprefix in ['Quad', 'XCor', 'YCor']:
            magnet_object = self.current_cm.magnet_name_map[magnetprefix]
            self.magnet_interlock_indicators[magnetprefix].channel = magnet_object.interlockPV.pvname
            self.magnet_interlock_labels[magnetprefix].channel = magnet_object.interlockPV.pvname
            self.magnet_ps_status_labels[magnetprefix].channel = magnet_object.ps_statusPV.pvname
            self.magnet_ps_status_indicators[magnetprefix].channel = magnet_object.ps_statusPV.pvname

    def update_current_decarad(self):
        self.current_decarad = self.ui.pick_radmonitor.currentText()
        P = "RADM:SYS0:{decarad}00".format(decarad=self.current_decarad)
        self.ui.button_decaradgui.macros = ["P={pstring}".format(pstring=P),
                                            "M={mstring}".format(mstring=self.current_decarad)]

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

    def run_piezo_prerf_check(self):
        # turn RF off
        self.current_cavity.turnOff()
        # set piezo to 'enabled'
        self.current_cavity.piezo_enable_PV.put(1)
        # set piezo to 'manual' mode
        self.current_cavity.piezo_feedback_mode_PV.put(0)
        # set piezo DC voltage offset to 0V
        self.current_cavity.piezo_dc_setpoint_PV.put(0)
        # run the test script
        self.current_cavity.piezo_prerf_run_check_PV.put(1)

        while self.current_cavity.piezo_prerf_check_status_PV.value == 2:
            sleep(1)
        if self.current_cavity.piezo_prerf_check_status_PV.value == 0:
            print('Piezo pre-rf test script has exited with status \'crash\' ')

        if self.current_cavity.piezo_prerf_cha_status_PV.value == 0 and self.current_cavity.piezo_prerf_chb_status_PV == 0:
            self.current_cavity.results.piezo_capacitance_a = self.current_cavity.piezo_capacitance_a_PV.value
            self.current_cavity.results.piezo_capacitance_b = self.current_cavity.piezo_capacitance_b_PV.value
            self.current_cavity.results.piezo_prerf_checked = True
            self.ui.label_piezo_prerf.setText('Complete')
        else:
            self.ui.label_piezo_prerf.setText('Failed')

    def run_ssa_calibration(self, drivemax=0.8, attemptnumber=1):
        if self.current_cavity.results.ssa_maxdrive:
            self.current_cavity.ssa_maxdrive_PV.put(self.current_cavity.results.ssa_maxdrive)
        else:
            self.current_cavity.ssa_maxdrive_PV.put(drivemax)
        try:
            self.current_cavity.ssa.runCalibration()
            self.current_cavity.results.ssa_maxdrive = drivemax
            self.current_cavity.results.ssa_characterized = True
        except scLinacUtils.SSACalibrationError:
            if attemptnumber <= 3:
                self.run_ssa_calibration(drivemax - 0.05, attemptnumber + 1)
            else:
                raise scLinacUtils.SSACalibrationError

    def ssa_calibration_button_pushed(self):
        try:
            self.run_ssa_calibration()
        except (scLinacUtils.SSACalibrationError, scLinacUtils.SSAPowerError) as e:
            print(e)
            ssa_expert_button = PyDMEDMDisplayButton()
            ssa_expert_button.filenames = ['$TOOLS/edm/display/llrf/rf_srf_char_embed_ssa.edl']
            ssa_expert_button.macros = self.macro_string
            ssa_expert_button.setText('Open SSA EDM expert screen')
            ssa_expert_button.setDefault(True)
            self.make_popup('SSA calibration failed', ssa_expert_button, e, self.ssa_actionbutton_clicked)
        self.save_results()

    def make_popup(self, title, expert_edmbutton, exception, action_func):
        popup = QMessageBox()
        popup.setIcon(QMessageBox.Critical)
        popup.setWindowTitle(title)
        popup.setText(
            '{error}\nPlease check expert screen and select from the options below'.format(error=exception))
        popup.addButton('Abort', QMessageBox.RejectRole)
        popup.addButton('Acknowledge manual completion and continue', QMessageBox.AcceptRole)
        popup.addButton(expert_edmbutton, QMessageBox.ActionRole)
        popup.buttonClicked.connect(partial(action_func, popup))
        popup.exec()

    def ssa_actionbutton_clicked(self, qmessagebox: QMessageBox):
        clickedbutton = qmessagebox.clickedButton()
        if qmessagebox.buttonRole(clickedbutton) == QMessageBox.AcceptRole:
            self.current_cavity.results.ssa_characterized = True
            self.current_cavity.results.ssa_maxdrive = self.current_cavity.ssa_maxdrive_PV.value
        self.populate_status_labels()

    def freq_actionbutton_clicked(self, qmessagebox: QMessageBox):
        clickedbutton = qmessagebox.clickedButton()
        if qmessagebox.buttonRole(clickedbutton) == QMessageBox.AcceptRole:
            self.current_cavity.results.eightpiovernine_frequency_measured = True
        self.populate_status_labels()

    def cavity_calibration_button_pushed(self):
        try:
            self.rf_controls_window.show()
            self.current_cavity.runCalibration(loadedQLowerlimit=3e7, loadedQUpperlimit=5e7)
            self.current_cavity.results.fpc_qext = self.current_cavity.measuredQLoadedPV.value
            self.current_cavity.results.probe_qext_value = self.current_cavity.measured_probe_qext_PV.value
            self.current_cavity.results.cavity_calibration_run = True
            self.populate_status_labels()
            self.save_results()
        except (
                scLinacUtils.CavityQLoadedCalibrationError, scLinacUtils.CavityScaleFactorCalibrationError,
                TypeError, CASeverityException) as e:
            cavity_expert_button = self.make_edmbutton('$TOOLS/edm/display/llrf/rf_srf_char_embed_ramp.edl')
            self.make_popup('Cavity calibration failed', cavity_expert_button, e, self.cavity_actionbutton_clicked)

    def make_edmbutton(self, filepath: str):
        edmbutton = PyDMEDMDisplayButton()
        edmbutton.filenames = [filepath]
        edmbutton.macros = self.macro_string
        edmbutton.setText('Open EDM expert screen')
        edmbutton.setDefault(True)
        return edmbutton

    def cavity_actionbutton_clicked(self, qmessagebox: QMessageBox):
        clickedbutton = qmessagebox.clickedButton()
        if qmessagebox.buttonRole(clickedbutton) == QMessageBox.AcceptRole:
            self.current_cavity.results.cavity_calibration_run = True
            self.current_cavity.results.fpc_qext = self.current_cavity.measuredQLoadedPV.value
            self.current_cavity.results.probe_qext_value = self.current_cavity.measured_probe_qext_PV.value
        self.populate_status_labels()

    def measure_8pi9mode(self):
        other_cavities = list(self.current_cavity.rack.cavities.keys())
        other_cavities.remove(self.current_cavity.number)

        for cavity in other_cavities:
            self.current_cm.cavities[cavity].freq_search_select_PV.put(0)
        self.current_cavity.freq_search_select_PV.put(1)

        self.current_cavity.rack.freq_search_low_PV.put(FREQ_SEARCH_LOW)
        self.current_cavity.rack.freq_search_high_PV.put(FREQ_SEARCH_HIGH)
        self.current_cavity.rack.freq_search_rms_thresh_PV.put(FREQ_SEARCH_RMS_THRESH)
        self.current_cavity.rack.freq_search_modeoverlap_PV.put(FREQ_SEARCH_MODEOVERLAP)

        self.current_cavity.rack.freq_search_start_PV.put(1)
        while self.current_cavity.rack.freq_search_status_PV.value == 3:
            sleep(1)
        if self.current_cavity.rack.freq_search_status_PV.value != 5:
            raise util.FreqSearchError('Frequency search did not exit successfully')
        if (self.current_cavity.freq_search_8pi9_PV.value > -750000
                or self.current_cavity.freq_search_8pi9_PV.value < -850000):
            raise util.FreqSearchError('8pi/9 frequency outside tolerance')
        self.current_cavity.freq_search_push_PV.put(1)
        self.current_cavity.results.eightpiovernine_frequency_measured = True

    def freq_scan_button_pressed(self):
        try:
            self.measure_8pi9mode()
        except util.FreqSearchError as e:
            freq_edmbutton = self.make_edmbutton('$TOOLS/edm/display/llrf/rf_srf_freq_scan_rack_embed_search.edl')
            self.make_popup(title='Error finding 8pi/9 frequency', expert_edmbutton=freq_edmbutton,
                            exception=e, action_func=self.freq_actionbutton_clicked)

    def load_results(self):
        with open('cryomodule_results.json', 'r+') as f:
            data = json.load(f)
            if self.current_cm.name in data:
                self.current_cm.results.__dict__.update(data[self.current_cm.name])
        with open('cavity_results.json', 'r+') as f:
            data = json.load(f)
            if self.current_cm.name in data:
                cav_data = data[self.current_cm.name]
                # required precondition: keys in cav_data are ints 1 through 8
                if str(self.current_cavity.number) in cav_data:
                    self.current_cavity.results.__dict__.update(cav_data[str(self.current_cavity.number)])

    def save_results(self):
        if not self.current_cm:
            return

        with open('cryomodule_results.json', 'r+') as f:
            data = json.load(f)

            data[self.current_cm.name] = self.current_cm.results.__dict__
            f.seek(0)
            json.dump(data, f)
            f.truncate()
        with open('cavity_results.json', 'r+') as f:
            data = json.load(f)
            if self.current_cm.name not in data:
                data[self.current_cm.name] = {cav_number: {} for cav_number in self.current_cm.cavities.keys()}
            data[self.current_cm.name][self.current_cavity.number] = self.current_cavity.results.__dict__
            f.seek(0)
            json.dump(data, f)
            f.truncate()
