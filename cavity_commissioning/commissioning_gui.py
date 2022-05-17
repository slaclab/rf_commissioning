import dataclasses
import json
import sys
import warnings
from datetime import datetime, timedelta
from functools import partial
from os import path
from threading import Lock
from time import sleep
from typing import Optional

from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QMessageBox
from edmbutton import PyDMEDMDisplayButton
from epics.ca import CASeverityException
from pydm import Display
from qtpy.QtCore import Qt, Signal as signal, Slot as slot

import commissioningUtilities as utils
import lcls_tools.superconducting.scLinacUtils as scLinacUtils
from commissioningLinac import (ALL_CRYOMODULES, COMMISSIONING_CRYOMODULE_OBJECTS, CommissioningCavity,
                                CommissioningCryomodule, Decarad)
from lcls_tools.common.pydm_tools.displayUtils import make_error_popup, make_info_popup, showDisplay
from lcls_tools.common.pydm_tools.pydmPlotUtil import (TimePlotParams,
                                                       TimePlotUpdater,
                                                       WaveformPlotParams,
                                                       WaveformPlotUpdater)
from lcls_tools.common.pyepics_tools import pyepicsUtils

warnings.filterwarnings("ignore", category=RuntimeWarning)


class GuidedCommissioningScreens(Display):
    non_zero_rad_signal = signal(str)
    rad_exceeded_signal = signal(str)
    success_signal = signal(str)
    change_max_ades_signal = signal(float)
    piezo_pre_rf_failed = signal(str)

    def __init__(self, parent=None, args=None):
        super(GuidedCommissioningScreens, self).__init__(parent=parent, args=args)

        self.pathHere = path.dirname(sys.modules[self.__module__].__file__)

        self.mutex = Lock()

        self.current_cm: Optional[CommissioningCryomodule] = None
        self.current_cavity: Optional[CommissioningCavity] = None
        self.current_pvprefix = None

        self.setup_combo_boxes()

        self.rf_controls_window = None

        self.live_signals_window = None
        self.ui.button_livesignals.clicked.connect(self.live_signal_button_clicked)

        self.tuner_window = None
        self.waveform_plot_updater = None
        self.time_plot_updater = TimePlotUpdater({})

        self.update_cavity()
        self.update_decarad()

        self.ui.button_piezo_prerf.clicked.connect(self.piezo_prerf_button_pressed)
        self.ui.button_ssa_char.clicked.connect(self.ssa_calibration_button_pushed)
        self.ui.button_cavity_calibration.clicked.connect(partial(self.cavity_calibration_button_pushed, 3e7, 5e7))
        self.ui.button_measure_8pi9.clicked.connect(self.freq_scan_button_pressed)
        self.ui.button_piezo_withrf.clicked.connect(self.piezo_withrf_button_pressed)

        self.ui.button_tune_cavity.clicked.connect(self.tune_cavity)

        self.ui.button_selap_rampup.clicked.connect(self.selap_button_pressed)

        self.non_zero_rad_signal.connect(self.handle_non_zero_rad, Qt.QueuedConnection)
        self.rad_exceeded_signal.connect(self.handle_rad_exceeded, Qt.QueuedConnection)
        self.change_max_ades_signal.connect(self.set_ades_max_srf_PV, Qt.QueuedConnection)

        self.success_signal.connect(self.handle_success)
        self.piezo_pre_rf_failed.connect(self.handle_piezo_pre_rf_fail, Qt.QueuedConnection)

        self.selap_timer = QTimer()
        self.selap_timer.timeout.connect(self.end_selap)

        self.success_popup: Optional[QMessageBox] = None

    @slot(str)
    def handle_non_zero_rad(self, message):
        if not self.current_cavity.non_zero_rad_flagged:
            make_info_popup(message)
            self.current_cavity.non_zero_rad_flagged = True

    @slot(str)
    def handle_rad_exceeded(self, message):
        if not self.current_cavity.rad_exceeded_flagged:
            make_info_popup(message)
            self.current_cavity.rad_exceeded_flagged = True

    @slot(str)
    def handle_success(self, message):
        if not self.success_popup:
            self.success_popup = make_info_popup(message)
        else:
            self.success_popup.setText(message)
            self.success_popup.exec()

    @slot(float)
    def set_ades_max_srf_PV(self, new_max):
        self.current_cavity.ades_max_srf_PV.put(new_max)

    @slot(str)
    def handle_piezo_pre_rf_fail(self, message):
        piezo_prerf_edmbutton = self.make_edmbutton('$TOOLS/edm/display/llrf/rf_srf_char_embed_pzt.edl')
        make_error_popup(title='Error during piezo pre-rf check',
                         expert_edmbutton=piezo_prerf_edmbutton,
                         exception=message,
                         action_func=self.piezo_prerf_actionbutton_clicked)

    def check_nonzero_rad(self, severity):
        max_avg_dose = self.current_cm.decarad.max_avg_dose
        if (severity == pyepicsUtils.EPICS_INVALID_VAL or max_avg_dose == 0
                or self.current_cavity.non_zero_rad_flagged):
            return

        if utils.RADIATION_LIMIT > max_avg_dose > 0:

            threshold = (utils.GRADIENT_THRESHOLD_RADLIMIT
                         * self.current_cavity.length)
            new_max = min(threshold, self.current_cavity.ades_max_srf_PV.value)
            self.change_max_ades_signal.emit(new_max)

            if self.current_cavity.selAmplitudeActPV.value <= threshold:
                self.current_cavity.results.commissioned_amplitude = threshold
                self.non_zero_rad_signal.emit('Field emission detected. Proceed with'
                                              ' caution without exceeding {thresh} MV.'
                                              .format(thresh=threshold))

            else:
                self.current_cavity.results.commissioned_amplitude = self.current_cavity.selAmplitudeDesPV.value
                self.non_zero_rad_signal.emit('Field emission detected above {thresh} MV.'
                                              ' Please stop.'.format(thresh=threshold))
            self.current_cavity.non_zero_rad_flagged = True

    def check_rad_exceeded(self, severity):
        max_avg_dose = self.current_cm.decarad.max_avg_dose
        if (severity == pyepicsUtils.EPICS_INVALID_VAL or max_avg_dose == 0
                or self.current_cavity.rad_exceeded_flagged):
            return
        if max_avg_dose >= utils.RADIATION_LIMIT:
            self.change_max_ades_signal.emit(self.current_cavity.selAmplitudeDesPV.value)
            self.rad_exceeded_signal.emit('Radiation exceeds {limit}mR/hr. Please stop.'
                                          .format(limit=utils.RADIATION_LIMIT))

            self.current_cavity.rad_exceeded_flagged = True

    def check_radiation(self, severity, **kwargs):
        self.check_nonzero_rad(severity)
        self.check_rad_exceeded(severity)

    def connect_tuner_window(self):
        self.tuner_window.ui.button_save_cold_freq.clicked.connect(self.cold_freq_button_pressed)
        self.tuner_window.ui.step_des_line_edit.returnPressed.connect(self.des_step_changed)
        self.tuner_window.ui.button_replace.clicked.connect(self.replace_button_clicked)
        self.tuner_window.ui.button_add.clicked.connect(self.add_button_clicked)
        self.tuner_window.ui.button_mark_tuned.clicked.connect(self.tuned_button_clicked)

    def live_signal_button_clicked(self):
        if not self.live_signals_window:
            self.live_signals_window = Display(ui_filename=self.getPath("gui/live_signals.ui"))
            self.setup_plots()
            self.update_cavity_plots()
            self.update_decarad_plot()
        showDisplay(self.live_signals_window)

    def setup_plots(self):
        ui = self.live_signals_window.ui
        time_plot_updater = {
            utils.STEPPERTEMP_PLOT_KEY  : TimePlotParams(plot=ui.plot_steppertemps,
                                                         formLayout=ui.stepper_form),
            utils.HOMUS_PLOT_KEY        : TimePlotParams(plot=ui.plot_homus_temp,
                                                         formLayout=ui.up_hom_form),
            utils.HOMDS_PLOT_KEY        : TimePlotParams(plot=ui.plot_homds_temp,
                                                         formLayout=ui.down_hom_form),
            utils.CPLRTOP_PLOT_KEY      : TimePlotParams(plot=ui.plot_couplertop_temp,
                                                         formLayout=ui.coup_top_form),
            utils.CPLRBOT_PLOT_KEY      : TimePlotParams(plot=ui.plot_couplerbot_temp,
                                                         formLayout=ui.coup_bot_hom),
            utils.CMVACUUM_PLOT_KEY     : TimePlotParams(plot=ui.plot_cmvacuum,
                                                         formLayout=ui.vacuum_form),
            utils.CRYOSIGNALS_PLOT_KEY  : TimePlotParams(plot=ui.plot_cryosignals,
                                                         formLayout=ui.cryo_form),
            utils.SINGLE_CAVITY_PLOT_KEY: TimePlotParams(plot=ui.plot_single_cavity_overview,
                                                         formLayout=ui.single_cav_form),
            utils.DECARAD_PLOT_KEY      : TimePlotParams(plot=ui.plot_decarad,
                                                         formLayout=ui.decarad_form)
        }
        self.time_plot_updater = TimePlotUpdater(time_plot_updater)

    def ui_filename(self):
        return 'gui/commissioning.ui'

    def getPath(self, fileName):
        return path.join(self.pathHere, fileName)

    def tune_cavity(self):
        try:
            if not self.tuner_window:
                self.tuner_window = Display(ui_filename=self.getPath("gui/tuning.ui"))
                self.time_plot_updater.plotParams[utils.DETUNE_PLOT_KEY] = TimePlotParams(
                        plot=self.tuner_window.ui.tuning_plot, formLayout=self.tuner_window.ui.plot_layout)
                self.connect_tuner_window()
            self.update_tuner_window()
            self.current_cavity.setup_tuning()
            self.current_cavity.steppertuner.connect_callback()
        except (utils.DetuneError, pyepicsUtils.PVInvalidError) as e:
            tuner_expert_button = self.make_edmbutton('$TOOLS/edm/display/llrf/rf_srf_tuner_embed.edl')
            make_error_popup('Detune PV invalid', tuner_expert_button, e, None)

        showDisplay(self.tuner_window)

    def setup_combo_boxes(self):
        self.ui.testlead.addItems(utils.TESTLEAD_LIST)
        self.ui.testlead.currentIndexChanged.connect(self.testlead_selected)

        self.ui.pick_cavity.currentIndexChanged.connect(self.update_cavity)

        self.ui.pick_decarad.currentIndexChanged.connect(self.update_decarad)

        self.ui.pick_cm.addItems(ALL_CRYOMODULES)

        self.ui.pick_cm.currentIndexChanged.connect(self.update_cavity)

    def populate_status_labels(self):
        @dataclasses.dataclass
        class StatusMap:
            message: str
            color: str

            @property
            def stylesheet(self):
                return 'color: {color};'.format(color=self.color)

        status_map = {True : StatusMap('Complete', 'green'),
                      False: StatusMap('Incomplete', 'red')}

        cm_results = self.current_cm.results
        cav_results = self.current_cavity.results
        overall_completion_status = (cm_results.magnet_checked
                                     and cav_results.piezo_prerf_checked
                                     and cav_results.ssa_characterized
                                     and cav_results.is_tuned
                                     and cav_results.eight_pi_nine_freq_measured
                                     and cav_results.cavity_calibration_run
                                     and cav_results.piezo_withrf_checked
                                     and cav_results.onehourrun_complete
                                     and cm_results.unit_test_complete
                                     )

        label_status_pairs = [(self.ui.label_piezo_prerf, cav_results.piezo_prerf_checked),
                              (self.ui.label_ssa_char, cav_results.ssa_characterized),
                              (self.ui.label_tune_cavity, cav_results.is_tuned),
                              (self.ui.label_measure_8pi9,
                               cav_results.eight_pi_nine_freq_measured),
                              (self.ui.label_cavity_calibration, cav_results.cavity_calibration_run),
                              (self.ui.label_piezo_withrf, cav_results.piezo_withrf_checked),
                              (self.ui.label_selap_rampup, cav_results.onehourrun_complete),
                              (self.ui.label_overall_completion, overall_completion_status)]

        for label, status in label_status_pairs:
            label.setText(status_map[status].message)
            label.setStyleSheet(status_map[status].stylesheet)

    def update_cavity(self):
        self.save_results()

        self.current_cm: CommissioningCryomodule = COMMISSIONING_CRYOMODULE_OBJECTS[
            self.ui.pick_cm.currentText()]
        if self.current_cavity:
            self.current_cavity.steppertuner.step_tot_pv.clear_callbacks()
        self.current_cavity: CommissioningCavity = self.current_cm.cavities[int(self.ui.pick_cavity.currentText())]

        self.load_results()

        self.populate_status_labels()

        self.update_rf_controls()

        self.update_cavity_plots()
        self.update_rf_plots()
        self.update_tuner_plot()

        self.update_tuner_window()

        self.update_interlock()

    def update_decarad(self):
        self.current_cavity.cryomodule.decarad = Decarad(int(self.ui.pick_decarad.currentText()))
        self.ui.indicator_decarad.channel = self.current_cm.decarad.powerStatusPVName
        self.ui.label_decarad_onoff.channel = self.current_cm.decarad.powerStatusPVName
        self.ui.label_decarad_voltage.channel = self.current_cm.decarad.voltageReadbackPVName
        self.ui.button_decarad_on.channel = self.current_cm.decarad.powerControlPVName
        self.ui.button_decarad_off.channel = self.current_cm.decarad.powerControlPVName
        self.current_cavity.connect_to_decarad(self.check_radiation)

        self.update_decarad_plot()

    def update_decarad_plot(self):
        if not self.time_plot_updater:
            return

        timeplot_update_map = {}
        if self.live_signals_window:
            timeplot_update_map = {utils.DECARAD_PLOT_KEY: self.current_cm.decarad_PVs}
        self.time_plot_updater.updatePlots(timeplot_update_map)

    def update_interlock(self):
        # button_interlockoverview is an PyDMEDMDisplaybutton
        self.ui.button_interlockoverview.macros = [self.macro_string]
        self.ui.indicator_interlock.channel = self.current_cavity.interlock_PV.pvname
        self.ui.label_interlock.channel = self.current_cavity.interlock_PV.pvname

    def update_tuner_plot(self):
        if self.tuner_window:
            self.time_plot_updater.updatePlots({utils.DETUNE_PLOT_KEY:
                                                    self.current_cavity.tuning_pvs})

    def update_rf_plots(self):
        if self.rf_controls_window:
            waveformplot_update_map = {utils.RFWAVEFORM_PLOT_KEY: self.current_cavity.waveformplot_channelpairs,
                                       utils.CHEETO_PLOT_KEY    : self.current_cavity.cheetoplot_channelpairs}
            self.waveform_plot_updater.updatePlots(waveformplot_update_map)

    def update_cavity_plots(self):
        if self.live_signals_window:
            timeplot_update_map = {utils.STEPPERTEMP_PLOT_KEY  : self.current_cm.stepper_temp_PVs,
                                   utils.HOMDS_PLOT_KEY        : self.current_cm.hom_ds_PVs,
                                   utils.HOMUS_PLOT_KEY        : self.current_cm.hom_us_PVs,
                                   utils.CPLRTOP_PLOT_KEY      : self.current_cm.coupler_top_PVs,
                                   utils.CPLRBOT_PLOT_KEY      : self.current_cm.coupler_bot_PVs,
                                   utils.CMVACUUM_PLOT_KEY     : self.current_cm.vacuumPVs,
                                   utils.CRYOSIGNALS_PLOT_KEY  : self.current_cm.cryo_signal_PVs,
                                   utils.SINGLE_CAVITY_PLOT_KEY: self.current_cavity.plot_pvs, }

            self.time_plot_updater.updatePlots(timeplot_update_map)

    def update_tuner_window(self):
        if not self.tuner_window:
            return
        self.current_cavity.detune_best_PV.clear_callbacks()
        self.current_cavity.detune_best_PV.add_callback(self.detune_callback)
        ui = self.tuner_window.ui
        ui.detune_label.channel = self.current_cavity.detune_best_PV.pvname
        ui.label_cold_steps.channel = self.current_cavity.steppertuner.steps_cold_landing_pv.pvname
        ui.label_cold_landing_freq.setText(str(self.current_cavity.results.cold_land_freq_2K))
        ui.label_session_steps.setText(str(self.current_cavity.current_steps))
        self.update_tuner_plot()

    def replace_button_clicked(self):
        self.current_cavity.steppertuner.steps_cold_landing_pv.put(self.current_cavity.current_steps)

    def add_button_clicked(self):
        self.current_cavity.steppertuner.steps_cold_landing_pv.put(self.current_cavity.current_steps
                                                                   +
                                                                   self.current_cavity.steppertuner.steps_cold_landing_pv.value)

    def tuned_button_clicked(self):
        self.current_cavity.results.is_tuned = True
        self.save_results()
        self.populate_status_labels()
        self.success_signal.emit("Tuning successful")

    def detune_callback(self, value, **kwargs):
        est_steps = value * (utils.ESTIMATED_STEPS_PER_HZ_HL
                             if self.current_cm.isHarmonicLinearizer
                             else utils.ESTIMATED_STEPS_PER_HZ)
        ui = self.tuner_window.ui
        ui.estimated_steps_label.setText(str(int(est_steps)))
        ui.label_current_freq.setText(str(value + self.current_cavity.frequency))

    def des_step_changed(self):
        des_steps = int(self.tuner_window.ui.step_des_line_edit.text())
        print("Issuing stepper move command")
        self.current_cavity.steppertuner.move(des_steps,
                                              maxSteps=utils.STEPPER_MAX_STEPS,
                                              speed=scLinacUtils.MAX_STEPPER_SPEED)
        print("stepper done moving")
        self.current_cavity.current_steps += des_steps
        self.tuner_window.ui.label_session_steps.setText(str(self.current_cavity.current_steps))

    def update_rf_controls(self):
        # TODO implement microphonics measurement (or connect button to microphonics GUI)
        if not self.rf_controls_window:
            return
        ui = self.rf_controls_window.ui
        ui.button_ssa_on.channel = self.current_cavity.ssa.turnOnPV.pvname
        ui.button_ssa_off.channel = self.current_cavity.ssa.turnOffPV.pvname
        ui.label_ssa_status_rdbk.channel = self.current_cavity.ssa.statusPV.pvname

        ui.combobox_rfmode.channel = self.current_cavity.rfModeCtrlPV.pvname
        ui.label_rfmode_rdbk.channel = self.current_cavity.rfModePV.pvname

        ui.button_rf_on.channel = self.current_cavity.rfControlPV.pvname
        ui.button_rf_off.channel = self.current_cavity.rfControlPV.pvname
        ui.label_rfstatus_rdbk.channel = self.current_cavity.rfStatePV.pvname

        ui.spinbox_ades.channel = self.current_cavity.selAmplitudeDesPV.pvname
        ui.label_ades_rdbk.channel = self.current_cavity.selAmplitudeDesPV.pvname

        ui.lineedit_srfmax.channel = self.current_cavity.ades_max_srf_PV
        ui.label_srfmax_rdbk.channel = self.current_cavity.ades_max_srf_PV
        ui.label_amax_rdbk.channel = self.current_cavity.ades_max_PV.pvname

        ui.spinbox_selphaseoffset.channel = self.current_cavity.sel_phaseoffset_PVName
        ui.label_selphaseoffset_rdbk.channel = self.current_cavity.sel_phaseoffset_rdbk_PVName
        ui.label_forward_pwr.channel = self.current_cavity.forward_pwr_PVName

        ui.indicator_phas_high.channel = self.current_cavity.feedback_phase_high_PVName
        ui.indicator_phas_low.channel = self.current_cavity.feedback_phase_low_PVName
        ui.indicator_amp_high.channel = self.current_cavity.feedback_amplitude_high_PVName
        ui.indicator_amp_low.channel = self.current_cavity.feedback_amplitude_low_PVName

        ui.label_phas_high.channel = self.current_cavity.feedback_phase_high_PVName
        ui.label_phas_low.channel = self.current_cavity.feedback_phase_low_PVName
        ui.label_amp_high.channel = self.current_cavity.feedback_amplitude_high_PVName
        ui.label_amp_low.channel = self.current_cavity.feedback_amplitude_low_PVName

        ui.spinbox_reactive_power.channel = self.current_cavity.ssa_reactive_power_fraction_PV.pvname
        ui.label_reactive_power_rdbk.channel = self.current_cavity.ssa_reactive_power_fraction_PV.pvname

        ui.label_max_amplitude.channel = self.current_cavity.acceptancetest_max_amplitude_PVName
        ui.label_useable_amplitude.channel = self.current_cavity.acceptancetest_useable_amplitude_PVName
        ui.label_fe_onset.channel = self.current_cavity.acceptancetest_fe_onset_PVName
        ui.label_cavity_limitation.channel = self.current_cavity.acceptancetest_cavity_limitation_PVName

        ui.button_onehour_done.clicked.connect(self.onehour_done_button_pressed)
        ui.button_open_edm_rfcontrols.macros = [self.macro_string]

    def onehour_done_button_pressed(self):
        self.current_cavity.results.onehourrun_complete = True
        self.current_cavity.results.commissioned_amplitude = self.current_cavity.ades_max_srf_PV.value
        self.save_results()
        self.current_cavity.turnOff()
        self.success_signal.emit("One hour run complete")

    def update_stepsize(self):
        stepsize = float(self.rf_controls_window.ui.lineedit_ades_stepsize.text())
        self.rf_controls_window.ui.spinbox_ades.setSingleStep(stepsize)

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

    def trigger_pass(self, value, **kwargs):
        piezo = self.current_cavity.piezo
        if value == utils.PIEZO_SCRIPT_RUNNING_VALUE:
            print("Test is running")
        elif value == utils.PIEZO_SCRIPT_COMPLETE_VALUE:
            print("Test finished running")
            piezo.prerf_test_status_pv.clear_callbacks()
            if (piezo.prerf_cha_status_PV.value == utils.PIEZO_PRERF_CHECKOUT_PASS_VALUE
                    and piezo.prerf_chb_status_PV.value == utils.PIEZO_PRERF_CHECKOUT_PASS_VALUE):
                self.current_cavity.results.piezo_capacitance_a = piezo.capacitance_a_PV.value
                self.current_cavity.results.piezo_capacitance_b = piezo.capacitance_b_PV.value
                self.current_cavity.results.piezo_prerf_checked = True
                self.populate_status_labels()
                self.save_results()
                self.success_signal.emit("Piezo pre-rf check complete and successful")

            else:
                self.piezo_pre_rf_failed.emit("Piezo pre-rf test failed")
        else:
            piezo.prerf_test_status_pv.clear_callbacks()
            self.piezo_pre_rf_failed.emit("Piezo pre-rf test failed")

    def trigger_start_test(self, value, **kwargs):
        if value == 0:
            print("piezo dc offset at 0")
            self.current_cavity.piezo.prerf_test_status_pv.add_callback(self.trigger_pass)
            self.current_cavity.piezo.prerf_test_start_pv.put(1)
            self.current_cavity.piezo.dc_setpoint_PV.clear_callbacks()

    def trigger_dc_zero(self, value, **kwargs):
        if value == utils.PIEZO_MANUAL_VALUE:
            print("Piezo in manual")
            self.current_cavity.piezo.dc_setpoint_PV.add_callback(self.trigger_start_test)
            self.current_cavity.piezo.dc_setpoint_PV.put(0)
            self.current_cavity.piezo.feedback_mode_PV.clear_callbacks()

    def trigger_manual(self, value, **kwargs):
        if value == utils.PIEZO_ENABLE_VALUE:
            print("Piezo enabled")
            self.current_cavity.piezo.feedback_mode_PV.add_callback(self.trigger_dc_zero)
            self.current_cavity.piezo.feedback_mode_PV.put(utils.PIEZO_MANUAL_VALUE)
            self.current_cavity.piezo.enable_PV.clear_callbacks()

    def run_piezo_prerf_check(self):
        self.current_cavity.turnOff()
        self.current_cavity.piezo.enable_PV.add_callback(self.trigger_manual)
        self.current_cavity.piezo.enable_PV.put(utils.PIEZO_ENABLE_VALUE)

    def run_piezo_prerf_check1(self):
        self.current_cavity.turnOff()
        piezo = self.current_cavity.piezo
        piezo.enable_PV.put(utils.PIEZO_ENABLE_VALUE)
        piezo.feedback_mode_PV.put(utils.PIEZO_MANUAL_VALUE)
        # set piezo DC voltage offset to 0V
        piezo.dc_setpoint_PV.put(0)
        # run the test script
        piezo.prerf_test_start_pv.put(1)

        print("waiting 5 seconds for piezo tuner test to start")
        sleep(5)

        while piezo.prerf_test_status_pv.value == utils.PIEZO_SCRIPT_RUNNING_VALUE:
            print("waiting for piezo tuner test to finish running", datetime.now())
            sleep(1)

        print("waiting 5s for piezo test status to update")
        sleep(5)

        if piezo.prerf_test_status_pv.value != utils.PIEZO_SCRIPT_COMPLETE_VALUE:
            raise utils.PiezoError('Piezo pre-rf test script was not successful')

        if (piezo.prerf_cha_status_PV.value == utils.PIEZO_PRERF_CHECKOUT_PASS_VALUE
                and piezo.prerf_chb_status_PV.value == utils.PIEZO_PRERF_CHECKOUT_PASS_VALUE):
            self.current_cavity.results.piezo_capacitance_a = piezo.capacitance_a_PV.value
            self.current_cavity.results.piezo_capacitance_b = piezo.capacitance_b_PV.value
            self.current_cavity.results.piezo_prerf_checked = True
            print("Piezo pre-rf check complete and successful")

        else:
            raise utils.PiezoError("Piezo test unsuccessful")

    def run_piezo_withrf_check(self):
        print("turning RF off")
        self.current_cavity.turnOff()

        print("turning SSA on")
        self.current_cavity.ssa.turnOn()

        print("setting ADES to 5MV")
        self.current_cavity.selAmplitudeDesPV.put(5)

        print("setting cavity to SEL")
        self.current_cavity.rfModeCtrlPV.put(scLinacUtils.RF_MODE_SEL)

        print("turning RF on")
        self.current_cavity.turnOn()
        piezo = self.current_cavity.piezo

        print("waiting 5s for the detune to catch up")
        sleep(5)

        print("enabling piezo")
        piezo.enable_PV.put(utils.PIEZO_ENABLE_VALUE)

        print("setting piezo to manual")
        piezo.feedback_mode_PV.put(utils.PIEZO_MANUAL_VALUE)

        print("verifying that RFS detune is <100Hz")
        if (self.current_cavity.detune_rfs_PV.severity == 3
                or abs(self.current_cavity.detune_rfs_PV.value) > 100):
            raise utils.PiezoError('Detuning is invalid or larger than 100Hz')

        print("running piezo test script")
        piezo.withrf_run_check_PV.put(1, waitForPut=False)

        print("waiting 5s for piezo test script to run")
        sleep(5)

        while piezo.withrf_check_status_PV.value == utils.PIEZO_SCRIPT_RUNNING_VALUE:
            print("waiting for piezo test script to finish running", datetime.now())
            sleep(1)
        if piezo.withrf_check_status_PV.value != utils.PIEZO_SCRIPT_COMPLETE_VALUE:
            raise utils.PiezoError('Piezo with-rf test script has exited with status \'crash\' ')

        self.current_cavity.results.piezo_amplifiergain_a = piezo.amplifiergain_a_PV.value
        self.current_cavity.results.piezo_amplifiergain_b = piezo.amplifiergain_b_PV.value

        print("pushing and saving gain")
        piezo.withrf_push_dfgain_PV.put(1, waitForPut=False)
        piezo.withrf_save_dfgain_PV.put(1, waitForPut=False)

        self.current_cavity.results.piezo_detune_gain = piezo.detunegain_new_PV.value
        self.current_cavity.results.piezo_withrf_checked = True

    def run_ssa_calibration(self, drivemax=0.8, attemptnumber=1):
        print("trying calibration at {drive}; attempt #{attempt}".format(drive=drivemax,
                                                                         attempt=attemptnumber))
        self.current_cavity.ssa_maxdrive_PV.put(drivemax)
        try:
            self.current_cavity.ssa.runCalibration()
            self.current_cavity.results.ssa_maxdrive = drivemax
            self.current_cavity.results.ssa_characterized = True
        except scLinacUtils.SSACalibrationError:
            print("calibration failed, lowering drive")
            if attemptnumber <= 3:
                self.run_ssa_calibration(drivemax - 0.05, attemptnumber + 1)
            else:
                raise

    def ssa_calibration_button_pushed(self):
        try:
            self.run_ssa_calibration()
            self.populate_status_labels()
            self.save_results()
            self.success_signal.emit("SSA calibration successful")
        except (scLinacUtils.SSACalibrationError, scLinacUtils.SSAPowerError,
                pyepicsUtils.PVInvalidError) as e:
            print(e)
            ssa_expert_button = PyDMEDMDisplayButton()
            ssa_expert_button.filenames = ['$TOOLS/edm/display/llrf/rf_srf_char_embed_ssa.edl']
            ssa_expert_button.macros = self.macro_string
            ssa_expert_button.setText('Open SSA EDM expert screen')
            ssa_expert_button.setDefault(True)
            make_error_popup('SSA calibration failed', ssa_expert_button, e, self.ssa_actionbutton_clicked)

    def ssa_actionbutton_clicked(self, qmessagebox: QMessageBox):
        clickedbutton = qmessagebox.clickedButton()
        if qmessagebox.buttonRole(clickedbutton) == QMessageBox.AcceptRole:
            self.current_cavity.results.ssa_characterized = True
            self.current_cavity.results.ssa_maxdrive = self.current_cavity.ssa_maxdrive_PV.value
        self.populate_status_labels()

    def freq_actionbutton_clicked(self, qmessagebox: QMessageBox):
        clickedbutton = qmessagebox.clickedButton()
        if qmessagebox.buttonRole(clickedbutton) == QMessageBox.AcceptRole:
            self.current_cavity.results.eight_pi_nine_freq_measured = True
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

    def cavity_calibration_button_pushed(self, loadedQLowerlimit, loadedQUpperlimit):
        try:
            if not self.rf_controls_window:
                self.setup_rf_window()
            self.rf_controls_window.show()
            self.current_cavity.runCalibration(loadedQLowerlimit, loadedQUpperlimit)
            self.current_cavity.results.fpc_qext_cold = self.current_cavity.measuredQLoadedPV.value
            self.current_cavity.results.probe_qext_value = self.current_cavity.measured_probe_qext_PV.value
            self.current_cavity.results.cavity_calibration_run = True
            self.populate_status_labels()
            self.save_results()
            self.success_signal.emit("Cavity calibration successful")
        except (
                scLinacUtils.CavityQLoadedCalibrationError, scLinacUtils.CavityScaleFactorCalibrationError,
                TypeError, CASeverityException, pyepicsUtils.PVInvalidError) as e:
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
            self.current_cavity.results.fpc_qext_cold = self.current_cavity.measuredQLoadedPV.value
            self.current_cavity.results.probe_qext_value = self.current_cavity.measured_probe_qext_PV.value
        self.populate_status_labels()

    def measure_8pi9mode(self):
        other_cavities = list(self.current_cavity.rack.cavities.keys())
        other_cavities.remove(self.current_cavity.number)

        print("removing other cavities from rack frequency scan")
        for cavity in other_cavities:
            self.current_cm.cavities[cavity].freq_search_select_PV.put(0)

        print("selecting current cavity for rack frequency scan")
        self.current_cavity.freq_search_select_PV.put(1)

        self.current_cavity.rack.freq_search_low_PV.put(utils.FREQ_SEARCH_LOW)
        self.current_cavity.rack.freq_search_high_PV.put(utils.FREQ_SEARCH_HIGH)
        self.current_cavity.rack.freq_search_rms_thresh_PV.put(utils.FREQ_SEARCH_RMS_THRESH)
        self.current_cavity.rack.freq_search_modeoverlap_PV.put(utils.FREQ_SEARCH_MODEOVERLAP)

        self.current_cavity.rack.freq_search_start_PV.put(1, waitForPut=False)
        print("Waiting 5s for the rack frequency scan to start")
        sleep(5)

        while self.current_cavity.rack.freq_search_status_PV.value == 3:
            print("waiting for scan to finish running")
            sleep(1)
        if self.current_cavity.rack.freq_search_status_PV.value != 5:
            raise utils.FreqSearchError('Frequency search did not exit successfully')
        if (self.current_cavity.freq_search_8pi9_PV.value > -750000
                or self.current_cavity.freq_search_8pi9_PV.value < -850000):
            raise utils.FreqSearchError('8pi/9 frequency outside tolerance')
        self.current_cavity.freq_search_push_PV.put(1, waitForPut=False)
        self.current_cavity.results.eight_pi_nine_freq_measured = True

        self.success_signal.emit("8pi/9 scan successful")

    def testlead_selected(self):
        self.current_cavity.results.test_lead = self.ui.testlead.currentText()
        self.save_results()

    def freq_scan_button_pressed(self):
        try:
            self.measure_8pi9mode()
        except (utils.FreqSearchError, pyepicsUtils.PVInvalidError) as e:
            # TODO check why this does not get pulled up with the correct macros
            freq_edmbutton = self.make_edmbutton('$TOOLS/edm/display/llrf/rf_srf_freq_scan_rack_embed_search.edl')
            make_error_popup(title='Error finding 8pi/9 frequency',
                             expert_edmbutton=freq_edmbutton,
                             exception=e,
                             action_func=self.freq_actionbutton_clicked)
        self.populate_status_labels()
        self.save_results()

    def piezo_prerf_button_pressed(self):
        try:
            self.run_piezo_prerf_check()
            # self.populate_status_labels()
            # self.save_results()
            # self.success_signal.emit("Piezo pre rf check successful")
        except (utils.PiezoError, pyepicsUtils.PVInvalidError) as e:
            piezo_prerf_edmbutton = self.make_edmbutton('$TOOLS/edm/display/llrf/rf_srf_char_embed_pzt.edl')
            make_error_popup(title='Error during piezo pre-rf check',
                             expert_edmbutton=piezo_prerf_edmbutton,
                             exception=e,
                             action_func=self.piezo_prerf_actionbutton_clicked)

    def piezo_withrf_button_pressed(self):
        try:
            self.run_piezo_withrf_check()
            self.populate_status_labels()
            self.save_results()
            self.success_signal.emit("Piezo with rf check successful")
        except (utils.PiezoError, scLinacUtils.SSAPowerError,
                pyepicsUtils.PVInvalidError) as e:
            piezo_withrf_edmbutton = self.make_edmbutton('$TOOLS/edm/display/llrf/rf_srf_char_embed_pzt_rf.edl')
            make_error_popup(title='Error during piezo with-rf check',
                             expert_edmbutton=piezo_withrf_edmbutton,
                             exception=e,
                             action_func=self.piezo_withrf_actionbutton_clicked)

    def cold_freq_button_pressed(self):
        self.current_cavity.results.cold_land_freq_2K = float(self.tuner_window.ui.label_current_freq.text())
        self.tuner_window.ui.label_cold_landing_freq.setText(str(self.current_cavity.results.cold_land_freq_2K))
        self.populate_status_labels()
        self.save_results()

    def end_selap(self):
        try:
            self.current_cavity.selAmplitudeDesPV.put(5)
            self.current_cavity.turnOff()
            self.current_cavity.runCalibration(loadedQLowerlimit=scLinacUtils.LOADED_Q_LOWER_LIMIT,
                                               loadedQUpperlimit=scLinacUtils.LOADED_Q_UPPER_LIMIT)
            self.current_cavity.turnOff()
            self.current_cavity.ssa.turnOff()
            self.save_results()
            self.populate_status_labels()
            self.success_signal.emit('1h run complete')
        except scLinacUtils.CavityQLoadedCalibrationError as e:
            cavity_expert_button = self.make_edmbutton('$TOOLS/edm/display/llrf/rf_srf_char_embed_ramp.edl')
            make_error_popup('Cavity calibration failed', cavity_expert_button, e,
                             self.cavity_actionbutton_clicked)

    def selap_button_pressed(self):
        try:
            if not self.rf_controls_window:
                self.setup_rf_window()
                self.update_rf_plots()

            self.current_cavity.selap_setup()
            showDisplay(self.rf_controls_window)
            make_info_popup('Walk amplitude up to {amax}MV in SELA'.format(amax=self.current_cavity.ades_max_PV.value))
        except (utils.PiezoError, utils.DetuneError, scLinacUtils.SSAPowerError,
                pyepicsUtils.PVInvalidError) as e:
            showDisplay(self.rf_controls_window)
            print(e)
        self.populate_status_labels()
        self.save_results()

    def setup_rf_window(self):
        self.rf_controls_window = Display(ui_filename=self.getPath("gui/rf_controls.ui"))
        self.waveform_plot_updater = WaveformPlotUpdater(
                {utils.RFWAVEFORM_PLOT_KEY:
                     WaveformPlotParams(plot=self.rf_controls_window.ui.waveform_rfsignals),
                 utils.CHEETO_PLOT_KEY    : WaveformPlotParams(
                         plot=self.rf_controls_window.ui.waveform_cheeto)})
        self.rf_controls_window.ui.lineedit_ades_stepsize.returnPressed.connect(self.update_stepsize)
        self.rf_controls_window.ui.button_start_timer.clicked.connect(self.start_timer)
        self.rf_controls_window.ui.button_reset_timer.clicked.connect(self.restart_timer)
        self.rf_controls_window.ui.button_stop_timer.clicked.connect(self.stop_timer)
        self.update_rf_controls()
        self.update_rf_plots()

    def start_timer(self):
        self.selap_timer.start(3600000)
        end_time = datetime.now() + timedelta(hours=1)
        self.rf_controls_window.ui.label_timer.setText("Rampdown will trigger at {time}".format(time=end_time))

    def restart_timer(self):
        self.selap_timer.stop()
        self.start_timer()

    def stop_timer(self):
        self.selap_timer.stop()
        self.rf_controls_window.ui.label_timer.setText("Timer stopped")

    # TODO add people handling
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

        fd = utils.acquireLock()

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
        utils.releaseLock(fd)
