from abc import abstractmethod
from copy import copy
from datetime import datetime
from time import sleep
from typing import Dict

from PyQt5.QtCore import QObject
from epics.ca import CASeverityException
from qtpy.QtCore import Signal as signal

import commissioningUtilities as utils
from commissioningLinac import CommissioningCavity
from lcls_tools.common.pyepics_tools import pyepicsUtils
from lcls_tools.common.pyepics_tools.pyepicsUtils import PVInvalidError
from lcls_tools.superconducting import scLinacUtils as scLinacUtils


class Worker(QObject):
    finished = signal(str)
    progress = signal(int)
    error = signal(str)
    status = signal(str)

    @abstractmethod
    def run(self, cavity: CommissioningCavity):
        pass


class PiezoPreRFWorker(Worker):

    def run(self, cavity: CommissioningCavity):
        try:
            self.status.emit("Turning RF off")
            cavity.turnOff()
            self.progress.emit(16.5)
            piezo = cavity.piezo

            self.status.emit("setting piezo parameters")

            piezo.enable_PV.put(utils.PIEZO_ENABLE_VALUE)
            self.progress.emit(33)

            piezo.feedback_mode_PV.put(utils.PIEZO_MANUAL_VALUE)
            self.progress.emit(49.5)

            # set piezo DC voltage offset to 0V
            piezo.dc_setpoint_PV.put(0)
            self.progress.emit(66)

            # run the test script
            piezo.prerf_test_start_pv.put(1)

            self.status.emit("waiting 5 seconds for piezo tuner test to start")
            sleep(5)

            self.progress.emit(82.5)

            self.status.emit("waiting 5s for piezo test status to update")
            sleep(5)

            if piezo.prerf_test_status_pv.value != utils.PIEZO_SCRIPT_COMPLETE_VALUE:
                self.error.emit('Piezo pre-rf test script was not successful')
                return

            if (piezo.prerf_cha_status_PV.value == utils.PIEZO_PRERF_CHECKOUT_PASS_VALUE
                    and piezo.prerf_chb_status_PV.value == utils.PIEZO_PRERF_CHECKOUT_PASS_VALUE):
                cavity.results.piezo_capacitance_a = piezo.capacitance_a_PV.value
                cavity.results.piezo_capacitance_b = piezo.capacitance_b_PV.value
                cavity.results.piezo_prerf_checked = True
                self.status.emit("Piezo pre-rf check complete and successful")
                self.finished.emit("Piezo pre-rf check complete and successful")
                self.progress.emit(100)

            else:
                self.error.emit("Piezo test unsuccessful")

        except (utils.PiezoError, pyepicsUtils.PVInvalidError) as e:
            self.error.emit(str(e))


class SSACharWorker(Worker):
    def run(self, cavity: CommissioningCavity, drivemax=0.8, attemptnumber=1):
        try:
            self.status.emit("trying calibration at {drive}; attempt #{attempt}".format(drive=drivemax,
                                                                                        attempt=attemptnumber))
            cavity.ssa_maxdrive_PV.put(drivemax)
            self.progress.emit(50)
            try:
                self.status.emit("running SSA calibration")
                cavity.ssa.runCalibration()
                cavity.results.ssa_maxdrive = drivemax
                cavity.results.ssa_characterized = True
                self.finished.emit("SSA Calibration Successful")
                self.progress.emit(100)
            except scLinacUtils.SSACalibrationError as e:
                self.status.emit("calibration failed, lowering drive")
                if attemptnumber <= 3:
                    self.run(cavity, drivemax - 0.05, attemptnumber + 1)
                else:
                    self.error.emit(str(e))
        except PVInvalidError as e:
            self.error.emit(str(e))


class TuneWorker(Worker):
    def run(self, cavity: CommissioningCavity):
        try:
            self.status.emit("Setting cavity up for tuning")
            cavity.setup_tuning()
            self.progress.emit(50)
            cavity.steppertuner.connect_callback()
            self.status.emit("Ready for tuning")
            self.progress.emit(100)
        except (utils.DetuneError, pyepicsUtils.PVInvalidError) as e:
            self.error.emit(str(e))


class PiezoWithRFWorker(Worker):
    def run(self, cavity: CommissioningCavity):
        try:
            self.status.emit("turning RF off")
            cavity.turnOff()
            self.progress.emit(10)

            self.status.emit("turning SSA on")
            cavity.ssa.turnOn()
            self.progress.emit(20)

            self.status.emit("setting ADES to 5MV")
            cavity.selAmplitudeDesPV.put(5)
            self.progress.emit(30)

            self.status.emit("setting cavity to SEL")
            cavity.rfModeCtrlPV.put(scLinacUtils.RF_MODE_SEL)
            self.progress.emit(40)

            self.status.emit("turning RF on")
            cavity.turnOn()
            self.progress.emit(50)

            piezo = cavity.piezo

            self.status.emit("waiting 5s for the detune to catch up")
            sleep(5)

            self.status.emit("enabling piezo")
            piezo.enable_PV.put(utils.PIEZO_ENABLE_VALUE)
            self.progress.emit(60)

            self.status.emit("setting piezo to manual")
            piezo.feedback_mode_PV.put(utils.PIEZO_MANUAL_VALUE)
            self.progress.emit(70)

            self.status.emit("verifying that RFS detune is <100Hz")
            if (cavity.detune_rfs_PV.severity == 3
                    or abs(cavity.detune_rfs_PV.value) > 100):
                self.error.emit('Detuning is invalid or larger than 100Hz')
                return

            self.status.emit("running piezo test script")
            piezo.withrf_run_check_PV.put(1)

            self.status.emit("waiting 5s for piezo test script to run")
            sleep(5)

            self.status.emit("waiting for piezo test script to finish running", datetime.now())
            while piezo.withrf_check_status_PV.value == utils.PIEZO_SCRIPT_RUNNING_VALUE:
                sleep(1)

            self.progress.emit(80)

            if piezo.withrf_check_status_PV.value != utils.PIEZO_SCRIPT_COMPLETE_VALUE:
                self.error.emit('Piezo with-rf test script has exited with status \'crash\'')
                return

            cavity.results.piezo_amplifiergain_a = piezo.amplifiergain_a_PV.value
            cavity.results.piezo_amplifiergain_b = piezo.amplifiergain_b_PV.value

            self.status.emit("pushing and saving gain")
            piezo.withrf_push_dfgain_PV.put(1)
            piezo.withrf_save_dfgain_PV.put(1)
            self.progress.emit(90)

            cavity.results.piezo_detune_gain = piezo.detunegain_new_PV.value
            cavity.results.piezo_withrf_checked = True
            self.progress.emit(100)
            self.finished.emit("Piezo with RF check complete")
        except (utils.PiezoError, scLinacUtils.SSAPowerError,
                pyepicsUtils.PVInvalidError) as e:
            self.error.emit(str(e))


class LargeRackWorker(Worker):
    def run(self, cavity: CommissioningCavity):
        try:
            other_cavities: Dict[int, CommissioningCavity] = copy(cavity.rack.cavities)
            other_cavities.pop(cavity.number)

            self.status.emit("removing other cavities from rack frequency scan")
            for cavity in other_cavities.values():
                cavity.freq_search_select_PV.put(0)

            self.progress.emit(0)

            self.status.emit("selecting current cavity for rack frequency scan")
            cavity.freq_search_select_PV.put(1)

            self.progress.emit(25)

            self.status.emit("setting frequency scan parameters")

            cavity.rack.freq_search_low_PV.put(utils.FREQ_SEARCH_LOW)
            cavity.rack.freq_search_high_PV.put(utils.FREQ_SEARCH_HIGH)
            cavity.rack.freq_search_rms_thresh_PV.put(utils.FREQ_SEARCH_RMS_THRESH)
            cavity.rack.freq_search_modeoverlap_PV.put(utils.FREQ_SEARCH_MODEOVERLAP)

            self.progress.emit(50)

            cavity.rack.freq_search_start_PV.put(1)
            self.status.emit("Waiting 5s for the rack frequency scan to start")
            sleep(5)

            self.status.emit("waiting for scan to finish running")
            while cavity.rack.freq_search_status_PV.value == 3:
                sleep(1)

            self.progress.emit(75)

            if cavity.rack.freq_search_status_PV.value != 5:
                self.error.emit('Frequency search did not exit successfully')
            if (cavity.freq_search_8pi9_PV.value > -750000
                    or cavity.freq_search_8pi9_PV.value < -850000):
                self.error.emit('8pi/9 frequency outside tolerance')
            cavity.freq_search_push_PV.put(1)
            cavity.results.eight_pi_nine_freq_measured = True

            self.success.emit("8pi/9 scan successful")
            self.progress.emit(100)
        except PVInvalidError as e:
            self.error.emit(str(e))


class CavCalWorker(Worker):
    def run(self, cavity: CommissioningCavity):
        try:
            self.status.emit("running cavity calibration")
            cavity.runCalibration(3e7, 5e7)
            self.progress.emit(100)
            cavity.results.fpc_qext_cold = self.current_cavity.measuredQLoadedPV.value
            cavity.results.probe_qext_value = self.current_cavity.measured_probe_qext_PV.value
            cavity.results.cavity_calibration_run = True
            self.finished.emit("cavity calibration done")
        except (scLinacUtils.CavityQLoadedCalibrationError,
                scLinacUtils.CavityScaleFactorCalibrationError, TypeError,
                CASeverityException, pyepicsUtils.PVInvalidError) as e:
            self.error.emit(str(e))


class SELAPWorker(Worker):
    def run(self, cavity: CommissioningCavity):
        try:
            self.status.emit("Setting up for SELAP ramp up")
            cavity.selap_setup()
            self.progress.emit(50)
            self.finished.emit("Walk amplitude up to {amax}MV in SELA".format(amax=cavity.ades_max_PV.value))
        except (utils.PiezoError, utils.DetuneError, scLinacUtils.SSAPowerError,
                pyepicsUtils.PVInvalidError) as e:
            self.error.emit(str(e))
