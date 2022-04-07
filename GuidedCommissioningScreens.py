from typing import Optional

from epics import PV
from lcls_tools.devices.scLinac import CRYOMODULE_OBJECTS, Cavity, Cryomodule
from pydm import Display

import utilities as util


class GuidedCommissioningScreens(Display):

    def __init__(self, parent=None, args=None):
        super(GuidedCommissioningScreens, self).__init__(parent=parent, args=args)

        # declare class variables
        self.current_cm = None
        self.current_cavity = None
        self.current_decarad = None
        self.current_pvprefix = None

        # setup: initial setup tab
        self.setup_combo_boxes()

        # setup: magnet tab
        self.ui.label_7.setText('Current cryomodule is:')
        self.ui.label_8.setText('not defined yet')

        # setup: StripTool & Interlock
        self.ui.button_decaradgui.filenames = ["$TOOLS/pydm/display/ads/decarad_main.ui"]
        self.ui.button_decaradgui.openInNewWindow = True

        # on press of start button read entries from initial setup tab
        self.ui.start_button.clicked.connect(self.initial_setup)

    def ui_filename(self):
        return 'GuidedCommissioningScreens.ui'

    def setup_combo_boxes(self):
        self.ui.testlead.addItems(util.testlead_list)
        self.ui.testlead.setEnabled(True)

        self.ui.pick_linacsection.addItems(["L0B", "L1B", "L2B", "L3B"])
        self.ui.pick_linacsection.setEnabled(True)

        self.ui.pick_cavity.addItems(util.cavity_list)
        self.ui.pick_cavity.setEnabled(True)

        self.ui.pick_radmonitor.addItems(["DecaRad 1", "DecaRad 2"])
        self.ui.pick_radmonitor.setEnabled(True)

        self.ui.pick_cm.addItems(util.cryomodule_list)
        self.ui.pick_cm.setEnabled(True)

    def initial_setup(self):
        # read the initial setup from inputs
        self.current_cm = self.ui.pick_cm.currentText()
        self.current_cavity = int(self.ui.pick_cavity.currentText())
        self.current_decarad = self.ui.pick_radmonitor.currentText()
        self.current_pvprefix = CRYOMODULE_OBJECTS[self.current_cm].cavities[self.current_cavity].pvPrefix
        self.ui.label_8.setText(self.current_pvprefix)

        # set variables for other tabs
        # Striptool + Interlock tab
        if self.current_decarad == "DecaRad 1":
            self.ui.button_decaradgui.macros = {"P": "RADM:SYS0:100", "M": 1}

        else:
            self.ui.button_decaradgui.macros = {"P": "RADM:SYS0:200", "M": 2}

        self.ui.button_interlockoverview.filenames('$TOOLS/edm/display/llrf/rf_srf_intlk_nocryo_embed.edl)')
        # self.ui.button_interlockoverview.macros('C=1,RFS=1A,R=A,CM=ACCL:L1B:02,CH=1,ID=01') #hardcoded set of macros for testing
        # self.ui.button_interlockoverview.macros(self.make_interlock_macro_string())

        self.ui.button_striptool_cavtemps.commands(
            'srf_makeAutoPlot.py st cavtemps ACCL:L0B:01; StripTool $STRIP_CONFIGFILE_DIR/srf_cavtemps.stp'
        )
        self.ui.button_striptool_vacuum.commands(
            'srf_makeAutoPlot.py st cavtemps ACCL:L0B:01; StripTool $STRIP_CONFIGFILE_DIR/srf_cavtemps.stp'
        )

    def make_interlock_macro_string(self):

        c = str(self.current_cavity.number)

        if self.current_cavity.number in (1, 2):
            rfs = '1A'
        elif self.current_cavity.number in (3, 4):
            rfs = '2A'
        elif self.current_cavity.number in (5, 6):
            rfs = '1B'
        else:
            rfs = '2B'

        if 1 <= self.current_cavity.number <= 4:
            r = 'A'
        else:
            r = 'B'

        cm = self.current_cm.pvPrefix.rstrip(":0")  # need to remove trailing colon and zeroes to match needed format

        id = self.current_cm.name

        if self.current_cavity.number in (2, 4):
            ch = 2
        else:
            ch = 1

        macro_string = 'C=' + c + ',RFS=' + rfs + ',R=' + r + ',CM=' + cm + ',CH=' + ch + ',ID=' + id
        return macro_string


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
