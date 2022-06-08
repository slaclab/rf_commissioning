from typing import Dict, List, Tuple

from epics import PV

from lcls_tools.superconducting.scLinac import Cryomodule, Magnet, make_lcls_cryomodules

# TODO convert to IDES of 20A
NOMINAL_BDES = 8.5

CONTROL_PLOT_KEY = 'controlplot'
LIVE_PLOT_KEY = 'liveplot'


class CheckoutMagnet(Magnet):
    def __init__(self, magnettype, cryomodule):
        super().__init__(magnettype, cryomodule)
    
    def start_checkout(self):
        self.reset()
        self.turnOn()
        self.degauss()
        self.bdes = NOMINAL_BDES
    
    def end_checkout(self):
        self.bdes = 0
        self.turnOff()


class CheckoutCryomodule(Cryomodule):
    def __init__(self, cryoName, linacObject, cavityClass, magnetClass,
                 rackClass, isHarmonicLinearizer, ssaClass, stepperClass):
        super().__init__(cryoName, linacObject, magnetClass=CheckoutMagnet)
        
        mag_temp_formatter = "240{num}:MP:TEMP"
        self.magnet_temp_1_PV: PV = PV(self.ctePrefix + mag_temp_formatter.format(num=1))
        self.magnet_temp_2_PV: PV = PV(self.ctePrefix + mag_temp_formatter.format(num=2))
        self.magnet_temp_3_PV: PV = PV(self.ctePrefix + mag_temp_formatter.format(num=3))
        self.magnet_temp_4_PV: PV = PV(self.ctePrefix + mag_temp_formatter.format(num=4))
        
        self.magnet_voltage_12_vd_PV: PV = PV(self.cvtPrefix + "12:VD:VOLTAGE")
        self.magnet_voltage_34_vd_PV: PV = PV(self.cvtPrefix + "34:VD:VOLTAGE")
        self.magnet_voltage_12_hd_PV: PV = PV(self.cvtPrefix + "12:HD:VOLTAGE")
        self.magnet_voltage_34_hd_PV: PV = PV(self.cvtPrefix + "34:HD:VOLTAGE")
        self.magnet_voltage_12_sq_PV: PV = PV(self.cvtPrefix + "12:SQ:VOLTAGE")
        self.magnet_voltage_34_sq_PV: PV = PV(self.cvtPrefix + "34:SQ:VOLTAGE")
        
        self.magnet_pv_pairs: List[Tuple[str, str]] = [(self.magnet_temp_1_PV.pvname, None),
                                                       (self.magnet_temp_2_PV.pvname, None),
                                                       (self.magnet_temp_3_PV.pvname, None),
                                                       (self.magnet_temp_4_PV.pvname, None),
                                                       (self.magnet_voltage_12_vd_PV.pvname, None),
                                                       (self.magnet_voltage_34_vd_PV.pvname, None),
                                                       (self.magnet_voltage_12_hd_PV.pvname, None),
                                                       (self.magnet_voltage_34_hd_PV.pvname, None),
                                                       (self.magnet_voltage_12_sq_PV.pvname, None),
                                                       (self.magnet_voltage_34_sq_PV.pvname, None)]


CHECKOUT_CRYOMODULE_OBJECTS: Dict[str, Cryomodule] = make_lcls_cryomodules(magnetClass=CheckoutMagnet,
                                                                           cryomoduleClass=CheckoutCryomodule)
