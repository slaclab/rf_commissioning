from pydm import Display
from PyQt5 import QtGui
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QMessageBox, QInputDialog, QLineEdit
import math
import smartsheet
from typing import Optional
import csv
from datetime import datetime
import dateutil.parser as parser

class formSubmission(Display):
    def __init__(self, parent=None, args=None):
        super(formSubmission, self).__init__(parent=parent, args=args)


        # Functions related to user choice
        self.ui.submitButton.clicked.connect(self.buttonToggled)
        self.ui.final_freq_help_button.clicked.connect(self.final_freq_help)
        self.ui.cold_freq_help_button.clicked.connect(self.cold_freq_help)
        self.ui.cm_dropdown.currentIndexChanged.connect(self.cm_selection)
        self.ui.cav_dropdown.currentIndexChanged.connect(self.cav_selection)

        self.ui.smartsheet_client = smartsheet.Smartsheet("Bearer FcMv1IwineP5T56sZvXwF0M5fx9XFOkUbhKec")

        self.ui.initialize_cm_dropdown()
        self.ui.initialize_cav_dropdown()
        self.ui.initialize_status_dropdowns()

        self.ui.read_contact_list()
        

 

    
    def ui_filename(self):
        return 'formSubmission.ui'

    def buttonToggled(self):

        self.ui.check_date_format()

        sheetId = "1599832142964612"
        sheet = self.ui.smartsheet_client.Sheets.get_sheet(sheetId,level="2",include="objectValue")

        cm, cav = self.ui.get_CM_cav()
        column_ids, column_names = self.ui.get_columns(sheet)
        row_ids, index = self.ui.get_rows(sheet)
        
        column_to_update = ["Date", "Piezo Capacitance A", "Piezo Capacitance B", "SSA max drive", "Cold Landing Frequency", "Final Frequency", "Steps to Reach Final Frequency", "Qext FPC (cold)", "Qext FPC (warm)", "Qext Probe", "Piezo amplifier gain A", "Piezo amplifier gain B", "Piezo detune gain", "Radiation Onset", "Final Phase Offset", "Commissioned Amplitude", "1 hour run Amplitude", "Additional Details", "1 hour run", "Item Comp"]
        

        data = []
        #data.append(self.ui.operator_edit.text())
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
            
            
        # build the operator field
        operator = self.ui.operator_edit.text()
        if operator!="":
            val = self.ui.get_contact_object(operator)
            if val!="error":
                new_cell.append(smartsheet.models.Cell())
                new_cell[-1].column_id = column_ids[2]
                new_cell[-1].object_value = val
            else:
                self.ui.throw_error("Operator not on approved list, field not updated.")
    
        

            
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

        data = CavityResults()
        r = sheet.rows[index[0]]
        c = r.cells
        for x in c:
            id = x.column_id
            jindex = column_ids.index(id)
            name = column_names[jindex]
            if name=="Operator":
                data.test_lead = x.value

            elif name=="Date":
                data.date = x.value

            elif name=="Piezo Capacitance A":
                data.piezo_capacitance_a = x.value

            elif name=="Piezo Capacitance B":
                data.piezo_capacitance_b = x.value

            elif name=="SSA max drive":
                data.ssa_maxdrive = x.value

            elif name=="Cold Landing Frequency":
                data.cold_land_freq_2K = x.value

            elif name=="Final Frequency":
                data.final_frequency = x.value

            elif name=="Steps to Reach Final Frequency":
                data.steps_to_tuned_2K = x.value

            elif name=="Qext FPC (cold)":
                data.fpc_qext_cold = x.value

            elif name=="Qext FPC (warm)":
                data.fpc_qext_warm = x.value

            elif name=="Qext Probe":
                data.probe_qext_value = x.value

            elif name=="Piezo amplifier gain A":
                data.piezo_amplifiergain_a = x.value

            elif name=="Piezo amplifier gain B":
                data.piezo_amplifiergain_b = x.value

            elif name=="Piezo detune gain":
                data.piezo_detune_gain = x.value

            elif name=="Radiation Onset":
                temp = x.value
                if isinstance(temp,float):
                    data.radiation_onset = str(temp)
                else:
                    data.radiation_onset = temp

            elif name=="Final Phase Offset":
                data.final_phase_offset = x.value

            elif name=="Commissioned Amplitude":
                data.commissioned_amplitude = x.value

            elif name=="1 hour run Amplitude":
                data.onehourrun_amplitude = x.value

            elif name=="1 hour run":
                data.onehourrun_complete = x.value

            elif name=="Item Comp":
                data.item_comp = x.value

            elif name=="Additonal Details":
                data.add_details = x.value
            
        return data
        

    def cav_selection(self):
        if self.ui.cav_dropdown.currentIndex()!=0:
            data = self.ui.readData()
        
            self.ui.printData(data)

    def printData(self,data):
        temp = data.test_lead
        if temp!="None":
           self.ui.operator_edit.setText(temp)
        else:
            self.ui.operator_edit.setText("")
        
        temp = data.date
        if temp!="None":
            self.ui.date_edit.setText(temp)
        else:
            self.ui.date_edit.setText("")
        
        temp = str(data.piezo_capacitance_a)
        if temp!="None":
            self.ui.piezo_cap_a_edit.setText(temp)
        else:
            self.ui.piezo_cap_a_edit.setText("")

        temp = str(data.piezo_capacitance_b)
        if temp!="None":
            self.ui.piezo_cap_b_edit.setText(temp)
        else:
            self.ui.piezo_cap_b_edit.setText("")

        temp = str(data.ssa_maxdrive)
        if temp!="None":
            self.ui.ssa_drive_edit.setText(temp)
        else:
            self.ui.ssa_drive_edit.setText("")

        temp = str(data.cold_land_freq_2K)
        if temp!="None":
            self.ui.cold_freq_edit.setText(temp)
        else:
            self.ui.cold_freq_edit.setText("")

        temp = str(data.final_frequency)
        if temp!="None":
            self.ui.final_freq_edit.setText(temp)
        else:
            self.ui.final_freq_edit.setText("")

        temp = str(data.steps_to_tuned_2K)
        if temp!="None":
            self.ui.ff_steps_edit.setText(temp)
        else:
            self.ui.ff_steps_edit.setText("")

        temp = str(data.fpc_qext_cold)
        if temp!="None":
            temp = format(float(temp),'E')
            self.ui.qext_fpc_cold_edit.setText(temp)
        else:
            self.ui.qext_fpc_cold_edit.setText("")

        temp = str(data.fpc_qext_warm)
        if temp!="None":
            temp = format(float(temp),'E')
            self.ui.qext_fpc_warm_edit.setText(temp)
        else:
            self.ui.qext_fpc_warm_edit.setText("")

        temp = str(data.probe_qext_value)
        if temp!="None":
            temp = format(float(temp),'E')
            self.ui.qext_probe_edit.setText(temp)
        else:
            self.ui.qext_probe_edit.setText("")

        temp = str(data.piezo_amplifiergain_a)
        if temp!="None":
            self.ui.piezo_amp_a_edit.setText(temp)
        else:
            self.ui.piezo_amp_a_edit.setText("")

        temp = str(data.piezo_amplifiergain_b)
        if temp!="None":
            self.ui.piezo_amp_b_edit.setText(temp)
        else:
            self.ui.piezo_amp_b_edit.setText("")

        temp = str(data.piezo_detune_gain)
        if temp!="None":
            self.ui.piezo_detune_edit.setText(temp)
        else:
            self.ui.piezo_detune_edit.setText("")

        temp = data.radiation_onset
        if temp!="None":
            self.ui.rad_edit.setText(temp)
        else:
            self.ui.rad_edit.setText("")

        temp = str(data.final_phase_offset)
        if temp!="None":
            self.ui.phase_edit.setText(temp)
        else:
            self.ui.phase_edit.setText("")

        temp = str(data.commissioned_amplitude)
        if temp!="None":
            self.ui.com_amp_edit.setText(temp)
        else:
            self.ui.com_amp_edit.setText("")

        temp = str(data.onehourrun_amplitude)
        if temp!="None":
            self.ui.hour_run_edit.setText(temp)
        else:
            self.ui.hour_run_edit.setText("")

        temp = data.add_details
        if temp!="None":
            self.ui.add_details_edit.setText(temp)
        else:
            self.ui.add_details_edit.setText("")

        temp = data.onehourrun_complete
        if temp=="None":
            self.ui.hour_run_dropdown.setCurrentIndex(0)
        elif temp=="Issues, see comments":
            self.ui.hour_run_dropdown.setCurrentIndex(2)
        elif temp=="Completed":
            self.ui.hour_run_dropdown.setCurrentIndex(1)
        else:
            self.ui.hour_run_dropdown.setCurrentIndex(0)

        temp = data.item_comp
        if temp=="None":
            self.ui.status_dropdown.setCurrentIndex(0)
        elif temp=="In Progress":
            self.ui.status_dropdown.setCurrentIndex(1)
        elif temp=="Deferred":
            self.ui.status_dropdown.setCurrentIndex(2)
        elif temp=="Minor Issues":
            self.ui.status_dropdown.setCurrentIndex(3)
        elif temp=="Major Issues":
            self.ui.status_dropdown.setCurrentIndex(4)
        elif temp=="Completed":
            self.ui.status_dropdown.setCurrentIndex(5)
        else:
            self.ui.status_dropdown.setCurrentIndex(0)

        
    def read_contact_list(self):
       
        f = open('contact_list.csv')
        csvreader = csv.reader(f)
        rows = []
        self.ui.contacts = []
        for row in csvreader:
            self.ui.contacts.append(smartsheet.models.ContactObjectValue({
                "name": row[0],
                "email": row[1]
                }))

        f.close
        



    def get_contact_object(self,operator):
        con = []
        operators = operator.split(', ')
        
        indices = []
        for op in operators:
            for index, x in enumerate(self.ui.contacts):
                if x.name == op:
                    break
                index = -1
            indices.append(index)


        if -1 in indices:
            val = "error"
        else:
            for i in indices:
                con.append(self.ui.contacts[i])

            val = smartsheet.models.MultiContactObjectValue()
            val.values = con

        return val

    def throw_error(self,message):
        popup = QMessageBox()
        popup.setIcon(QMessageBox.Critical)
        popup.setWindowTitle("ERROR")
        popup.setText(message)
        popup.exec()

    def final_freq_help(self):
        text, ok = QInputDialog().getText(self, "Final Frequency Calculator",
                                          "Detune: 1300+", QLineEdit.Normal,
                                          "0")
        if ok:
            detune = float(text)
            freq = (1.3e9+detune)/1e6
            self.ui.final_freq_edit.setText(str(freq))

    def cold_freq_help(self):
        text, ok = QInputDialog().getText(self, "Cold Landing Frequency Calculator",
                                          "Detune: 1300+", QLineEdit.Normal,
                                          "0")
        if ok:
            detune = float(text)
            freq = (1.3e9+detune)/1e6
            self.ui.cold_freq_edit.setText(str(freq))

    def check_date_format(self):
        text = self.ui.date_edit.text()
        if text!="":
            try:
                date = parser.parse(text)
                self.ui.date_edit.setText(date.strftime("%Y-%m-%d"))
            except:
                print("Bad format")
                self.ui.date_edit.setText("")


    


        

            
class CavityResults:
    piezo_capacitance_a: Optional[float] = None
    piezo_capacitance_b: Optional[float] = None
    ssa_maxdrive: Optional[float] = None
    cold_land_freq_2K: Optional[float] = None
    steps_to_tuned_2K: Optional[int] = None
    final_frequency: Optional[float] = None
    fpc_qext_cold: Optional[float] = None
    fpc_qext_warm: Optional[float] = None
    probe_qext_value: Optional[float] = None
    piezo_amplifiergain_a: Optional[float] = None
    piezo_amplifiergain_b: Optional[float] = None
    piezo_detune_gain: Optional[float] = None
    final_phase_offset: Optional[float] = None
    onehourrun_complete: Optional[str] = None
    onehourrun_amplitude: Optional[float] = None
    radiation_onset: Optional[str] = None
    commissioned_amplitude: Optional[float] = None
    test_lead: Optional[str] = None
    item_comp: Optional[str] = None
    date: Optional[str] = None
    add_details: Optional[str] = None
