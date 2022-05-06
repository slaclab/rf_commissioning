import dataclasses
import json
import sys
from functools import partial
from os import path
from threading import Lock
from time import sleep
from typing import Optional

from PyQt5.QtWidgets import QMessageBox
from edmbutton import PyDMEDMDisplayButton
from epics.ca import CASeverityException
from pydm import Display

import commissioningUtilities as util
import lcls_tools.superconducting.scLinacUtils as scLinacUtils
from commissioningLinac import COMMISSIONING_CRYOMODULE_OBJECTS, CommissioningCavity, CommissioningCryomodule, Decarad
from lcls_tools.common.pydm_tools.displayUtils import make_error_popup, showDisplay
from lcls_tools.common.pydm_tools.pydmPlotUtil import (TimePlotParams,
                                                       TimePlotUpdater,
                                                       WaveformPlotParams,
                                                       WaveformPlotUpdater)
from lcls_tools.common.pyepics_tools import pyepicsUtils
from lcls_tools.superconducting.scLinac import CRYOMODULE_OBJECTS


class GuidedCommissioningScreens(Display):

    def __init__(self, parent=None, args=None):
        # TODO add functionality to disable ui buttons that depend on completion of previous steps
        super(GuidedCommissioningScreens, self).__init__(parent=parent, args=args)

        self.pathHere = path.dirname(sys.modules[self.__module__].__file__)

        self.mutex = Lock()

        self.current_cm: Optional[CommissioningCryomodule] = None
        self.current_cavity: Optional[CommissioningCavity] = None
        self.current_pvprefix = None

        self.setup_combo_boxes()

        # button_decaradgui is an PyDMRelatedDisplayButton
        self.ui.button_decaradgui.filenames = ["$TOOLS/pydm/display/ads/decarad_main.ui"]
        self.ui.button_decaradgui.openInNewWindow = True

        self.rf_controls_window = Display(ui_filename=self.getPath("gui/rf_controls.ui"))

        self.live_signals_window = Display(ui_filename=self.getPath("gui/live_signals.ui"))
        self.ui.button_livesignals.clicked.connect(partial(showDisplay, self.live_signals_window))

        self.tuner_window = Display(ui_filename=self.getPath("gui/tuning.ui"))

        time_plot_updater = {
            util.STEPPERTEMP_PLOT_KEY: TimePlotParams(plot=self.live_signals_window.ui.plot_steppertemps),
            util.HOMUS_PLOT_KEY: TimePlotParams(plot=self.live_signals_window.ui.plot_homus_temp),
            util.HOMDS_PLOT_KEY: TimePlotParams(plot=self.live_signals_window.ui.plot_homds_temp),
            util.CPLRTOP_PLOT_KEY: TimePlotParams(
                plot=self.live_signals_window.ui.plot_couplertop_temp),
            util.CPLRBOT_PLOT_KEY: TimePlotParams(
                plot=self.live_signals_window.ui.plot_couplerbot_temp),
            util.CMVACUUM_PLOT_KEY: TimePlotParams(plot=self.live_signals_window.ui.plot_cmvacuum),
            util.CRYOSIGNALS_PLOT_KEY: TimePlotParams(plot=self.live_signals_window.ui.plot_cryosignals),
            util.SINGLE_CAVITY_PLOT_KEY: TimePlotParams(
                plot=self.live_signals_window.ui.plot_single_cavity_overview),
            util.FREQUENCY_PLOT_KEY: TimePlotParams(plot=self.live_signals_window.ui.plot_frequency),
            util.DECARAD_PLOT_KEY: TimePlotParams(plot=self.live_signals_window.ui.plot_decarad),
            util.DETUNE_PLOT_KEY: TimePlotParams(plot=self.tuner_window.ui.tuning_plot,
                                                 formLayout=self.tuner_window.ui.plot_layout)
        }
        self.time_plot_updater = TimePlotUpdater(time_plot_updater)

        self.waveform_plot_updater = WaveformPlotUpdater(
            {util.RFWAVEFORM_PLOT_KEY:
                 WaveformPlotParams(plot=self.rf_controls_window.ui.waveform_rfsignals)})

        self.update_selection()

        self.ui.button_ssa_char.clicked.connect(self.ssa_calibration_button_pushed)
        self.ui.button_cavity_calibration.clicked.connect(self.cavity_calibration_button_pushed)
        self.ui.button_measure_8pi9.clicked.connect(self.freq_scan_button_pressed)
        self.ui.button_piezo_prerf.clicked.connect(self.piezo_prerf_button_pressed)
        self.ui.button_piezo_withrf.clicked.connect(self.piezo_withrf_button_pressed)
        # TODO make popup that asks to record cold landing frequency
        # TODO add radio buttons for sanity check, have options for 'positive step = freq decrease' etc.
        self.ui.button_tune_cavity.clicked.connect(self.tune_cavity)

        self.tuner_window.ui.step_des_line_edit.returnPressed.connect(self.des_step_changed)

    def ui_filename(self):
        return 'gui/commissioning.ui'

    def getPath(self, fileName):
        return path.join(self.pathHere, fileName)

    def tune_cavity(self):
        self.current_cavity.turnOff()
        piezo = self.current_cavity.piezo
        piezo.enable_PV.put(util.PIEZO_ENABLE_VALUE)
        piezo.feedback_mode_PV.put(util.PIEZO_MANUAL_VALUE)
        # set piezo DC voltage offset to 0V
        piezo.dc_setpoint_PV.put(0)
        self.current_cavity.drivelevelPV.put(scLinacUtils.SAFE_PULSED_DRIVE_LEVEL)
        self.current_cavity.rfModeCtrlPV.put(scLinacUtils.RF_MODE_CHIRP)
        self.current_cavity.turnOn()

        if self.current_cavity.detune_best_PV.severity == pyepicsUtils.EPICS_INVALID_VAL:
            raise util.DetuneError("Detune PV invalid. Either expand the chirp"
                                   " range or use the rack large frequency scan"
                                   " to find the detune.")

        showDisplay(self.tuner_window)

    def setup_combo_boxes(self):
        self.ui.testlead.addItems(util.TESTLEAD_LIST)

        self.ui.pick_cavity.currentIndexChanged.connect(self.update_selection)

        self.ui.pick_decarad.currentIndexChanged.connect(self.update_selection)

        self.ui.pick_cm.addItems(CRYOMODULE_OBJECTS.keys())

        self.ui.pick_cm.currentIndexChanged.connect(self.update_selection)

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
                                     and cav_results.piezo_withrf_checked
                                     and cav_results.onehourrun_complete
                                     and cm_results.unit_test_complete
                                     )

        label_status_pairs = [(self.ui.label_piezo_prerf, cav_results.piezo_prerf_checked),
                              (self.ui.label_ssa_char, cav_results.ssa_characterized),
                              (self.ui.label_tune_cavity, cav_results.is_tuned),
                              (self.ui.label_measure_8pi9,
                               cav_results.eightpiovernine_frequency_measured),
                              (self.ui.label_cavity_calibration, cav_results.cavity_calibration_run),
                              (self.ui.label_piezo_withrf, cav_results.piezo_withrf_checked),
                              (self.ui.label_selap_rampup, cav_results.onehourrun_complete),
                              (self.ui.label_overall_completion, overall_completion_status)]

        for label, status in label_status_pairs:
            label.setText(status_map[status].message)
            label.setStyleSheet(status_map[status].stylesheet)

    def update_selection(self):
        self.save_results()

        current_decarad = self.ui.pick_decarad.currentText()
        P = "RADM:SYS0:{decarad}00".format(decarad=current_decarad)
        self.ui.button_decaradgui.macros = ["P={pstring}".format(pstring=P),
                                            "M={mstring}".format(mstring=current_decarad)]

        self.current_cm: CommissioningCryomodule = COMMISSIONING_CRYOMODULE_OBJECTS[
            self.ui.pick_cm.currentText()]
        self.current_cm.decarad = Decarad(int(self.ui.pick_decarad.currentText()))
        self.current_cavity: CommissioningCavity = self.current_cm.cavities[int(self.ui.pick_cavity.currentText())]
        self.current_cavity.connect_to_decarad()

        self.load_results()

        self.populate_status_labels()

        # button_interlockoverview is an PyDMEDMDisplaybutton
        self.ui.button_interlockoverview.macros = [self.macro_string]

        self.ui.button_striptools.commands = [
            'srf_stavDisplayCfg.py st cmcryos {prefix}; StripTool $STRIP_CONFIGFILE_DIR/srf_cmcryos.stp'.format(
                prefix=self.current_cm.pvPrefix[:-2])
        ]

        self.update_rf_controls()

        plot_update_map = {util.STEPPERTEMP_PLOT_KEY: self.current_cm.stepper_temp_PVs,
                           util.HOMDS_PLOT_KEY: self.current_cm.hom_ds_PVs,
                           util.HOMUS_PLOT_KEY: self.current_cm.hom_us_PVs,
                           util.CPLRTOP_PLOT_KEY: self.current_cm.coupler_top_PVs,
                           util.CPLRBOT_PLOT_KEY: self.current_cm.coupler_bot_PVs,
                           util.FREQUENCY_PLOT_KEY: self.current_cm.detune_PVs,
                           util.DECARAD_PLOT_KEY: self.current_cm.decarad_PVs,
                           util.CMVACUUM_PLOT_KEY: self.current_cm.vacuumPVs,
                           util.CRYOSIGNALS_PLOT_KEY: self.current_cm.cryo_signal_PVs,
                           util.DETUNE_PLOT_KEY: self.current_cavity.tuning_pvs}

        self.time_plot_updater.updatePlots(plot_update_map)

        self.waveform_plot_updater.updatePlot(util.RFWAVEFORM_PLOT_KEY,
                                              self.current_cavity.waveformplot_channelpairs)

        self.current_cavity.detune_best_PV.clear_callbacks()
        self.current_cavity.detune_best_PV.add_callback(self.detune_callback)
        self.tuner_window.ui.detune_label.channel = self.current_cavity.detune_best_PV.pvname

    def detune_callback(self, value, **kwargs):
        est_steps = value * (util.ESTIMATED_STEPS_PER_HZ_HL
                             if self.current_cm.isHarmonicLinearizer
                             else util.ESTIMATED_STEPS_PER_HZ)
        self.tuner_window.ui.estimated_steps_label.setText(str(int(est_steps)))

    def des_step_changed(self):
        des_steps = int(self.tuner_window.ui.step_des_line_edit.text())
        self.current_cavity.steppertuner.move(des_steps,
                                              maxSteps=util.STEPPER_MAX_STEPS,
                                              speed=scLinacUtils.MAX_STEPPER_SPEED)

    def update_rf_controls(self):
        # TODO implement microphonics measurement (or connect button to microphonics GUI)
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

    def run_piezo_prerf_check(self):
        self.current_cavity.turnOff()
        piezo = self.current_cavity.piezo
        piezo.enable_PV.put(util.PIEZO_ENABLE_VALUE)
        piezo.feedback_mode_PV.put(util.PIEZO_MANUAL_VALUE)
        # set piezo DC voltage offset to 0V
        piezo.dc_setpoint_PV.put(0)
        # run the test script
        piezo.prerf_run_check_PV.put(1)

        while piezo.prerf_check_status_PV.value == util.PIEZO_SCRIPT_RUNNING_VALUE:
            sleep(1)
        if piezo.prerf_check_status_PV.value != util.PIEZO_SCRIPT_COMPLETE_VALUE:
            raise util.PiezoError('Piezo pre-rf test script has exited with status \'crash\' ')

        if (piezo.prerf_cha_status_PV.value == util.PIEZO_PRERF_CHECKOUT_STATUS_VALUE
                and piezo.prerf_chb_status_PV == util.PIEZO_PRERF_CHECKOUT_STATUS_VALUE):
            self.current_cavity.results.piezo_capacitance_a = piezo.capacitance_a_PV.value
            self.current_cavity.results.piezo_capacitance_b = piezo.capacitance_b_PV.value
            self.current_cavity.results.piezo_prerf_checked = True

    def run_piezo_withrf_check(self):
        # make sure the RF is off
        self.current_cavity.turnOff()
        self.current_cavity.ssa.turnOn()
        # set desired amplitude to 5MV
        self.current_cavity.selAmplitudeDesPV.put(5)
        self.current_cavity.rfModeCtrlPV.put(scLinacUtils.RF_MODE_SEL)
        self.current_cavity.turnOn()
        piezo = self.current_cavity.piezo
        piezo.enable_PV.put(util.PIEZO_ENABLE_VALUE)
        piezo.feedback_mode_PV.put(util.PIEZO_MANUAL_VALUE)
        # verify that RFS detune is <100Hz
        if (self.current_cavity.detune_rfs_PV.severity == 3
                or abs(self.current_cavity.detune_rfs_PV.value) > 100):
            raise util.PiezoError('Detuning is invalid or larger than 100Hz')
        # run the test script
        piezo.withrf_run_check_PV.put(1)

        while piezo.withrf_check_status_PV.value == util.PIEZO_SCRIPT_RUNNING_VALUE:
            sleep(1)
        if piezo.withrf_check_status_PV.value != util.PIEZO_SCRIPT_COMPLETE_VALUE:
            raise util.PiezoError('Piezo with-rf test script has exited with status \'crash\' ')

        self.current_cavity.results.piezo_amplifiergain_a = piezo.amplifiergain_a_PV.value
        self.current_cavity.results.piezo_amplifiergain_b = piezo.amplifiergain_b_PV.value
        piezo.withrf_push_dfgain_PV.put(1)
        piezo.withrf_save_dfgain_PV.put(1)
        self.current_cavity.results.piezo_detune_gain = piezo.detunegain_new_PV.value
        self.current_cavity.results.piezo_withrf_checked = True

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
                raise

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
            make_error_popup('SSA calibration failed', ssa_expert_button, e, self.ssa_actionbutton_clicked)
        self.save_results()

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

    def piezo_prerf_actionbutton_clicked(self, qmessagebox: QMessageBox):
        clickedbutton = qmessagebox.clickedButton()
        if qmessagebox.buttonRole(clickedbutton) == QMessageBox.AcceptRole:
            self.current_cavity.results.piezo_capacitance_a = self.current_cavity.piezo.capacitance_a_PV.value
            self.current_cavity.results.piezo_capacitance_b = self.current_cavity.piezo.capacitance_b_PV.value
            self.current_cavity.results.piezo_prerf_checked = True
        self.populate_status_labels()

    def piezo_withrf_actionbutton_clicked(self, qmessagebox: QMessageBox):
        clickedbutton = qmessagebox.clickedButton()
        if qmessagebox.buttonRole(clickedbutton) == QMessageBox.AcceptRole:
            self.current_cavity.results.piezo_amplifiergain_a = self.current_cavity.piezo.amplifiergain_a_PV.value
            self.current_cavity.results.piezo_amplifiergain_b = self.current_cavity.piezo.amplifiergain_b_PV.value
            self.current_cavity.piezo.withrf_push_dfgain_PV.put(1)
            self.current_cavity.piezo.withrf_save_dfgain_PV.put(1)
            self.current_cavity.results.piezo_detune_gain = self.current_cavity.piezo.detunegain_new_PV.value
            self.current_cavity.results.piezo_withrf_checked = True
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
            make_error_popup('Cavity calibration failed', cavity_expert_button, e,
                             self.cavity_actionbutton_clicked)

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

        self.current_cavity.rack.freq_search_low_PV.put(util.FREQ_SEARCH_LOW)
        self.current_cavity.rack.freq_search_high_PV.put(util.FREQ_SEARCH_HIGH)
        self.current_cavity.rack.freq_search_rms_thresh_PV.put(util.FREQ_SEARCH_RMS_THRESH)
        self.current_cavity.rack.freq_search_modeoverlap_PV.put(util.FREQ_SEARCH_MODEOVERLAP)

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
            make_error_popup(title='Error finding 8pi/9 frequency', expert_edmbutton=freq_edmbutton,
                             exception=e, action_func=self.freq_actionbutton_clicked)

    def piezo_prerf_button_pressed(self):
        try:
            self.run_piezo_prerf_check()
        except util.PiezoError as e:
            piezo_prerf_edmbutton = self.make_edmbutton('$TOOLS/edm/display/llrf/rf_srf_char_embed_pzt.edl')
            make_error_popup(title='Error during piezo pre-rf check', expert_edmbutton=piezo_prerf_edmbutton,
                             exception=e, action_func=self.piezo_prerf_actionbutton_clicked)

    def piezo_withrf_button_pressed(self):
        try:
            self.run_piezo_withrf_check()
        except (util.PiezoError, scLinacUtils.SSAPowerError) as e:
            piezo_withrf_edmbutton = self.make_edmbutton('$TOOLS/edm/display/llrf/rf_srf_char_embed_pzt_rf.edl')
            make_error_popup(title='Error during piezo with-rf check', expert_edmbutton=piezo_withrf_edmbutton,
                             exception=e, action_func=self.piezo_withrf_actionbutton_clicked)

    def load_results(self):
        with open('results/cryomodule_results.json', 'r+') as f:
            data = json.load(f)
            if self.current_cm.name in data:
                self.current_cm.results.__dict__.update(data[self.current_cm.name])
        with open('results/cavity_results.json', 'r+') as f:
            data = json.load(f)
            if self.current_cm.name in data:
                cav_data = data[self.current_cm.name]
                # required precondition: keys in cav_data are ints 1 through 8
                if str(self.current_cavity.number) in cav_data:
                    self.current_cavity.results.__dict__.update(cav_data[str(self.current_cavity.number)])

    def save_results(self):
        if not self.current_cm:
            return

        fd = util.acquireLock()

        with open('results/cryomodule_results.json', 'r+') as f:
            data = json.load(f)

            data[self.current_cm.name] = self.current_cm.results.__dict__
            f.seek(0)
            json.dump(data, f)
            f.truncate()
        with open('results/cavity_results.json', 'r+') as f:
            data = json.load(f)
            if self.current_cm.name not in data:
                data[self.current_cm.name] = {cav_number: {} for cav_number in self.current_cm.cavities.keys()}
            data[self.current_cm.name][self.current_cavity.number] = self.current_cavity.results.__dict__
            f.seek(0)
            json.dump(data, f)
            f.truncate()
        util.releaseLock(fd)
