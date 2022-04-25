import dataclasses
from typing import Optional, List, Dict

from epics import PV

from lcls_tools.devices.scLinac.scLinac import Cavity, Cryomodule, Linac, LINAC_TUPLES, Magnet

TESTLEAD_LIST = [
    'Aderhold, Sebastian',
    'Gonnella, Dan',
    'Maniscalco, James',
    'Nelson, Janice',
    'Porter, Ryan',
    'Zacarias, Lisa',
]

# these values are based on the list of enum states found by probing {Magnettype}:L{x}B:{cm}85:CTRL
MAGNET_RESET_VALUE = 10
MAGNET_ON_VALUE = 11
MAGNET_OFF_VALUE = 12
MAGNET_DEGAUSS_VALUE = 13
MAGNET_TRIM_VALUE = 1

NOMINAL_BDES = 8.5


@dataclasses.dataclass
class CommissioningCavityResults:
    piezo_prerf_checked: bool = False
    piezo_capacitance_a: Optional[float] = None
    piezo_capacitance_b: Optional[float] = None
    ssa_maxdrive: Optional[float] = None
    ssa_characterized: bool = False
    is_tuned: bool = False
    cold_landing_frequency: Optional[float] = None
    steps_to_tuned: Optional[int] = None
    eightpiovernine_frequency_measured: bool = False
    cavity_calibration_run: bool = False
    fpc_qext: Optional[float] = None
    probe_qext_measured: bool = False
    probe_qext_value: Optional[float] = None
    piezo_withrf_checked: bool = False
    piezo_amplifiergain_a: Optional[float] = None
    piezo_amplifiergain_b: Optional[float] = None
    piezo_detune_gain: Optional[float] = None
    microphonics_captured: bool = False
    final_phase_offset: Optional[float] = None
    onehourrun_complete: bool = False


@dataclasses.dataclass
class CommissioningCryomoduleResults:
    magnet_checked: bool = False
    unit_test_complete: bool = False


class CommissioningCavity(Cavity):
    def __init__(self, cavityNum, rackObject):
        super().__init__(cavityNum, rackObject)

        self.results = CommissioningCavityResults()

        self.interlock_pv = PV(self.pvPrefix + "RFPERMIT")
        self.stepper_temp_PV = PV(self.pvPrefix + "STEPTEMP")
        self.coupler_top_PV = PV(self.pvPrefix + "CPLRTEMP1")
        self.coupler_bot_PV = PV(self.pvPrefix + "CPLRTEMP2")
        self.hom_us_PV = PV("CTE:CM{cm}:1{cavity}18:UH:TEMP".format(cm=self.cryomodule.name, cavity=self.number))
        self.hom_ds_PV = PV("CTE:CM{cm}:1{cavity}20:DH:TEMP".format(cm=self.cryomodule.name, cavity=self.number))
        self.detune_PV = PV(self.pvPrefix + "DFBEST")

        self.rf_state_PV = PV(self.pvPrefix + "RFCTRL")
        self.ssa_maxdrive_PV = PV(self.pvPrefix + "SSA:DRV_MAX_REQ")
        self.piezo_enable_PV = PV(self.pvPrefix + "PZT:ENABLE")
        self.piezo_feedback_mode_PV = PV(self.pvPrefix + "PZT:MODECTRL")
        self.piezo_dc_setpoint_PV = PV(self.pvPrefix + "PZT:DAC_SP")
        self.piezo_prerf_run_check_PV = PV(self.pvPrefix + "PZT:TESTSTRT")
        self.piezo_prerf_cha_status_PV = PV(self.pvPrefix + "PZT:CHA_TESTSTAT")
        self.piezo_prerf_chb_status_PV = PV(self.pvPrefix + "PZT:CHB_TESTSTAT")
        self.piezo_prerf_cha_testmsg_PV = PV(self.pvPrefix + "PZT:CHA_TESTMSG1")
        self.piezo_prerf_chb_testmsg_PV = PV(self.pvPrefix + "PZT:CHA_TESTMSG2")
        self.piezo_capacitance_a_PV = PV(self.pvPrefix + "PZT:CHA_C")
        self.piezo_capacitance_b_PV = PV(self.pvPrefix + "PZT:CHB_C")
        self.piezo_prerf_check_status_PV = PV(self.pvPrefix + "PZT:TESTSTS")

    @property
    def interlocks_cleared(self):
        return self.interlock_pv.value == 1


class CommissioningMagnet(Magnet):
    def __init__(self, magnettype, cryomodule):
        super(CommissioningMagnet, self).__init__(magnettype, cryomodule)

        self.bdesPV = PV(self.pvprefix + 'BDES')
        self.controlPV = PV(self.pvprefix + 'CTRL')
        self.interlockPV = PV(self.pvprefix + 'INTLKSUMY')
        self.ps_statusPV = PV(self.pvprefix + 'STATE')


class CommissioningCryomodule(Cryomodule):
    def __init__(self, cryoName, linacObject, cavityClass=CommissioningCavity, magnetClass=CommissioningMagnet):
        super().__init__(cryoName, linacObject, CommissioningCavity, CommissioningMagnet)

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


COMMISSIONING_LINAC_OBJECTS: List[Linac] = []

# Utility dictionary to map cryomodule name strings to cryomodule objects
COMMISSIONING_CRYOMODULE_OBJECTS: Dict[str, CommissioningCryomodule] = {}

for idx, (name, cryomoduleList) in enumerate(LINAC_TUPLES):
    linac = Linac(name, cryomoduleList, cavityClass=CommissioningCavity, cryomoduleClass=CommissioningCryomodule)
    COMMISSIONING_LINAC_OBJECTS.append(linac)
    COMMISSIONING_CRYOMODULE_OBJECTS.update(linac.cryomodules)
