import json
from time import sleep
from typing import Dict, Optional

import commissioningUtilities as utils
from commissioningLinac import ALL_CRYOMODULES, COMMISSIONING_CRYOMODULE_OBJECTS, Piezo
from lcls_tools.common.pyepics_tools import pyepicsUtils

# The first element in this list is just an empty string
ALL_CRYOMODULES.pop(0)
results: Dict[str, Dict[int, Optional[str]]] = {cm: {cav: None for cav in range(1, 9)}
                                                for cm in ALL_CRYOMODULES}

for cm in ALL_CRYOMODULES:
    cmObj = COMMISSIONING_CRYOMODULE_OBJECTS[cm]
    for cavity in cmObj.cavities.values():
        try:
            piezo: Piezo = cavity.piezo
            piezo.enable_PV.put(utils.PIEZO_ENABLE_VALUE)
            piezo.feedback_mode_PV.put(utils.PIEZO_MANUAL_VALUE)
            piezo.dc_setpoint_PV.put(0)
            piezo.prerf_test_start_pv.put(1, waitForPut=False)
            while piezo.prerf_test_status_pv.value == utils.PIEZO_SCRIPT_RUNNING_VALUE:
                sleep(1)
            if piezo.prerf_test_status_pv.value != utils.PIEZO_SCRIPT_COMPLETE_VALUE:
                results[cm][cavity.number] = 'FAIL'
                continue
            
            if (piezo.prerf_cha_status_PV.value == utils.PIEZO_PRERF_CHECKOUT_PASS_VALUE
                    and piezo.prerf_chb_status_PV.value == utils.PIEZO_PRERF_CHECKOUT_PASS_VALUE):
                results[cm][cavity.number] = "PASS"
            
            else:
                results[cm][cavity.number] = 'FAIL'
        
        except (utils.PiezoError, pyepicsUtils.PVInvalidError) as e:
            print(cm, cavity.number, e)
            results[cm][cavity.number] = 'FAIL'
        
        print(cm, cavity.number, results[cm][cavity.number])
        
        with open('allPiezoPreRF.json', 'w') as fp:
            json.dump(results, fp, sort_keys=True, indent=4)
