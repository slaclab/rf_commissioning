from time import sleep
from typing import Dict

from lcls_tools.superconducting.scLinac import Cryomodule, Magnet, make_lcls_cryomodules

# TODO convert to IDES of 20A
NOMINAL_BDES = 8.5


class CheckoutMagnet(Magnet):
    def __init__(self, magnettype, cryomodule):
        super().__init__(magnettype, cryomodule)

    def checkout(self):
        self.reset()
        self.turnOn()
        self.degauss()
        self.bdes = NOMINAL_BDES
        sleep(3600)
        self.bdes = 0
        self.turnOff()



CHECKOUT_CRYOMODULE_OBJECTS: Dict[str, Cryomodule] = make_lcls_cryomodules(magnetClass=CheckoutMagnet)