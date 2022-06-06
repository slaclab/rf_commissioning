import dataclasses
import sys
import warnings
from datetime import datetime, timedelta
from functools import partial
from os import path
from threading import Lock
from typing import Callable, Optional

from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QMessageBox, QProgressBar, QPushButton
from edmbutton import PyDMEDMDisplayButton
from pydm import Display
from qtpy.QtCore import Qt, Slot as slot

from commissioningLinac import (ALL_CRYOMODULES, COMMISSIONING_CRYOMODULE_OBJECTS,
                                CommissioningCryomodule, Decarad)
from commissioning_workers import *
from lcls_tools.common.pydm_tools.displayUtils import make_error_popup, make_info_popup, showDisplay
from lcls_tools.common.pydm_tools.pydmPlotUtil import (TimePlotParams,
                                                       TimePlotUpdater,
                                                       WaveformPlotParams,
                                                       WaveformPlotUpdater)
from lcls_tools.common.pyepics_tools import pyepicsUtils

warnings.filterwarnings("ignore", category=RuntimeWarning)


def enable_after_deletion(button: QPushButton, thread: QThread):
    if thread:
        thread.terminate()
        thread.wait()
    button.setEnabled(True)


class GuidedCommissioningScreens(Display):
    rad_error = signal(utils.RadHandler)
    success_signal = signal(str)
    change_max_ades_signal = signal(float)
    
    def ui_filename(self):
        return 'gui/commissioning.ui'
    
    def __init__(self, parent=None, args=None):
        super(GuidedCommissioningScreens, self).__init__(parent=parent, args=args)
        
        self.pathHere = path.dirname(sys.modules[self.__module__].__file__)
        
        self.mutex = Lock()
        
        self.current_cm: Optional[CommissioningCryomodule] = None
        self.current_cavity: Optional[CommissioningCavity] = None
        self.current_pvprefix = None
        
        # These are here because otherwise the thread goes out of scope when the
        # "launch thread" function exits
        self.piezo_pre_rf_thread: QThread = None
        self.ssa_char_thread: QThread = None
        self.tune_thread: QThread = None
        self.large_rack_thread: QThread = None
        self.cav_cal_thread: QThread = None
        self.piezo_with_rf_thread: QThread = None
        self.start_selap_thread: QThread = None
        self.stepper_thread: QThread = None
        self.end_selap_thread: QThread = None
        
        self.setup_combo_boxes()
        
        self.rf_controls_window = None
        
        self.live_signals_window = None
        self.ui.button_livesignals.clicked.connect(self.live_signal_button_clicked)
        
        self.tuner_window = None
        self.waveform_plot_updater = None
        self.time_plot_updater = TimePlotUpdater({})
        self.ui.tuning_button.clicked.connect(self.setup_tuner_window)
        
        self.progressbars = [self.ui.pre_rf_progressbar,
                             self.ui.ssa_char_progressbar,
                             self.ui.tune_progressbar,
                             self.ui.large_rack_progressbar,
                             self.ui.cav_cal_progressbar,
                             self.ui.piezo_with_rf_progressbar,
                             self.ui.selap_progressbar]
        
        self.connect_buttons()
        
        self.rad_error.connect(self.handle_radiation, Qt.QueuedConnection)
        
        self.success_signal.connect(self.handle_success)
        
        self.selap_timer = QTimer()
        self.selap_timer.setSingleShot(True)
        self.selap_timer.timeout.connect(self.launch_end_selap_thread)
        
        self.success_popup: Optional[QMessageBox] = None
        self.rad_popup: Display = None
        
        self.decarads = {"1": Decarad(1), "2": Decarad(2)}
    
    @slot(float)
    def update_amax(self, value):
        self.current_cavity.ades_max_srf_PV.put(value)
    
    def reset_progressbars(self):
        for progressbar in self.progressbars:
            progressbar.setValue(0)
    
    def connect_buttons(self):
        self.ui.button_piezo_prerf.clicked.connect(self.launch_piezo_pre_rf_thread)
        self.ui.button_ssa_char.clicked.connect(self.launch_ssa_char_thread)
        
        self.ui.button_cavity_calibration.clicked.connect(self.setup_rf_window)
        self.ui.button_cavity_calibration.clicked.connect(self.launch_cav_cal_thread)
        
        self.ui.button_measure_8pi9.clicked.connect(self.launch_large_rack_thread)
        self.ui.button_piezo_withrf.clicked.connect(self.launch_piezo_with_rf_thread)
        
        self.ui.button_tune_cavity.clicked.connect(self.setup_tuner_window)
        self.ui.button_tune_cavity.clicked.connect(self.launch_tune_thread)
        
        self.ui.button_selap_rampup.clicked.connect(self.launch_selap_thread)
        self.ui.button_selap_rampup.clicked.connect(self.setup_rf_window)
        
        self.ui.rf_button.clicked.connect(self.setup_rf_window)
    
    def setup_thread(self, worker: Worker,
                     progressBar: QProgressBar,
                     error_handler: Callable, abortButton: QPushButton,
                     startButton: QPushButton,
                     action_desc: Optional[str] = None):
        terminateFunc = partial(enable_after_deletion, startButton, worker)
        worker.started.connect(partial(startButton.setEnabled, False))
        
        worker.finished.connect(terminateFunc)
        worker.finished.connect(self.handle_success)
        worker.finished.connect(print)
        
        if progressBar:
            worker.progress.connect(progressBar.setValue)
        worker.status.connect(self.ui.status_label.setText)
        worker.status.connect(print)
        
        worker.error.connect(error_handler)
        worker.error.connect(self.ui.status_label.setText)
        worker.error.connect(print)
        
        abortButton.clicked.connect(terminateFunc)
        abortButton.clicked.connect(partial(self.ui.status_label.setText,
                                            "termination command sent to {action} thread".format(action=action_desc)))
        worker.start()
    
    @slot(str)
    def handle_selap_error(self, e):
        def abort(qmessagebox: QMessageBox):
            clickedbutton = qmessagebox.clickedButton()
            if qmessagebox.buttonRole(clickedbutton) == QMessageBox.RejectRole:
                enable_after_deletion(self.ui.button_selap_rampup, self.start_selap_thread)
                enable_after_deletion(self.ui.button_selap_rampup, self.end_selap_thread)
        
        showDisplay(self.rf_controls_window)
        popup = QMessageBox()
        popup.setIcon(QMessageBox.Critical)
        popup.setWindowTitle("SELAP Error")
        popup.setText(str(e))
        popup.addButton('Abort automatic setup and set up manually',
                        QMessageBox.RejectRole)
        popup.buttonClicked.connect(partial(abort, popup))
        popup.exec()
    
    def launch_selap_thread(self):
        self.start_selap_thread = StartSELAPWorker(self.current_cavity)
        self.setup_thread(worker=self.start_selap_thread,
                          progressBar=self.ui.selap_progressbar,
                          error_handler=self.handle_selap_error,
                          abortButton=self.ui.selap_abort,
                          action_desc="SELAP setup",
                          startButton=self.ui.button_selap_rampup)
    
    def launch_piezo_with_rf_thread(self):
        self.piezo_with_rf_thread = PiezoWithRFWorker(self.current_cavity)
        self.setup_thread(worker=self.piezo_with_rf_thread,
                          progressBar=self.ui.piezo_with_rf_progressbar,
                          error_handler=self.handle_peizo_with_rf_error,
                          abortButton=self.ui.piezo_with_rf_abort,
                          action_desc="Piezo with RF",
                          startButton=self.ui.button_piezo_withrf)
    
    def launch_cav_cal_thread(self):
        self.cav_cal_thread = CavCalWorker(self.current_cavity)
        self.setup_thread(worker=self.cav_cal_thread,
                          progressBar=self.ui.cav_cal_progressbar,
                          error_handler=self.handle_cav_cal_error,
                          abortButton=self.ui.cavity_cal_abort,
                          action_desc="Cavity calibration",
                          startButton=self.ui.button_cavity_calibration)
    
    def handle_cav_cal_error(self, e):
        cavity_expert_button = self.make_edmbutton('$TOOLS/edm/display/llrf/rf_srf_char_embed_ramp.edl')
        make_error_popup('Cavity calibration failed', cavity_expert_button, e,
                         self.cavity_actionbutton_clicked)
    
    def launch_tune_thread(self):
        self.tune_thread = TuneWorker(self.current_cavity)
        self.setup_thread(worker=self.tune_thread,
                          progressBar=self.ui.tune_progressbar,
                          error_handler=self.handle_tune_error,
                          abortButton=self.ui.tune_abort,
                          action_desc="Tune cavity",
                          startButton=self.ui.button_tune_cavity)
    
    @slot(str)
    def handle_tune_error(self, message):
        tuner_expert_button = self.make_edmbutton('$TOOLS/edm/display/llrf/rf_srf_tuner_embed.edl')
        make_error_popup('Detune PV invalid', tuner_expert_button, message,
                         self.tune_actionbutton_clicked)
    
    def tune_actionbutton_clicked(self, qmessagebox: QMessageBox):
        clickedbutton = qmessagebox.clickedButton()
        if qmessagebox.buttonRole(clickedbutton) == QMessageBox.AcceptRole:
            self.current_cavity.results.is_tuned = True
        if qmessagebox.buttonRole(clickedbutton) == QMessageBox.RejectRole:
            enable_after_deletion(button=self.ui.button_tune_cavity,
                                  thread=self.tune_thread)
        self.populate_status_labels()
        self.current_cavity.save_results()
    
    def launch_large_rack_thread(self):
        self.large_rack_thread = LargeRackWorker(self.current_cavity)
        self.setup_thread(worker=self.large_rack_thread,
                          progressBar=self.ui.large_rack_progressbar,
                          error_handler=self.handle_large_rack_error,
                          abortButton=self.ui.large_rack_abort, action_desc="8pi/9",
                          startButton=self.ui.button_measure_8pi9)
    
    def launch_ssa_char_thread(self):
        self.ssa_char_thread = SSACharWorker(self.current_cavity)
        self.setup_thread(worker=self.ssa_char_thread,
                          progressBar=self.ui.ssa_char_progressbar,
                          error_handler=self.handle_ssa_char_error,
                          abortButton=self.ui.ssa_char_abort,
                          action_desc="ssa characterization",
                          startButton=self.ui.button_ssa_char)
    
    def launch_piezo_pre_rf_thread(self):
        self.piezo_pre_rf_thread = PiezoPreRFWorker(self.current_cavity)
        self.setup_thread(worker=self.piezo_pre_rf_thread,
                          progressBar=self.ui.pre_rf_progressbar,
                          error_handler=self.handle_piezo_pre_rf_error,
                          abortButton=self.ui.piezo_pre_rf_abort,
                          action_desc="piezo pre rf",
                          startButton=self.ui.button_piezo_prerf)
    
    @slot(str)
    def handle_piezo_pre_rf_error(self, message):
        piezo_prerf_edmbutton = self.make_edmbutton('$TOOLS/edm/display/llrf/rf_srf_char_embed_pzt.edl')
        make_error_popup(title='Error during piezo pre-rf check',
                         expert_edmbutton=piezo_prerf_edmbutton,
                         exception=message,
                         action_func=self.piezo_prerf_actionbutton_clicked)
    
    @slot(utils.RadHandler)
    def handle_radiation(self, radHandler: utils.RadHandler):
        if not self.rad_popup:
            self.rad_popup = Display(ui_filename=self.getPath("gui/rad_monitor.ui"))
        
        self.rad_popup.ui.yes_checkBox.stateChanged.connect(partial(self.handle_check, radHandler.action_func))
        self.rad_popup.ui.no_checkBox.stateChanged.connect(self.reset_rad_popup)
        
        self.rad_popup.ui.status_label.setText(radHandler.message)
        showDisplay(self.rad_popup)
    
    def reset_rad_popup(self):
        self.rad_popup.hide()
        self.rad_popup = None
    
    def handle_check(self, action_func: Callable):
        if self.rad_popup.ui.yes_checkBox.isChecked():
            action_func()
        self.reset_rad_popup()
    
    @slot(str)
    def handle_success(self, message):
        self.populate_status_labels()
        self.current_cavity.save_results()
        if not self.success_popup:
            self.success_popup = make_info_popup(message)
        else:
            self.success_popup.setText(message)
            self.success_popup.exec()
    
    def check_radiation(self, severity, **kwargs):
        max_avg_dose = self.current_cm.decarad.max_avg_dose
        
        if severity == pyepicsUtils.EPICS_INVALID_VAL or max_avg_dose == 0:
            return
        
        if utils.RADIATION_LIMIT > max_avg_dose > 0:
            if self.current_cavity.fe_onset_recorded:
                return
            
            if self.current_cavity.selAmplitudeActPV.value <= self.current_cavity.rad_threshold:
                message = ('Field emission detected. Proceed with caution'
                           ' without exceeding {thresh} MV.'
                           .format(thresh=self.current_cavity.rad_threshold))
                radHandler = utils.RadHandler(message=message,
                                              action_func=self.current_cavity.handle_rad_under50_underThresh)
            
            else:
                message = ('Field emission detected above {thresh} MV. Please'
                           ' stop.'.format(thresh=self.current_cavity.rad_threshold))
                radHandler = utils.RadHandler(message=message,
                                              action_func=self.current_cavity.handle_rad_over50_overThresh)
            self.rad_error.emit(radHandler)
        
        elif max_avg_dose >= utils.RADIATION_LIMIT:
            
            message = ('Radiation exceeds {limit}mR/hr. Please stop.'
                       .format(limit=utils.RADIATION_LIMIT))
            
            if self.current_cavity.selAmplitudeActPV.value <= self.current_cavity.rad_threshold:
                
                radHandler = utils.RadHandler(message=message,
                                              action_func=self.current_cavity.handle_rad_over50_underThresh)
            
            else:
                radHandler = utils.RadHandler(message=message,
                                              action_func=self.current_cavity.handle_rad_under50_overThresh)
            self.rad_error.emit(radHandler)
    
    def connect_tuner_window(self):
        self.tuner_window.ui.button_save_cold_freq.clicked.connect(self.cold_freq_button_pressed)
        self.tuner_window.ui.button_replace.clicked.connect(self.replace_button_clicked)
        self.tuner_window.ui.button_add.clicked.connect(self.add_button_clicked)
        self.tuner_window.ui.button_mark_tuned.clicked.connect(self.mark_tuned_button_clicked)
        self.tuner_window.ui.step_des_spinBox.editingFinished.connect(self.launch_stepper_worker)
    
    def update_plot_timespan(self):
        self.time_plot_updater.updateTimespans(self.live_signals_window.ui.timespan_spinbox.value())
    
    def live_signal_button_clicked(self):
        try:
            if not self.live_signals_window:
                self.live_signals_window = Display(ui_filename=self.getPath("gui/live_signals.ui"))
                self.setup_plots()
                self.live_signals_window.ui.timespan_spinbox.editingFinished.connect(self.update_plot_timespan)
                self.update_cavity_plots()
                self.update_decarad_plot()
        except AttributeError:
            pass
        
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
                                                         formLayout=ui.decarad_form),
            utils.AMP_PLOT_KEY          : TimePlotParams(plot=ui.plot_amps,
                                                         formLayout=ui.amp_form)
        }
        self.time_plot_updater = TimePlotUpdater(time_plot_updater)
    
    def getPath(self, fileName):
        return path.join(self.pathHere, fileName)
    
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
        
        if self.tuner_window:
            self.tuner_window.ui.label_session_steps.setText(f"{self.current_cavity.current_steps}")
    
    def update_cavity(self):
        self.ui.workflow_groupbox.setEnabled(True)
        if self.current_cavity:
            self.current_cavity.save_results()
        try:
            self.current_cm: CommissioningCryomodule = COMMISSIONING_CRYOMODULE_OBJECTS[
                self.ui.pick_cm.currentText()]
            if self.current_cavity:
                self.current_cavity.steppertuner.step_tot_pv.clear_callbacks()
            self.current_cavity: CommissioningCavity = self.current_cm.cavities[int(self.ui.pick_cavity.currentText())]
            
            self.current_cavity.load_results()
            
            self.populate_status_labels()
            
            self.update_rf_controls()
            
            self.update_cavity_plots()
            self.update_rf_plots()
            self.update_tuner_plot()
            
            self.update_tuner_window()
            
            self.update_interlock()
            self.reset_progressbars()
            self.update_decarad()
        except ValueError:
            self.ui.workflow_groupbox.setEnabled(False)
    
    def update_decarad(self):
        decarad = self.decarads[self.ui.pick_decarad.currentText()]
        self.current_cavity.cryomodule.decarad = decarad
        self.current_cm.decarad = decarad
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
                                                    self.current_cavity.tuning_plot_pairs})
    
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
                                   utils.CMVACUUM_PLOT_KEY     : self.current_cm.vacuumPlotPairs,
                                   utils.CRYOSIGNALS_PLOT_KEY  : self.current_cm.cryo_signal_PVs,
                                   utils.AMP_PLOT_KEY          : self.current_cm.amp_pvs,
                                   utils.SINGLE_CAVITY_PLOT_KEY: self.current_cavity.plot_pvs}
            
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
    
    def setup_tuner_window(self):
        if not self.tuner_window:
            self.tuner_window = Display(ui_filename=self.getPath("gui/tuning.ui"))
            self.time_plot_updater.plotParams[utils.DETUNE_PLOT_KEY] = TimePlotParams(
                    plot=self.tuner_window.ui.tuning_plot, formLayout=self.tuner_window.ui.plot_layout)
            self.connect_tuner_window()
        self.update_tuner_window()
        showDisplay(self.tuner_window)
    
    def mark_tuned_button_clicked(self):
        self.current_cavity.results.is_tuned = True
        self.current_cavity.save_results()
        self.populate_status_labels()
        self.success_signal.emit("Tuning successful")
    
    def detune_callback(self, value, **kwargs):
        est_steps = value * (utils.ESTIMATED_MICROSTEPS_PER_HZ_HL
                             if self.current_cm.isHarmonicLinearizer
                             else utils.ESTIMATED_MICROSTEPS_PER_HZ)
        ui = self.tuner_window.ui
        ui.estimated_steps_label.setText(str(int(est_steps)))
        ui.label_current_freq.setText(str(value + self.current_cavity.frequency))
    
    def launch_stepper_worker(self):
        if (not self.tuner_window.ui.step_des_spinBox.value()
                or (self.stepper_thread and not self.stepper_thread.isFinished())):
            return
        self.stepper_thread = StepperWorker(cavity=self.current_cavity,
                                            des_steps=self.tuner_window.ui.step_des_spinBox.value())
        self.setup_thread(worker=self.stepper_thread,
                          progressBar=None, error_handler=self.handle_stepper_err,
                          abortButton=self.tuner_window.ui.step_abort_button,
                          action_desc="Stepper move",
                          startButton=self.tuner_window.ui.step_des_spinBox)
    
    @slot(str)
    def handle_stepper_err(self, exception):
        popup = QMessageBox()
        popup.setIcon(QMessageBox.Critical)
        popup.setWindowTitle("Stepper Error")
        popup.setText(exception)
        popup.exec()
    
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
        
        ui.lineedit_srfmax.channel = self.current_cavity.ades_max_srf_PV.pvname
        ui.label_srfmax_rdbk.channel = self.current_cavity.ades_max_srf_PV.pvname
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
        ui.spinbox_reactive_power.editingFinished.connect(partial(self.current_cavity.ades_proc_pv.put, 1))
        ui.label_reactive_power_rdbk.channel = self.current_cavity.ssa_reactive_power_fraction_PV.pvname
        
        ui.label_max_amplitude.channel = self.current_cavity.acceptancetest_max_amplitude_PVName
        ui.label_useable_amplitude.channel = self.current_cavity.acceptancetest_useable_amplitude_PVName
        ui.label_fe_onset.channel = self.current_cavity.acceptancetest_fe_onset_PVName
        ui.label_cavity_limitation.channel = self.current_cavity.acceptancetest_cavity_limitation_PVName
        
        ui.button_onehour_done.clicked.connect(self.onehour_done_button_pressed)
        ui.button_edm_rfcontroller.macros = [self.macro_string]
        ui.button_edm_waveforms.macros = [self.macro_string]
    
    def onehour_done_button_pressed(self):
        self.selap_timer.stop()
        self.current_cavity.results.onehourrun_complete = True
        curr_amp = self.current_cavity.selAmplitudeDesPV.value
        self.current_cavity.ades_max_srf_PV.put(curr_amp)
        # TODO figure out if we need to save commissioned amp
        self.current_cavity.results.onehour_amp = curr_amp
        self.current_cavity.turnOff()
        self.current_cavity.save_results()
        self.success_signal.emit("One hour run complete")
    
    def update_stepsize(self):
        stepsize = float(self.rf_controls_window.ui.lineedit_ades_stepsize.text())
        self.rf_controls_window.ui.spinbox_ades.setSingleStep(stepsize)
    
    @property
    def macro_string(self):
        rfs_map = {1: "1A", 2: "1A", 3: "2A", 4: "2A", 5: "1B", 6: "1B", 7: "2B", 8: "2B"}
        
        rfs = rfs_map[self.current_cavity.number]
        
        r = self.current_cavity.rack.rackName
        cm = self.current_cm.pvPrefix[:-3]  # need to remove trailing colon and zeroes to match needed format
        id = self.current_cm.name
        
        ch = 2 if self.current_cavity.number in [2, 4] else 1
        
        macro_string = ",".join(["C={c}".format(c=self.current_cavity.number),
                                 "RFS={rfs}".format(rfs=rfs),
                                 "R={r}".format(r=r), "CM={cm}".format(cm=cm),
                                 "ID={id}".format(id=id),
                                 "CH={ch}".format(ch=ch)])
        return macro_string
    
    @slot(str)
    def handle_ssa_char_error(self, message):
        ssa_expert_button = self.make_edmbutton('$TOOLS/edm/display/llrf/rf_srf_char_embed_ssa.edl')
        make_error_popup('SSA calibration failed', ssa_expert_button, message,
                         self.ssa_actionbutton_clicked)
    
    def ssa_actionbutton_clicked(self, qmessagebox: QMessageBox):
        clickedbutton = qmessagebox.clickedButton()
        if qmessagebox.buttonRole(clickedbutton) == QMessageBox.AcceptRole:
            self.current_cavity.results.ssa_characterized = True
            self.current_cavity.results.ssa_maxdrive = self.current_cavity.ssa_maxdrive_PV.value
        if qmessagebox.buttonRole(clickedbutton) == QMessageBox.RejectRole:
            enable_after_deletion(button=self.ui.button_ssa_char,
                                  thread=self.ssa_char_thread)
        self.populate_status_labels()
        self.current_cavity.save_results()
    
    def freq_actionbutton_clicked(self, qmessagebox: QMessageBox):
        clickedbutton = qmessagebox.clickedButton()
        if qmessagebox.buttonRole(clickedbutton) == QMessageBox.AcceptRole:
            self.current_cavity.results.eight_pi_nine_freq_measured = True
        if qmessagebox.buttonRole(clickedbutton) == QMessageBox.RejectRole:
            enable_after_deletion(button=self.ui.button_measure_8pi9,
                                  thread=self.large_rack_thread)
        self.populate_status_labels()
        self.current_cavity.save_results()
    
    def piezo_prerf_actionbutton_clicked(self, qmessagebox: QMessageBox):
        clickedbutton = qmessagebox.clickedButton()
        if qmessagebox.buttonRole(clickedbutton) == QMessageBox.AcceptRole:
            self.current_cavity.results.piezo_capacitance_a = self.current_cavity.piezo.capacitance_a_PV.value
            self.current_cavity.results.piezo_capacitance_b = self.current_cavity.piezo.capacitance_b_PV.value
            self.current_cavity.results.piezo_prerf_checked = True
        if qmessagebox.buttonRole(clickedbutton) == QMessageBox.RejectRole:
            enable_after_deletion(button=self.ui.button_piezo_prerf,
                                  thread=self.piezo_pre_rf_thread)
        self.populate_status_labels()
        self.current_cavity.save_results()
    
    def piezo_withrf_actionbutton_clicked(self, qmessagebox: QMessageBox):
        clickedbutton = qmessagebox.clickedButton()
        if qmessagebox.buttonRole(clickedbutton) == QMessageBox.AcceptRole:
            self.current_cavity.results.piezo_amplifiergain_a = self.current_cavity.piezo.amplifiergain_a_PV.value
            self.current_cavity.results.piezo_amplifiergain_b = self.current_cavity.piezo.amplifiergain_b_PV.value
            self.current_cavity.piezo.withrf_push_dfgain_PV.put(1)
            self.current_cavity.piezo.withrf_save_dfgain_PV.put(1)
            self.current_cavity.results.piezo_detune_gain = self.current_cavity.piezo.detunegain_new_PV.value
            self.current_cavity.results.piezo_withrf_checked = True
        if qmessagebox.buttonRole(clickedbutton) == QMessageBox.RejectRole:
            enable_after_deletion(button=self.ui.button_piezo_withrf,
                                  thread=self.piezo_with_rf_thread)
        self.populate_status_labels()
        self.current_cavity.save_results()
    
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
        if qmessagebox.buttonRole(clickedbutton) == QMessageBox.RejectRole:
            enable_after_deletion(button=self.ui.button_cavity_calibration,
                                  thread=self.cav_cal_thread)
        self.populate_status_labels()
        self.current_cavity.save_results()
    
    def testlead_selected(self):
        self.current_cavity.results.test_lead = self.ui.testlead.currentText()
        self.current_cavity.save_results()
    
    @slot(str)
    def handle_large_rack_error(self, e):
        freq_edmbutton = self.make_edmbutton('$TOOLS/edm/display/llrf/rf_srf_freq_scan_rack_embed_search.edl')
        make_error_popup(title='Error finding 8pi/9 frequency',
                         expert_edmbutton=freq_edmbutton,
                         exception=e,
                         action_func=self.freq_actionbutton_clicked)
    
    def handle_peizo_with_rf_error(self, e):
        piezo_withrf_edmbutton = self.make_edmbutton('$TOOLS/edm/display/llrf/rf_srf_char_embed_pzt_rf.edl')
        make_error_popup(title='Error during piezo with-rf check',
                         expert_edmbutton=piezo_withrf_edmbutton,
                         exception=e,
                         action_func=self.piezo_withrf_actionbutton_clicked)
    
    def cold_freq_button_pressed(self):
        self.current_cavity.results.cold_land_freq_2K = float(self.tuner_window.ui.label_current_freq.text())
        self.tuner_window.ui.label_cold_landing_freq.setText(str(self.current_cavity.results.cold_land_freq_2K))
        self.populate_status_labels()
        self.current_cavity.save_results()
    
    def launch_end_selap_thread(self):
        self.end_selap_thread = EndSELAPWorker(self.current_cavity)
        self.setup_thread(worker=self.end_selap_thread,
                          progressBar=self.ui.selap_progressbar,
                          error_handler=self.handle_selap_error,
                          abortButton=self.ui.selap_abort,
                          action_desc="SELAP rampdown",
                          startButton=self.ui.button_selap_rampup)
    
    def setup_rf_window(self):
        if not self.rf_controls_window:
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
            self.rf_controls_window.ui.sela_button.clicked.connect(self.save_sela_amp)
        self.update_rf_controls()
        self.update_rf_plots()
        showDisplay(self.rf_controls_window)
    
    def save_sela_amp(self):
        self.current_cavity.results.sela_amp = self.current_cavity.selAmplitudeDesPV.value
    
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
