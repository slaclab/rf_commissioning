from pydm import Display
from PyQt5 import QtGui
from PyQt5.QtCore import Qt
import math
import smartsheet

class formSubmission(Display):
    def __init__(self, parent=None, args=None):
        super(formSubmission, self).__init__(parent=parent, args=args)


        # Functions related to user choice
        self.ui.submitButton.clicked.connect(self.buttonToggled)
        self.ui.cm_dropdown.currentIndexChanged.connect(self.cm_selection)
        self.ui.cav_dropdown.currentIndexChanged.connect(self.cav_selection)

        self.ui.smartsheet_client = smartsheet.Smartsheet("Bearer FcMv1IwineP5T56sZvXwF0M5fx9XFOkUbhKec")

        self.ui.initialize_cm_dropdown()
        self.ui.initialize_cav_dropdown()
        self.ui.initialize_status_dropdowns()

 

    
    def ui_filename(self):
        return 'formSubmission.ui'

    def buttonToggled(self):
        sheetId = "1599832142964612"
        sheet = self.ui.smartsheet_client.Sheets.get_sheet(sheetId)

        cm, cav = self.ui.get_CM_cav()
        column_ids, column_names = self.ui.get_columns(sheet)
        row_ids, index = self.ui.get_rows(sheet)
        
        column_to_update = ["Date", "Piezo Capacitance A", "Piezo Capacitance B", "SSA max drive", "Cold Landing Frequency", "Final Frequency", "Steps to Reach Final Frequency", "Qext FPC (cold)", "Qext FPC (warm)", "Qext Probe", "Piezo amplifier gain A", "Piezo amplifier gain B", "Piezo detune gain", "Radiation Onset", "Final Phase Offset", "Commissioned Amplitude", "1 hour run Amplitude", "Additional Details", "1 hour run", "Item Comp"]
        
        data = []
        data.append(self.ui.date_edit.text())
        data.append(self.ui.myfloat(self.ui.piezo_cap_a_edit.text()))
        data.append(self.ui.myfloat(self.ui.piezo_cap_b_edit.text()))
        data.append(self.ui.myfloat(self.ui.ssa_drive_edit.text()))
        data.append(self.ui.myfloat(self.ui.cold_freq_edit.text()))
        data.append(self.ui.myfloat(self.ui.final_freq_edit.text()))
        data.append(self.ui.myfloat(self.ui.ff_steps_edit.text()))
        data.append(self.ui.myfloat(self.ui.qext_fpc_cold_edit.text()))
        data.append(self.ui.myfloat(self.ui.qext_fpc_warm_edit.text()))
        data.append(self.ui.myfloat(self.ui.qext_probe_edit.text()))
        data.append(self.ui.myfloat(self.ui.piezo_amp_a_edit.text()))
        data.append(self.ui.myfloat(self.ui.piezo_amp_b_edit.text()))
        data.append(self.ui.myfloat(self.ui.piezo_detune_edit.text()))
        data.append(self.ui.rad_edit.text())
        data.append(self.ui.myfloat(self.ui.phase_edit.text()))
        data.append(self.ui.myfloat(self.ui.com_amp_edit.text()))
        data.append(self.ui.myfloat(self.ui.hour_run_edit.text()))
        data.append(self.ui.add_details_edit.text())
        data.append(self.ui.hour_run_dropdown.currentText())
        data.append(self.ui.status_dropdown.currentText())


        cIndex = []
        for x in column_to_update:
            cIndex.append(column_names.index(x))

        # build the new cells
        new_cell = []
        for i in range(len(cIndex)):
            new_cell.append(smartsheet.models.Cell())
            new_cell[-1].column_id = column_ids[cIndex[i]]
            new_cell[-1].value = data[i]



            
        # build the new row
        new_row = smartsheet.models.Row()
        new_row.id = row_ids[index[0]]
        for x in new_cell:
            new_row.cells.append(x)

            # update the row
        updated_row = self.ui.smartsheet_client.Sheets.update_rows(sheetId,new_row)




    def initialize_cm_dropdown(self):
        self.ui.cm_dropdown.addItem("Cryomodule")
        for i in range(35):
            self.ui.cm_dropdown.addItem("CM"+str(i+1).zfill(2))
        for i in range(2):
            self.ui.cm_dropdown.addItem("CMH"+str(i+1))

    def initialize_cav_dropdown(self):
        self.ui.cav_dropdown.addItem("Cavity")
        for i in range(8):
            self.ui.cav_dropdown.addItem("Cavity "+str(i+1))

        
    def cm_selection(self):
        index = self.ui.cm_dropdown.currentIndex()
        if index != 0:
            self.ui.cav_dropdown.setDisabled(False)
            self.ui.cav_dropdown.setCurrentIndex(0)
        else:
            self.ui.cav_dropdown.setDisabled(True)
            self.ui.cav_dropdown.setCurrentIndex(0)

    def get_CM_cav(self):
        cm = self.ui.cm_dropdown.currentText()
        cav = self.ui.cav_dropdown.currentText()
        return cm, cav

    def get_columns(self,sheet):
        c = sheet.columns
        column_ids = []
        column_names = []
        for x in c:
            column_ids.append(x.id)
            column_names.append(x.title)
        return column_ids, column_names

    def get_rows(self,sheet):
        r = sheet.rows
        row_ids = []
        for x in r:
            row_ids.append(x.id)
        
        cms = []
        cavs = []
        for x in r:
            cms.append(x.cells[0].value)
            cavs.append(x.cells[1].value)

        cm, cav = self.ui.get_CM_cav()

        indices_cm = [i for i, x in enumerate(cms) if x == cm]
        indices_cav = [i for i, x in enumerate(cavs) if x == cav]
        index = [c for c in indices_cm if c in indices_cav]

        return row_ids, index

        
        
    def initialize_status_dropdowns(self):
          self.ui.hour_run_dropdown.addItem("Not Started")
          self.ui.hour_run_dropdown.addItem("Completed")
          self.ui.hour_run_dropdown.addItem("Issues, see comments")

          self.ui.status_dropdown.addItem("Not Started")
          self.ui.status_dropdown.addItem("In Progress")          
          self.ui.status_dropdown.addItem("Deferred")
          self.ui.status_dropdown.addItem("Minor Issues")
          self.ui.status_dropdown.addItem("Major Issues")

          self.ui.status_dropdown.addItem("Completed")

    def myfloat(self,data):
        if data == '':
            data = data
        else:
            data = float(data)
        return data

    def readData(self):
        cm, cav = self.ui.get_CM_cav()

        sheetId = "1599832142964612"
        sheet = self.ui.smartsheet_client.Sheets.get_sheet(sheetId)

        column_ids, column_names = self.ui.get_columns(sheet)
        row_ids, index = self.ui.get_rows(sheet)

        data = dataBlock()
        data.cm = cm
        data.cavity = cav
        
        return data
        

    def cav_selection(self):
        data = self.ui.readData()
        
        self.ui.printData(data)

    def printData(self,data):
        print(data.cm)

class dataBlock:
    def __init__(self,parent=None,args=None):
        self.cm = ""
        self.cavity = ""
            
