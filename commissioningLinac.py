from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from epics import PV
from lcls_tools.data_analysis.archiver import Archiver
from lcls_tools.devices.scLinac.scLinac import Cavity, Cryomodule, LINAC_TUPLES, Linac, Magnet, Rack
from numpy import nanmean

from utilities import CommissioningCavityResults, CommissioningCryomoduleResults, ProbeQError

PROBE_QEXT_UPPER_LIMIT = 3e12
PROBE_QEXT_LOWER_LIMIT = 1e11

DECARAD_ON_VALUE = 0
DECARAD_OFF_VALUE = 1

ARCHIVER = Archiver("lcls")


class DecaradHead:
    def __init__(self, number, decarad):
        # type (int, Decarad) -> None

        if number not in range(1, 11):
            raise AttributeError("Decarad Head number need to be between 1 and 10")

        self.decarad = decarad
        self.number = number

        # Adds leading 0 to numbers with less than 2 digits
        self.pvPrefix = self.decarad.pvPrefix + "{:02d}:".format(self.number)

        self.doseRatePV = PV(self.pvPrefix + "GAMMA_DOSE_RATE")

    @property
    def avgDose(self) -> float:
        # try to do averaging of the last NUM_LL_POINTS_TO_AVG points to account
        # for signal noise
        try:
            archiverData = ARCHIVER.getDataWithTimeInterval(pvList=[self.doseRatePV.pvname],
                                                            startTime=(datetime.now() - timedelta(minutes=1)),
                                                            endTime=datetime.now(),
                                                            timeDelta=timedelta(seconds=1))

            averageDose = nanmean(archiverData.values[self.doseRatePV.pvname])

            return max(averageDose - 4, 0)

        # return the most recent value if we can't average for whatever reason
        except AttributeError:
            return self.doseRatePV.value


class Decarad:
    def __init__(self, number: int):
        if number not in [1, 2]:
            raise AttributeError("Decarad needs to be 1 or 2")
        self.number = number
        self.pvPrefix = "RADM:SYS0:{num}00:".format(num=self.number)
        self.powerControlPV = PV(self.pvPrefix + "HVCTRL")
        self.powerStatusPV = PV(self.pvPrefix + "HVSTATUS")
        self.voltageReadbackPV = PV(self.pvPrefix + "HVMON")

        self.heads = {head: DecaradHead(number=head, decarad=self)
                      for head in range(1, 11)}


class CommissioningCavity(Cavity):
    def __init__(self, cavityNum, rackObject):
        super().__init__(cavityNum, rackObject)

        self.results = CommissioningCavityResults()

        self.interlock_PV: PV = PV(self.pvPrefix + "RFPERMIT")
        self.stepper_temp_PV: PV = PV(self.pvPrefix + "STEPTEMP")
        self.coupler_top_PV: PV = PV(self.pvPrefix + "CPLRTEMP1")
        self.coupler_bot_PV: PV = PV(self.pvPrefix + "CPLRTEMP2")
        self.hom_us_PV: PV = PV("CTE:CM{cm}:1{cavity}18:UH:TEMP".format(cm=self.cryomodule.name, cavity=self.number))
        self.hom_ds_PV: PV = PV("CTE:CM{cm}:1{cavity}20:DH:TEMP".format(cm=self.cryomodule.name, cavity=self.number))
        self.detune_PV: PV = PV(self.pvPrefix + "DFBEST")

        self.ssa_maxdrive_PV: PV = PV(self.pvPrefix + "SSA:DRV_MAX_REQ")
        self.piezo_enable_PV: PV = PV(self.pvPrefix + "PZT:ENABLE")
        self.piezo_feedback_mode_PV: PV = PV(self.pvPrefix + "PZT:MODECTRL")
        self.piezo_dc_setpoint_PV: PV = PV(self.pvPrefix + "PZT:DAC_SP")
        self.piezo_prerf_run_check_PV: PV = PV(self.pvPrefix + "PZT:TESTSTRT")
        self.piezo_prerf_cha_status_PV: PV = PV(self.pvPrefix + "PZT:CHA_TESTSTAT")
        self.piezo_prerf_chb_status_PV: PV = PV(self.pvPrefix + "PZT:CHB_TESTSTAT")
        self.piezo_prerf_cha_testmsg_PV: PV = PV(self.pvPrefix + "PZT:CHA_TESTMSG1")
        self.piezo_prerf_chb_testmsg_PV: PV = PV(self.pvPrefix + "PZT:CHA_TESTMSG2")
        self.piezo_capacitance_a_PV: PV = PV(self.pvPrefix + "PZT:CHA_C")
        self.piezo_capacitance_b_PV: PV = PV(self.pvPrefix + "PZT:CHB_C")
        self.piezo_prerf_check_status_PV: PV = PV(self.pvPrefix + "PZT:TESTSTS")

        self.measured_probe_qext_PV: PV = PV(self.pvPrefix + "QPROBE_CALC2")
        self.inuse_probe_qext_PV: PV = PV(self.pvPrefix + "QPROBE")
        self.calculate_probe_qext_PV: PV = PV(self.pvPrefix + "QPROBE_CALC1.PROC")
        self.push_probe_qext_PV: PV = PV(self.pvPrefix + "PUSH_QPROBECALC.PROC")

        self.waveformplot_channelpairs: List[Tuple[Optional[str], str]] = [(None, self.revWaveformPV.pvname),
                                                                           (None, self.fwdWaveformPV.pvname),
                                                                           (None, self.cavWaveformPV.pvname)]

        self.acceptancetest_max_amplitude_PV: PV = PV(self.pvPrefix + "AT:AMAX")
        self.acceptancetest_useable_amplitude_PV: PV = PV(self.pvPrefix + "AT:AUSE")
        self.acceptancetest_fe_onset_PV: PV = PV(self.pvPrefix + "AT:FEON_AACT")
        self.acceptancetest_cavity_limitation_PV: PV = PV(self.pvPrefix + "AT:LIMIT")

        self.sel_phaseoffset_PV: PV = PV(self.pvPrefix + "SEL_POFF")
        self.sel_phaseoffset_rdbk_PV: PV = PV(self.pvPrefix + "SEL_POFF_RBV")

        self.feedback_phase_high_PV: PV = PV(self.pvPrefix + "PHAFB_HSUM")
        self.feedback_phase_low_PV: PV = PV(self.pvPrefix + "PHAFB_LSUM")
        self.feedback_amplitude_high_PV: PV = PV(self.pvPrefix + "AMPFB_HSUM")
        self.feedback_amplitude_low_PV: PV = PV(self.pvPrefix + "AMPFB_LSUM")

        self.freq_search_select_PV: PV = PV(self.pvPrefix + "FSCAN:SEL")
        self.freq_search_8pi9_PV: PV = PV(self.pvPrefix + "FSCAN:8PI9MODE")
        self.freq_search_push_PV: PV = PV(self.pvPrefix + "FSCAN:PUSH_8PI9.PROC")

        self.ades_max_srf_PV: PV = PV(self.pvPrefix + "ADES_MAX_SRF")

        # To be populated from the GUI
        self.decaradHead: Optional[DecaradHead] = None
        self.decaradHead.doseRatePV.add_callback(self.checkRadiation)

    def checkRadiation(self):
        if self.decaradHead.avgDose > 0:
            threshold = 16 * self.length
            if self.selAmplitudeActPV.value <= threshold:
                self.results.max_amplitude = threshold

            else:
                self.results.max_amplitude = self.selAmplitudeDesPV.value

            # TODO do we want this? I think we want this
            self.ades_max_srf_PV.put(min(threshold, self.ades_max_srf_PV.value))

        if self.decaradHead.avgDose >= 50:
            self.ades_max_srf_PV.put(self.selAmplitudeDesPV.value)

    @property
    def interlocks_cleared(self) -> bool:
        return self.interlock_PV.value == 1

    def calculate_probe_q(self):
        # TODO check if '1' is actually the right thing to put
        self.calculate_probe_qext_PV.put(1)
        if PROBE_QEXT_LOWER_LIMIT <= self.measured_probe_qext_PV.value <= PROBE_QEXT_UPPER_LIMIT:
            self.push_probe_qext_PV.put(1)
            self.results.probe_qext_value = self.measured_probe_qext_PV.value
            self.results.probe_qext_measured = True
        else:
            raise ProbeQError('Measured probe Q value out of tolerance')


class CommissioningRack(Rack):
    def __init__(self, rackName, cryoObject, cavityClass):
        super().__init__(rackName=rackName, cryoObject=cryoObject, cavityClass=CommissioningCavity)

        self.freq_search_low_PV: PV = PV(self.pvPrefix + "FSCAN:FREQ_START")
        self.freq_search_high_PV: PV = PV(self.pvPrefix + "FSCAN:FREQ_STOP")
        self.freq_search_rms_thresh_PV: PV = PV(self.pvPrefix + "FSCAN:RMS_THRESH")
        self.freq_search_modeoverlap_PV: PV = PV(self.pvPrefix + "FSCAN:MODE+OVERLAP")
        self.freq_search_start_PV: PV = PV(self.pvPrefix + "FSCAN:START")
        self.freq_search_status_PV: PV = PV(self.pvPrefix + "FSCAN:STAT")


class CommissioningMagnet(Magnet):
    def __init__(self, magnettype, cryomodule):
        super(CommissioningMagnet, self).__init__(magnettype, cryomodule)

        self.bdesPV: PV = PV(self.pvprefix + 'BDES')
        self.controlPV: PV = PV(self.pvprefix + 'CTRL')
        self.interlockPV: PV = PV(self.pvprefix + 'INTLKSUMY')
        self.ps_statusPV: PV = PV(self.pvprefix + 'STATE')


class CommissioningCryomodule(Cryomodule):
    def __init__(self, cryoName, linacObject, cavityClass, magnetClass, rackClass):
        super().__init__(cryoName=cryoName, linacObject=linacObject, cavityClass=CommissioningCavity,
                         magnetClass=CommissioningMagnet, rackClass=CommissioningRack)

        self.results = CommissioningCryomoduleResults()
        self.cavity_results = {cavity.number: cavity.results for cavity in self.cavities.values()}

        self.stepper_temp_PVs = []
        self.coupler_top_PVs = []
        self.coupler_bot_PVs = []
        self.hom_us_PVs = []
        self.hom_ds_PVs = []
        self.detune_PVs = []

        for cavity in self.cavities.values():
            self.stepper_temp_PVs.append(cavity.stepper_temp_PV.pvname)
            self.coupler_top_PVs.append(cavity.coupler_top_PV.pvname)
            self.coupler_bot_PVs.append(cavity.coupler_bot_PV.pvname)
            self.hom_us_PVs.append(cavity.hom_us_PV.pvname)
            self.hom_ds_PVs.append(cavity.hom_ds_PV.pvname)
            self.detune_PVs.append(cavity.detune_PV.pvname)

        self.magnet_name_map: Dict[str, CommissioningMagnet] = {'Quad': self.quad, 'XCor': self.xcor, 'YCor': self.ycor}

        # To be populated from the GUI
        self.decarad: Optional[Decarad] = None


COMMISSIONING_LINAC_OBJECTS: List[Linac] = []

# Utility dictionary to map cryomodule name strings to cryomodule objects
COMMISSIONING_CRYOMODULE_OBJECTS: Dict[str, CommissioningCryomodule] = {}

for idx, (name, cryomoduleList) in enumerate(LINAC_TUPLES):
    linac = Linac(linacName=name, cryomoduleStringList=cryomoduleList, cavityClass=CommissioningCavity,
                  cryomoduleClass=CommissioningCryomodule, rackClass=CommissioningRack, magnetClass=CommissioningMagnet)
    COMMISSIONING_LINAC_OBJECTS.append(linac)
    COMMISSIONING_CRYOMODULE_OBJECTS.update(linac.cryomodules)
