from datetime import datetime, timedelta
from time import sleep
from typing import Callable, Dict, List, Optional, Tuple

from epics import PV as epicsPV
from numpy import nanmean

import commissioningUtilities as utils
from lcls_tools.common.pyepics_tools import pyepicsUtils
from lcls_tools.superconducting import scLinacUtils
from lcls_tools.superconducting.scLinac import Cavity, Cryomodule, Rack, SSA, StepperTuner, make_lcls_cryomodules


class PV(epicsPV):
    def __init__(self, pvname):
        super().__init__(pvname, connection_timeout=0.01)


class DecaradHead:
    def __init__(self, number, decarad):
        # type (int, Decarad) -> None

        if number not in range(1, 11):
            raise AttributeError("Decarad Head number need to be between 1 and 10")

        self.decarad = decarad
        self.number = number

        # Adds leading 0 to numbers with less than 2 digits
        self.pvPrefix = self.decarad.pvPrefix + "{:02d}:".format(self.number)

        self.doseRatePV: PV = PV(self.pvPrefix + "GAMMA_DOSE_RATE")

    @property
    def avgDose(self) -> float:
        # try to do averaging of the last 60 points to account for signal noise
        try:
            archiverData = utils.ARCHIVER.getDataWithTimeInterval(pvList=[self.doseRatePV.pvname],
                                                                  startTime=(datetime.now() - timedelta(minutes=1)),
                                                                  endTime=datetime.now(),
                                                                  timeDelta=timedelta(seconds=1))

            averageDose = nanmean(archiverData.values[self.doseRatePV.pvname])

            return max(averageDose - utils.DECARAD_BACKGROUND_READING, 0)

        # return the most recent value if we can't average for whatever reason
        except AttributeError:
            return self.doseRatePV.value


class Decarad:
    def __init__(self, number):
        # type: (int) -> None
        if number not in [1, 2]:
            raise AttributeError("Decarad needs to be 1 or 2")
        self.number = number
        self.pvPrefix = "RADM:SYS0:{num}00:".format(num=self.number)
        self.powerControlPVName = self.pvPrefix + "HVCTRL"
        self.powerStatusPVName = self.pvPrefix + "HVSTATUS"
        self.voltageReadbackPVName = self.pvPrefix + "HVMON"

        self.heads = {head: DecaradHead(number=head, decarad=self)
                      for head in range(1, 11)}

    @property
    def max_avg_dose(self):
        return max([head.avgDose for head in self.heads.values()])


class Piezo:
    def __init__(self, cavity):
        # type (CommissioningCavity) -> None
        self.cavity: CommissioningCavity = cavity
        self.pvPrefix: str = self.cavity.pvPrefix + "PZT:"

        self.enable_PV: PV = PV(self.pvPrefix + "ENABLE")
        self.feedback_mode_PV: PV = PV(self.pvPrefix + "MODECTRL")
        self.dc_setpoint_PV: PV = PV(self.pvPrefix + "DAC_SP")
        self.bias_voltage_PV: PV = PV(self.pvPrefix + "BIAS")
        self.prerf_run_check_PV: PV = PV(self.pvPrefix + "TESTSTRT")
        self.prerf_cha_status_PV: PV = PV(self.pvPrefix + "CHA_TESTSTAT")
        self.prerf_chb_status_PV: PV = PV(self.pvPrefix + "CHB_TESTSTAT")
        self.prerf_cha_testmsg_PV: PV = PV(self.pvPrefix + "CHA_TESTMSG1")
        self.prerf_chb_testmsg_PV: PV = PV(self.pvPrefix + "CHA_TESTMSG2")
        self.capacitance_a_PV: PV = PV(self.pvPrefix + "CHA_C")
        self.capacitance_b_PV: PV = PV(self.pvPrefix + "CHB_C")
        self.prerf_check_status_PV: PV = PV(self.pvPrefix + "TESTSTS")

        self.withrf_run_check_PV: PV = PV(self.pvPrefix + "RFSTART")
        self.withrf_check_status_PV: PV = PV(self.pvPrefix + "RFTESTS")
        self.withrf_status_PV: PV = PV(self.pvPrefix + "RFSTESTSTAT")
        self.amplifiergain_a_PV: PV = PV(self.pvPrefix + "CHA_AMPGAIN")
        self.amplifiergain_b_PV: PV = PV(self.pvPrefix + "CHB_AMPGAIN")
        self.withrf_push_dfgain_PV: PV = PV(self.pvPrefix + "PUSH_DFGAIN.PROC")
        self.withrf_save_dfgain_PV: PV = PV(self.pvPrefix + "SAVE_DFGAIN.PROC")
        self.detunegain_new_PV: PV = PV(self.pvPrefix + "DFGAIN_NEW")

    def enable_feedback(self):
        self.enable_PV.put(utils.PIEZO_DISABLE_VALUE)
        self.dc_setpoint_PV.put(25)
        self.feedback_mode_PV.put(utils.PIEZO_MANUAL_VALUE)
        self.enable_PV.put(utils.PIEZO_ENABLE_VALUE)


class CommissioningCavity(Cavity):
    def __init__(self, cavityNum, rackObject, ssaClass=SSA, stepperClass=StepperTuner):
        super().__init__(cavityNum, rackObject, stepperClass=CommissioningStepper)

        self.results = utils.CommissioningCavityResults()

        self.piezo = Piezo(self)

        self.interlock_PV: PV = PV(self.pvPrefix + "RFPERMIT")
        self.coupler_top_PVName = self.pvPrefix + "CPLRTEMP1"
        self.coupler_bot_PVName = self.pvPrefix + "CPLRTEMP2"
        self.hom_us_PVName = "CTE:CM{cm}:1{cavity}18:UH:TEMP".format(cm=self.cryomodule.name, cavity=self.number)
        self.hom_ds_PVName = "CTE:CM{cm}:1{cavity}20:DH:TEMP".format(cm=self.cryomodule.name, cavity=self.number)
        self.detune_best_PV: PV = PV(self.pvPrefix + "DFBEST")
        self.detune_rfs_PV: PV = PV(self.pvPrefix + "DF")

        self.ssa_maxdrive_PV: PV = PV(self.pvPrefix + "SSA:DRV_MAX_REQ")
        self.ssa_reactive_power_fraction_PV: PV = PV(self.pvPrefix + "SSA:REACTIVE")

        self.measured_probe_qext_PV: PV = PV(self.pvPrefix + "QPROBE_CALC2")
        self.inuse_probe_qext_PV: PV = PV(self.pvPrefix + "QPROBE")
        self.calculate_probe_qext_PV: PV = PV(self.pvPrefix + "QPROBE_CALC1.PROC")
        self.push_probe_qext_PV: PV = PV(self.pvPrefix + "PUSH_QPROBECALC.PROC")

        self.waveformplot_channelpairs: List[Tuple[Optional[str], str]] = [(None, self.revWaveformPV.pvname),
                                                                           (None, self.fwdWaveformPV.pvname),
                                                                           (None, self.cavWaveformPV.pvname)]

        self.iwaveform_PVName = self.pvPrefix + "CTRL:IWF"
        self.qwaveform_PVName = self.pvPrefix + "CTRL:QWF"
        self.controller_limit_a_PVName = self.pvPrefix + "CTRL:LIMS.VALA"
        self.controller_limit_b_PVName = self.pvPrefix + "CTRL:LIMS.VALB"

        self.cheetoplot_channelpairs: List[Tuple[Optional[str], str]] = [(self.iwaveform_PVName,
                                                                          self.qwaveform_PVName),
                                                                         (self.controller_limit_a_PVName,
                                                                          self.controller_limit_b_PVName)]

        self.acceptancetest_max_amplitude_PVName = self.pvPrefix + "AT:AMAX"
        self.acceptancetest_useable_amplitude_PVName = self.pvPrefix + "AT:AUSE"
        self.acceptancetest_fe_onset_PVName = self.pvPrefix + "AT:FEON_AACT"
        self.acceptancetest_cavity_limitation_PVName = self.pvPrefix + "AT:LIMIT"

        self.sel_phaseoffset_PVName = self.pvPrefix + "SEL_POFF"
        self.sel_phaseoffset_rdbk_PVName = self.pvPrefix + "SEL_POFF_RBV"

        self.feedback_phase_high_PVName = self.pvPrefix + "PHAFB_HSUM"
        self.feedback_phase_low_PVName = self.pvPrefix + "PHAFB_LSUM"
        self.feedback_amplitude_high_PVName = self.pvPrefix + "AMPFB_HSUM"
        self.feedback_amplitude_low_PVName = self.pvPrefix + "AMPFB_LSUM"

        self.freq_search_select_PV: PV = PV(self.pvPrefix + "FSCAN:SEL")
        self.freq_search_8pi9_PV: PV = PV(self.pvPrefix + "FSCAN:8PI9MODE")
        self.freq_search_push_PV: PV = PV(self.pvPrefix + "FSCAN:PUSH_8PI9.PROC")

        self.ades_max_srf_PVName = self.pvPrefix + "ADES_MAX_SRF"
        self.ades_max_PV: PV = PV(self.pvPrefix + "ADES_MAX")
        self.tuning_pvs: List[str] = [self.detune_best_PV.pvname,
                                      self.stepper_temp_PV.pvname]

        self.current_steps = 0

    def setup_tuning(self):
        # self.turnOff()
        print("enabling piezo")
        self.piezo.enable_PV.put(utils.PIEZO_ENABLE_VALUE)

        print("setting piezo to manual")
        self.piezo.feedback_mode_PV.put(utils.PIEZO_MANUAL_VALUE)

        print("setting piezo DC voltage offset to 0V")
        self.piezo.dc_setpoint_PV.put(0)

        print("setting piezo bias voltage to 25V")
        self.piezo.bias_voltage_PV.put(25)

        print("setting drive level to {lev}".format(lev=scLinacUtils.SAFE_PULSED_DRIVE_LEVEL))
        self.drivelevelPV.put(scLinacUtils.SAFE_PULSED_DRIVE_LEVEL)

        print("setting RF to chirp")
        self.rfModeCtrlPV.put(scLinacUtils.RF_MODE_CHIRP)

        print("turning RF on")
        self.turnOn()
        sleep(1)

        if self.detune_best_PV.severity == pyepicsUtils.EPICS_INVALID_VAL:
            raise utils.DetuneError("Detune PV invalid. Either expand the chirp"
                                    " range or use the rack large frequency scan"
                                    " to find the detune.")

    def connect_to_decarad(self, callbackfunc: Callable):
        for decaradhead in self.cryomodule.decarad.heads.values():
            if decaradhead.doseRatePV.severity != pyepicsUtils.EPICS_INVALID_VAL:
                decaradhead.doseRatePV.clear_callbacks()
                decaradhead.doseRatePV.add_callback(callbackfunc, with_ctrlvars=False)

    @property
    def interlocks_cleared(self) -> bool:
        return self.interlock_PV.value == 1

    def calculate_probe_q(self):
        # TODO check if '1' is actually the right thing to put
        self.calculate_probe_qext_PV.put(1)
        if utils.PROBE_QEXT_LOWER_LIMIT <= self.measured_probe_qext_PV.value <= utils.PROBE_QEXT_UPPER_LIMIT:
            self.push_probe_qext_PV.put(1)
            self.results.probe_qext_value = self.measured_probe_qext_PV.value
            self.results.probe_qext_measured = True
        else:
            raise utils.ProbeQError('Measured probe Q value out of tolerance')

    def selap_setup(self):

        self.turnOff()

        while self.rfStatePV.value != 0:
            print("turning RF off")
            sleep(1)

        self.ssa.turnOn()

        while self.ssa.statusPV.value != 3:
            print("turning SSA on")
            sleep(1)

        self.selAmplitudeDesPV.put(5)

        while self.selAmplitudeDesPV.value != 5:
            print("setting amplitude to 5MV")
            sleep(1)

        self.rfModeCtrlPV.put(scLinacUtils.RF_MODE_SEL)

        while self.rfModePV.value != scLinacUtils.RF_MODE_SEL:
            print("Setting cavity to SEL")
            sleep(1)

        print("turning cavity on")
        self.turnOn()

        while self.rfStatePV.value != 1:
            print("turning RF on")
            sleep(1)

        print("checking detune")
        if (self.detune_best_PV.severity == 3
                or abs(self.detune_best_PV.value) > 50):
            raise utils.DetuneError('Detune is invalid or larger than 50Hz')

        print("checking piezo with rf calibration")
        if not self.results.piezo_withrf_checked:
            raise utils.PiezoError('Piezo checks have not been completed')

        print("setting piezo to feedback")
        self.piezo.feedback_mode_PV.put(utils.PIEZO_FEEDBACK_VALUE)

        self.rfModeCtrlPV.put(scLinacUtils.RF_MODE_SELA)

        while self.rfModePV.value != scLinacUtils.RF_MODE_SELA:
            print("Setting cavity to SELA")
            sleep(1)


class CommissioningRack(Rack):
    def __init__(self, rackName, cryoObject, cavityClass, ssaClass=SSA, stepperClass=StepperTuner):
        super().__init__(rackName=rackName, cryoObject=cryoObject, cavityClass=CommissioningCavity,
                         stepperClass=CommissioningStepper)

        self.freq_search_low_PV: PV = PV(self.pvPrefix + "FSCAN:FREQ_START")
        self.freq_search_high_PV: PV = PV(self.pvPrefix + "FSCAN:FREQ_STOP")
        self.freq_search_rms_thresh_PV: PV = PV(self.pvPrefix + "FSCAN:RMS_THRESH")
        self.freq_search_modeoverlap_PV: PV = PV(self.pvPrefix + "FSCAN:MODE_OVERLAP")
        self.freq_search_start_PV: PV = PV(self.pvPrefix + "FSCAN:START")
        self.freq_search_status_PV: PV = PV(self.pvPrefix + "FSCAN:STAT")


class CommissioningCryomodule(Cryomodule):
    def __init__(self, cryoName, linacObject, cavityClass, magnetClass, rackClass, isHarmonicLinearizer, ssaClass=SSA,
                 stepperClass=StepperTuner):
        super().__init__(cryoName=cryoName, linacObject=linacObject, cavityClass=CommissioningCavity,
                         rackClass=CommissioningRack,
                         isHarmonicLinearizer=isHarmonicLinearizer, stepperClass=CommissioningStepper)

        self.results = utils.CommissioningCryomoduleResults()
        self.cavity_results = {cavity.number: cavity.results for cavity in self.cavities.values()}

        self.stepper_temp_PVs = []
        self.coupler_top_PVs = []
        self.coupler_bot_PVs = []
        self.hom_us_PVs = []
        self.hom_ds_PVs = []
        self.detune_PVs = []

        for cavity in self.cavities.values():
            self.stepper_temp_PVs.append(cavity.stepper_temp_PV.pvname)
            self.coupler_top_PVs.append(cavity.coupler_top_PVName)
            self.coupler_bot_PVs.append(cavity.coupler_bot_PVName)
            self.hom_us_PVs.append(cavity.hom_us_PVName)
            self.hom_ds_PVs.append(cavity.hom_ds_PVName)
            self.detune_PVs.append(cavity.detune_best_PV.pvname)

        self.cryo_signal_PVs = [self.dsLevelPV.pvname, self.usLevelPV.pvname,
                                self.dsPressurePV.pvname, self.jtValveRdbkPV.pvname]

        # To be populated from the GUI
        self.decarad: Optional[Decarad] = None

    @property
    def decarad_PVs(self):
        decarad_PVs = []
        for decaradhead in self.decarad.heads.values():
            decarad_PVs.append(decaradhead.doseRatePV.pvname)
        return decarad_PVs


class CommissioningStepper(StepperTuner):
    def __init__(self, cavity):
        super().__init__(cavity)

    def checkTemp(self, **kwargs):
        if self.cavity.stepper_temp_PV.value >= scLinacUtils.STEPPER_TEMP_LIMIT:
            self.abort_pv.put(1)

    def connect_callback(self):
        self.step_tot_pv.add_callback(self.checkTemp)


COMMISSIONING_CRYOMODULE_OBJECTS: Dict[str, CommissioningCryomodule] = make_lcls_cryomodules(
        cryomoduleClass=CommissioningCryomodule,
        rackClass=CommissioningRack, cavityClass=CommissioningCavity, stepperClass=CommissioningStepper)
