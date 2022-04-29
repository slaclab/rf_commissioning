import dataclasses
from typing import Optional

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

# TODO convert to IDES of 20A
NOMINAL_BDES = 8.5

RADIATION_LIMIT = 50
GRADIENT_THRESHOLD_RADLIMIT = 16
# this value is based on historical data, when the decarads were on, but not seeing any FE from a cavity
DECARAD_BACKGROUND_READING = 4


class ProbeQError(Exception):
    """
    Exception thrown during cavity probe Q calculation
    """

    def __init__(self, message):
        self.message = message
        super().__init__(self.message)


class FreqSearchError(Exception):
    """
    Exception thrown during 8pi/9 frequency search
    """

    def __init__(self, message):
        self.message = message
        super().__init__(self.message)


class RadError(Exception):
    """
    Exception thrown during SELAP ramp up
    """

    def __init__(self, message):
        self.message = message
        super().__init__(self.message)


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
    max_amplitude: Optional[float] = None


@dataclasses.dataclass
class CommissioningCryomoduleResults:
    magnet_checked: bool = False
    unit_test_complete: bool = False
