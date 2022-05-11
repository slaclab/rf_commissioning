import dataclasses
import fcntl
from typing import Optional

from lcls_tools.common.data_analysis.archiver import Archiver

TESTLEAD_LIST = [
    'Aderhold, Sebastian',
    'Gonnella, Dan',
    'Maniscalco, James',
    'Nelson, Janice',
    'Porter, Ryan',
    'Zacarias, Lisa',
]

RADIATION_LIMIT = 50
GRADIENT_THRESHOLD_RADLIMIT = 16
# this value is based on historical data, when the decarads were on, but not seeing any FE from a cavity
DECARAD_BACKGROUND_READING = 4

PROBE_QEXT_UPPER_LIMIT = 3e12
PROBE_QEXT_LOWER_LIMIT = 1e11

DECARAD_ON_VALUE = 0
DECARAD_OFF_VALUE = 1

PIEZO_ENABLE_VALUE = 1
PIEZO_DISABLE_VALUE = 0
PIEZO_MANUAL_VALUE = 0
PIEZO_SCRIPT_RUNNING_VALUE = 2
PIEZO_SCRIPT_COMPLETE_VALUE = 1
PIEZO_PRERF_CHECKOUT_STATUS_VALUE = 1

ARCHIVER = Archiver("lcls")

FREQ_SEARCH_MODEOVERLAP = 1000
FREQ_SEARCH_RMS_THRESH = 10
FREQ_SEARCH_HIGH = 50000
FREQ_SEARCH_LOW = -900000

STEPPERTEMP_PLOT_KEY = 'steppertemp'
CMVACUUM_PLOT_KEY = 'cmvacuum'
CRYOSIGNALS_PLOT_KEY = 'cryosignals'
MAGNET_PLOT_KEY = 'magnet'
HOMUS_PLOT_KEY = 'homus'
HOMDS_PLOT_KEY = 'homds'
CPLRTOP_PLOT_KEY = 'cplrtop'
CPLRBOT_PLOT_KEY = 'cplrbot'
SINGLE_CAVITY_PLOT_KEY = 'singlecavity'
FREQUENCY_PLOT_KEY = 'frequency'
RFWAVEFORM_PLOT_KEY = 'rfwaveform'
DECARAD_PLOT_KEY = 'decarad'
DETUNE_PLOT_KEY = "detune"

STEPPER_MAX_STEPS = 5000000

MICROSTEPS_PER_STEP = 256

# These are very rough values obtained empirically
ESTIMATED_STEPS_PER_HZ = MICROSTEPS_PER_STEP / 1.4
ESTIMATED_STEPS_PER_HZ_HL = MICROSTEPS_PER_STEP / 18.3


class ProbeQError(Exception):
    """
    Exception thrown during cavity probe Q calculation
    """

    def __init__(self, message):
        self.message = message
        super().__init__(self.message)


class DetuneError(Exception):
    """
    Exception thrown during cavity tuning
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


class PiezoError(Exception):
    """
    Exception thrown piezo checks
    """

    def __init__(self, message):
        self.message = message
        super().__init__(self.message)


# TODO add handling of multiple GUI instances
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
    final_frequency: Optional[float] = None
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


# got this from stackoverflow: https://stackoverflow.com/questions/4843359/python-lock-a-file
def acquireLock():
    ''' acquire exclusive lock file access '''
    locked_file_descriptor = open('lockfile.LOCK', 'w+')
    fcntl.lockf(locked_file_descriptor, fcntl.LOCK_EX)
    return locked_file_descriptor


def releaseLock(locked_file_descriptor):
    ''' release exclusive lock file access '''
    locked_file_descriptor.close()
