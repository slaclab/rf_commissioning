from abc import abstractmethod
from time import sleep

from PyQt5.QtCore import QThread
from epics.ca import CASeverityException
from qtpy.QtCore import Signal as signal

import commissioningUtilities as utils
from commissioningLinac import CommissioningCavity
from lcls_tools.common.pyepics_tools import pyepicsUtils
from lcls_tools.common.pyepics_tools.pyepicsUtils import PVInvalidError
from lcls_tools.superconducting import scLinacUtils as scLinacUtils


class Worker(QThread):
    finished = signal(str)
    progress = signal(int)
    error = signal(str)
    status = signal(str)

    def __init__(self, cavity: CommissioningCavity):
        super().__init__()
        self.cavity = cavity

    @abstractmethod
    def run(self):
        pass


class PiezoPreRFWorker(Worker):

    def run(self):
        try:
            self.status.emit("Turning RF off")
            self.cavity.turnOff()
            self.progress.emit(16.5)
            piezo = self.cavity.piezo

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

            self.status.emit("waiting for piezo tuner test to start")
            while piezo.prerf_test_status_pv.value != utils.PIEZO_SCRIPT_RUNNING_VALUE:
                sleep(1)

            self.status.emit("waiting for piezo test to finish")
            while piezo.prerf_test_status_pv.value == utils.PIEZO_SCRIPT_RUNNING_VALUE:
                sleep(1)

            self.progress.emit(82.5)

            if piezo.prerf_test_status_pv.value != utils.PIEZO_SCRIPT_COMPLETE_VALUE:
                self.error.emit('Piezo pre-rf test script was not successful')
                return

            if (piezo.prerf_cha_status_PV.value == utils.PIEZO_PRERF_CHECKOUT_PASS_VALUE
                    and piezo.prerf_chb_status_PV.value == utils.PIEZO_PRERF_CHECKOUT_PASS_VALUE):
                self.cavity.results.piezo_capacitance_a = piezo.capacitance_a_PV.value
                self.cavity.results.piezo_capacitance_b = piezo.capacitance_b_PV.value
                self.cavity.results.piezo_prerf_checked = True
                self.status.emit("Piezo pre-rf check complete and successful")
                self.finished.emit("Piezo pre-rf check complete and successful")
                self.progress.emit(100)

            else:
                self.error.emit("Piezo test unsuccessful")

        except (utils.PiezoError, pyepicsUtils.PVInvalidError) as e:
            self.error.emit(str(e))


class SSACharWorker(Worker):
    def __init__(self, cavity: CommissioningCavity, drivemax=0.8, attemptnumber=1):
        super().__init__(cavity)
        self.drivemax = drivemax
        self.attemptnumber = attemptnumber

    def run(self):
        try:
            self.status.emit("trying calibration at {drive}; attempt #{attempt}"
                             .format(drive=self.drivemax,
                                     attempt=self.attemptnumber))
            self.cavity.ssa_maxdrive_PV.put(self.drivemax)
            self.progress.emit(50)
            try:
                self.status.emit("running SSA calibration")
                self.cavity.ssa.runCalibration()
                self.cavity.results.ssa_maxdrive = self.drivemax
                self.cavity.results.ssa_characterized = True
                self.finished.emit("SSA Calibration Successful")
                self.progress.emit(100)
            except scLinacUtils.SSACalibrationError as e:
                self.status.emit("calibration failed, lowering drive")
                if self.attemptnumber <= 3:
                    self.drivemax = self.drivemax - 0.05
                    self.attemptnumber = self.attemptnumber + 1
                    self.run()
                else:
                    self.error.emit(str(e))
        except (PVInvalidError, scLinacUtils.SSAPowerError) as e:
            self.error.emit(str(e))


class TuneWorker(Worker):
    def run(self):
        try:
            self.status.emit("Setting cavity up for tuning")
            self.cavity.setup_tuning()
            self.progress.emit(50)
            self.cavity.steppertuner.connect_callback()
            self.status.emit("Ready for tuning")
            self.progress.emit(100)
        except (utils.DetuneError, pyepicsUtils.PVInvalidError) as e:
            self.error.emit(str(e))


class PiezoWithRFWorker(Worker):
    def run(self):
        try:
            self.status.emit("turning RF off")
            self.cavity.turnOff()
            self.progress.emit(10)

            self.status.emit("turning SSA on")
            self.cavity.ssa.turnOn()
            self.progress.emit(20)

            self.status.emit("setting ADES to 5MV")
            self.cavity.selAmplitudeDesPV.put(5)
            self.progress.emit(30)

            self.status.emit("setting cavity to SEL")
            self.cavity.rfModeCtrlPV.put(scLinacUtils.RF_MODE_SEL)
            self.progress.emit(40)

            self.status.emit("turning RF on")
            self.cavity.turnOn()
            self.progress.emit(50)

            piezo = self.cavity.piezo

            self.status.emit("waiting 5s for the detune to catch up")
            sleep(5)

            self.status.emit("enabling piezo")
            piezo.enable_PV.put(utils.PIEZO_ENABLE_VALUE)
            self.progress.emit(60)

            self.status.emit("setting piezo to manual")
            piezo.feedback_mode_PV.put(utils.PIEZO_MANUAL_VALUE)
            self.progress.emit(70)

            self.status.emit("verifying that RFS detune is <100Hz")
            if (self.cavity.detune_rfs_PV.severity == 3
                    or abs(self.cavity.detune_rfs_PV.value) > 100):
                self.error.emit('Detuning is invalid or larger than 100Hz')
                return

            self.status.emit("running piezo test script")
            piezo.withrf_run_check_PV.put(1, waitForPut=False)

            self.status.emit("waiting 5s for piezo test script to run")
            sleep(5)

            self.status.emit("waiting for piezo test script to finish running")
            while piezo.withrf_check_status_PV.value == utils.PIEZO_SCRIPT_RUNNING_VALUE:
                sleep(1)

            self.progress.emit(80)

            if piezo.withrf_check_status_PV.value != utils.PIEZO_SCRIPT_COMPLETE_VALUE:
                self.error.emit('Piezo with-rf test script has exited with status \'crash\'')
                return

            self.cavity.results.piezo_amplifiergain_a = piezo.amplifiergain_a_PV.value
            self.cavity.results.piezo_amplifiergain_b = piezo.amplifiergain_b_PV.value

            self.status.emit("pushing and saving gain")
            piezo.withrf_push_dfgain_PV.put(1)
            piezo.withrf_save_dfgain_PV.put(1)
            self.progress.emit(90)

            self.cavity.results.piezo_detune_gain = piezo.detunegain_new_PV.value
            self.cavity.results.piezo_withrf_checked = True
            self.progress.emit(100)
            self.finished.emit("Piezo with RF check complete")
        except (utils.PiezoError, scLinacUtils.SSAPowerError,
                pyepicsUtils.PVInvalidError) as e:
            self.error.emit(str(e))


class LargeRackWorker(Worker):
    def run(self):
        try:
            self.status.emit("removing cavities not {num} from rack frequency scan"
                             .format(num=self.cavity.number))
            for num, other_cavity in self.cavity.rack.cavities.items():
                if num != self.cavity.number:
                    other_cavity.freq_search_select_PV.put(0)

            self.progress.emit(0)

            self.status.emit("selecting cavity {num} for rack frequency scan"
                             .format(num=self.cavity.number))
            self.cavity.freq_search_select_PV.put(1)

            self.progress.emit(25)

            self.status.emit("setting frequency scan parameters")

            self.cavity.rack.freq_search_low_PV.put(utils.FREQ_SEARCH_LOW)
            self.cavity.rack.freq_search_high_PV.put(utils.FREQ_SEARCH_HIGH)
            self.cavity.rack.freq_search_rms_thresh_PV.put(utils.FREQ_SEARCH_RMS_THRESH)
            self.cavity.rack.freq_search_modeoverlap_PV.put(utils.FREQ_SEARCH_MODEOVERLAP)

            self.progress.emit(50)

            self.cavity.rack.freq_search_start_PV.put(1, waitForPut=False)
            self.status.emit("Waiting 5s for the rack frequency scan to start")
            sleep(5)

            self.status.emit("waiting for scan to finish running")
            while self.cavity.rack.freq_scan_status_PV.value == 3:
                sleep(1)

            self.progress.emit(75)

            if self.cavity.rack.freq_search_stat_PV.value != 0:
                self.error.emit('Frequency search did not exit successfully')
                return
            if (self.cavity.freq_search_8pi9_PV.value > -750000
                    or self.cavity.freq_search_8pi9_PV.value < -850000):
                self.error.emit('8pi/9 frequency outside tolerance')
                return
            self.cavity.freq_search_push_PV.put(1)
            self.cavity.results.eight_pi_nine_freq_measured = True

            self.success.emit("8pi/9 scan successful")
            self.progress.emit(100)
        except PVInvalidError as e:
            self.error.emit(str(e))


class CavCalWorker(Worker):
    def run(self):
        try:
            self.status.emit("running cavity calibration")
            self.cavity.runCalibration(3e7, 5e7)
            self.progress.emit(100)
            self.cavity.results.fpc_qext_cold = self.current_cavity.measuredQLoadedPV.value
            self.cavity.results.probe_qext_value = self.current_cavity.measured_probe_qext_PV.value
            self.cavity.results.cavity_calibration_run = True
            self.finished.emit("cavity calibration done")
        except (scLinacUtils.CavityQLoadedCalibrationError,
                scLinacUtils.CavityScaleFactorCalibrationError, TypeError,
                CASeverityException, pyepicsUtils.PVInvalidError) as e:
            self.error.emit(str(e))


class SELAPWorker(Worker):
    def run(self):
        try:
            self.status.emit("Setting up for SELAP ramp up")
            self.cavity.selap_setup()
            self.progress.emit(50)
            self.finished.emit("Walk amplitude up to {amax}MV in SELA"
                               .format(amax=self.cavity.ades_max_PV.value))
        except (utils.PiezoError, utils.DetuneError, scLinacUtils.SSAPowerError,
                pyepicsUtils.PVInvalidError) as e:
            self.error.emit(str(e))


class StepperWorker(Worker):
    def __init__(self, cavity: CommissioningCavity, des_steps: int):
        super().__init__(cavity)
        self.des_steps = des_steps

    def run(self):
        try:
            self.status.emit("Sending move command")
            self.cavity.steppertuner.move(self.des_steps,
                                          maxSteps=utils.STEPPER_MAX_STEPS,
                                          speed=scLinacUtils.MAX_STEPPER_SPEED)
            self.status.emit("stepper done moving")
            self.cavity.current_steps += self.des_steps
            self.finished.emit(str(self.cavity.current_steps))
        except (scLinacUtils.StepperError, PVInvalidError) as e:
            self.error.emit(str(e))
