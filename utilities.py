from epics import PV
from typing import Optional, List, Dict

from lcls_tools.devices.scLinac import Cavity, Cryomodule, Linac, LINAC_TUPLES, Magnet

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


class CommissioningCavity(Cavity):
    def __init__(self, cavityNum, rackObject):
        super().__init__(cavityNum, rackObject)
        self.interlock_pv = PV(self.pvPrefix + "RFPERMIT")
        self.piezo_prerf_checked: bool = False
        self.piezo_capacitance_a: Optional[float] = None
        self.piezo_capacitance_b: Optional[float] = None
        self.ssa_characterized: bool = False
        self.is_tuned: bool = False
        self.cold_landing_frequency: Optional[float] = None
        self.steps_to_tuned: Optional[int] = None
        self.eightpiovernine_frequency_measured: bool = False
        self.cavity_calibration_run: bool = False
        self.fpc_qext: Optional[float] = None
        self.probe_qext_measured: bool = False
        self.probe_qext_value: Optional[float] = None
        self.piezo_withrf_checked: bool = False
        self.piezo_amplifiergain_a: Optional[float] = None
        self.piezo_amplifiergain_b: Optional[float] = None
        self.piezo_detune_gain: Optional[float] = None
        self.microphonics_captured: bool = False
        self.final_phase_offset: Optional[float] = None
        self.onehourrun_complete: bool = False

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

        self.magnet_checked: bool = False
        self.unit_test_complete: bool = False

        self.magnet_name_map: Dict[str, CommissioningMagnet] = {'Quad': self.quad, 'XCor': self.xcor, 'YCor': self.ycor}


COMMISSIONING_LINAC_OBJECTS: List[Linac] = []

# Utility dictionary to map cryomodule name strings to cryomodule objects
COMMISSIONING_CRYOMODULE_OBJECTS: Dict[str, CommissioningCryomodule] = {}

for idx, (name, cryomoduleList) in enumerate(LINAC_TUPLES):
    linac = Linac(name, cryomoduleList, cavityClass=CommissioningCavity, cryomoduleClass=CommissioningCryomodule)
    COMMISSIONING_LINAC_OBJECTS.append(linac)
    COMMISSIONING_CRYOMODULE_OBJECTS.update(linac.cryomodules)
