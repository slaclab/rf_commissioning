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

        self.update_current_cavity_and_cm()

        # setup: magnet tab
        self.ui.label_7.setText('Current cryomodule is:')
        self.ui.label_8.setText('not defined yet')

        # setup: StripTool & Interlock
        self.ui.button_decaradgui.filenames = ["$TOOLS/pydm/display/ads/decarad_main.ui"]
        self.ui.button_decaradgui.openInNewWindow = True
        self.update_current_decarad()

        self.initial_setup()

    def ui_filename(self):
        return 'GuidedCommissioningScreens.ui'

    def setup_combo_boxes(self):
        self.ui.testlead.addItems(util.testlead_list)

        self.ui.pick_cavity.addItems(util.cavity_list)

        self.ui.pick_cavity.currentIndexChanged.connect(self.update_current_cavity_and_cm)

        self.ui.pick_radmonitor.currentIndexChanged.connect(self.update_current_decarad)

        self.ui.pick_cm.addItems(util.cryomodule_list)

        self.ui.pick_cm.currentIndexChanged.connect(self.update_current_cavity_and_cm)

    def update_current_cavity_and_cm(self):
        self.current_cm = util.COMMISSIONING_CRYOMODULE_OBJECTS[self.ui.pick_cm.currentText()]
        self.current_cavity = self.current_cm.cavities[int(self.ui.pick_cavity.currentText())]

    def update_current_decarad(self):
        self.current_decarad = self.ui.pick_radmonitor.currentText()
        self.ui.button_decaradgui.macros = {"P": "RADM:SYS0:{decarad}00".format(decarad=self.current_decarad),
                                            "M": self.current_decarad}

    def initial_setup(self):
        # set variables for other tabs
        # Striptool + Interlock tab

        self.ui.button_interlockoverview.filenames = ['$TOOLS/edm/display/llrf/rf_srf_intlk_nocryo_embed.edl']

        self.ui.button_striptools.commands = [
            'srf_makeAutoPlot.py st cavtemps {prefix}; StripTool $STRIP_CONFIGFILE_DIR/srf_cavtemps.stp'.format(
                prefix=self.current_cm.pvPrefix[:-2])
        ]

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

        cm = self.current_cm.pvPrefix[:-2]  # need to remove trailing colon and zeroes to match needed format

        id = self.current_cm.name

        if self.current_cavity.number in (2, 4):
            ch = 2
        else:
            ch = 1

        macro_string = "C={c},RFS={rfs},R={r},CM={cm},CH={ch},ID={id}".format(c=c, rfs=rfs, r=r, cm=cm, ch=ch, id=id)
        return macro_string
