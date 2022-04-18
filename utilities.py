from typing import Optional, List, Dict

from epics import PV
from lcls_tools.devices.scLinac import Cavity, Cryomodule, Linac, LINAC_TUPLES

testlead_list = [
    'Aderhold, Sebastian',
    'Gonnella, Dan',
    'Maniscalco, James',
    'Nelson, Janice',
    'Porter, Ryan',
    'Zacarias, Lisa',
]

cavity_list = [
    '1',
    '2',
    '3',
    '4',
    '5',
    '6',
    '7',
    '8',
    '9',
]

cryomodule_list = [
    '01',
    '02',
    '03',
    'H1',
    'H2',
    '04',
    '05',
    '06',
    '07',
    '08',
    '09',
    '10',
    '11',
    '12',
    '13',
    '14',
    '15',
    '16',
    '17',
    '18',
    '19',
    '21',
    '22',
    '23',
    '24',
    '25',
    '26',
    '27',
    '28',
    '29',
    '30',
    '31',
    '32',
    '33',
    '34',
    '35',
]


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


class CommissioningCryomodule(Cryomodule):
    def __init__(self, cryoName, linacObject, cavityClass=CommissioningCavity):
        super().__init__(cryoName, linacObject, CommissioningCavity)

        self.magnet_checked: bool = False
        self.unit_test_complete: bool = False

        magnet_prefix = "{{type}}:{linac}:{cm}85:".format(linac=self.linac.name, cm=self.name)
        self.quad_prefix = magnet_prefix.format(type="QUAD")
        self.xcor_prefix = magnet_prefix.format(type="XCOR")
        self.ycor_prefix = magnet_prefix.format(type="YCOR")

        self.quad_control_pv = PV(self.quad_prefix + 'CTRL')
        self.xcor_control_pv = PV(self.xcor_prefix + 'CTRL')
        self.ycor_control_pv = PV(self.ycor_prefix + 'CTRL')


COMMISSIONING_LINAC_OBJECTS: List[Linac] = []

# Utility dictionary to map cryomodule name strings to cryomodule objects
COMMISSIONING_CRYOMODULE_OBJECTS: Dict[str, CommissioningCryomodule] = {}

for idx, (name, cryomoduleList) in enumerate(LINAC_TUPLES):
    linac = Linac(name, cryomoduleList, cavityClass=CommissioningCavity, cryomoduleClass=CommissioningCryomodule)
    COMMISSIONING_LINAC_OBJECTS.append(linac)
    COMMISSIONING_CRYOMODULE_OBJECTS.update(linac.cryomodules)
