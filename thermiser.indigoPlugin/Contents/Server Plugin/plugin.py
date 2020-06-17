#! /usr/bin/env python
# -*- coding: utf-8 -*-

#  Indigo Plugin integrating Heatmiser Slimline thermostats in Indigo
#  This file contains the higher level plugin code.
#  Lower level routines to communicate with the thermostats are contained in the file pymiser.py

#  MIT License
#
#  Copyright (c) 2020 Stefan Prins
#
#  Permission is hereby granted, free of charge, to any person obtaining a copy
#  of this software and associated documentation files (the "Software"), to deal
#  in the Software without restriction, including without limitation the rights
#  to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
#  copies of the Software, and to permit persons to whom the Software is
#  furnished to do so, subject to the following conditions:
#
#  The above copyright notice and this permission notice shall be included in all
#  copies or substantial portions of the Software.
#
#  THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
#  IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
#  FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
#  AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
#  LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
#  OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
#  SOFTWARE.

# version 1.0.0
# last modified 17 jun 2020

import serial
import time
from Queue import *
from pymiser import *

# default name for discovered devices, followed by suffix, e.g. "Thermostat 1"
DEFAULT_DEVICE_NAME = "Thermostat"

class Plugin(indigo.PluginBase):

    def __init__(self, pluginId, pluginDisplayName, pluginVersion, pluginPrefs):
        super(Plugin, self).__init__(pluginId, pluginDisplayName, pluginVersion, pluginPrefs)
        self.comm_port = serial.Serial()
        self.comm_port_open = False

        self.q = Queue()
        self.communicator = PyMiser(self)
        self.debug = pluginPrefs.get("showDebugInfo", False)
        self.detailed_debug = pluginPrefs.get("showDetailDebugInfo", False)
        self.last_poll_time = 0
        self.last_clock_sync_time = 0
        self.poll_interval = int(pluginPrefs.get('pollInterval'), 5) * 60
        self.clock_sync_interval = int(pluginPrefs.get('clockSyncInterval', 2400)) * 60

    def __generateUniqueName(self):
        """Generates a unique name based on DEFAULT_DEVICE_NAME and a trailing number."""
        # Find a unique name for our device:
        existing_names = []
        suffix = 0
        # make a list of all existing device names:
        for dev in indigo.devices:
            existing_names.append(dev.name)
        # keep increasing suffix number until we have a unique name:
        while True:
            suffix = suffix + 1
            proposed_name = "%s %d" % (DEFAULT_DEVICE_NAME, suffix)
            if not any(proposed_name in s for s in existing_names):
                return proposed_name

    def startup(self):
        self.debugLog(u"startup called")
        self.comm_port_open = self.openCommPort()

    def shutdown(self):
        self.debugLog(u"shutdown called")

    def detailDebugLog(self, msg):
        if self.detailed_debug:
            self.debugLog(msg)

    def validatePrefsConfigUi(self, valuesDict):
        # Validate the plugin configuration
        errorsDict = indigo.Dict()
        # use indigo-provided serial port validation:
        self.validateSerialPortUi(valuesDict, errorsDict, u"devicePortFieldId")

        # check clock sync interval
        if not unicode.isdigit(valuesDict["clockSyncInterval"]):
            errorsDict["clockSyncInterval"] = "Clock sync interval must be a positive integer."
        # check poll interval:
        if not unicode.isdigit(valuesDict["pollInterval"]):
            errorsDict["pollInterval"] = "Poll interval must be a positive integer."

        if len(errorsDict) > 0:
            return False, valuesDict, errorsDict
        return True, valuesDict


    def closedPrefsConfigUi(self, valuesDict, userCancelled):
        # Configure plugin dialog closed - update settings:
        if userCancelled:
            return

        self.debug = valuesDict.get("showDebugInfo", False)
        if self.debug:
            indigo.server.log("Debug logging enabled")
            self.detailed_debug = valuesDict.get("showDetailDebugInfo", False)
        else:
            indigo.server.log("Debug logging disabled")
            self.detailed_debug = False
            valuesDict["showDetailDebugInfo"] = False

        try:
            self.poll_interval = int(valuesDict['pollInterval']) * 60
        except Exception as e:
            self.debugLog("Error: cannot read poll interval from preferences - defaulting to 5 minutes.")
            self.debugLog(e)
            self.poll_interval = 300

        try:
            self.clock_sync_interval = int(valuesDict['clockSyncInterval']) * 60
        except Exception as e:
            self.debugLog("Error: cannot read clock sync interval from preferences - defaulting to once a day.")
            self.debugLog(e)
            self.clock_sync_interval = 86400

    def openCommPort(self):

        if self.pluginPrefs["devicePortFieldId_serialConnType"] != "local":
            self.debugLog("Warning: only local serial ports have been tested.")

        self.comm_port.port = self.pluginPrefs['devicePortFieldId_serialPortLocal']
        self.comm_port.baudrate = 4800
        self.comm_port.bytesize = serial.EIGHTBITS
        self.comm_port.parity = serial.PARITY_NONE
        self.comm_port.stopbits = serial.STOPBITS_ONE
        self.comm_port.timeout = 1

        try:
            self.comm_port.open()
            self.debugLog(u"Opened COMM port: %s" % self.comm_port.port)
            return True
        except Exception as e:
            self.errorLog(u"Unable to open COMM port: %s" % self.comm_port.port)
            self.errorLog(e)
            return False

    def deviceStartComm(self, device):
        self.debugLog("Starting comms for: " + device.name)
        device.stateListOrDisplayStateIdChanged()
        return

    def deviceStopComm(self, device):
        self.debugLog("Stopping comms for: " + device.name)

    def runConcurrentThread(self):
        try:
            while True:
                self.sleep(1)
                now = time.time()

                if not self.q.empty():
                    # run the next job in the queue:
                    job = self.q.get()
                    if job:
                        f = job[0]
                        args = job[1]
                        f(*args)

                if (now - self.last_poll_time) > self.poll_interval:
                    self.last_poll_time = now
                    self.pollAllDevices()

                if (now - self.last_clock_sync_time) > self.clock_sync_interval:
                    self.last_clock_sync_time = now
                    self.syncAllDeviceClocks()

        except self.StopThread:
            self.debugLog("Thermiser main thread stopping ")


    def validateDeviceConfigUi(self, valuesDict, typeId, devId):
        """ Gets called when the settings for an individual thermostat are validated"""
        self.debugLog(u"validateDeviceConfigUi")
        errorsDict = indigo.Dict()

        try:
            address = int(valuesDict['address'])
            # if address > 32 or address < 1:
            if address not in range(1, 32):
                errorsDict["address"] = "Address must be a positive integer between 1 and 32."

        except Exception as e:
            errorsDict["address"] = "Address must be a positive integer between 1 and 32."

        if len(errorsDict) > 0:
            return False, valuesDict, errorsDict
        return True, valuesDict

    def validateActionConfigUi(self, valuesDict, typeId, devId):
        self.debugLog(u"validateActionConfigUi for type: " + typeId)
        return True, valuesDict

    def _addressFromProps(self, device):
        """Returns a tuple with a boolean that indicates the address was found and the actual address"""
        props = device.pluginProps

        if "address" not in props:
            self.errorLog("Device %s has no address property" % device.name)
            return False
        try:
            address = int(props['address'])
        except Exception as e:
            self.errorLog("Invalid address in device pluginProps for %s" % device.name)
            self.errorLog(e)
            return False

        return True, address


    def pollAllDevices(self):
        """Iterates through all devices owned by this plugin, and calls pollDevice for each device"""
        self.detailDebugLog("Polling all devices...")
        for device in indigo.devices.iter("self"):
            self.pollDevice(device)

    def pollDevice(self, device):
        """ Queues a poll"""
        self.detailDebugLog("Queueing poll for %s" % device.name)
        self.q.put((self._pollDevice, [device]))

    def _pollDevice(self, device):
        """ the worker function that polls a single device and updates its indigo states"""

        if not self.comm_port_open:
            device.updateStateOnServer("status", u"(No COMMS)")
            return


        self.detailDebugLog("Executing poll for %s" % device.name)

        found, address = self._addressFromProps(device)
        if not found:
            self.debugLog("No address configured for device %s." % device.name)
            return

        device.updateStateOnServer("status", u"(polling)")

        if not self.communicator.update_device_info(address):
            self.debugLog("Device with address %d did not reply - re-queueing..." % address)
            device.updateStateOnServer("status", u"(no reply)")
            self.q.put((self._pollDevice, [device]))
            return

        device.updateStateOnServer(u"airTemp", self.communicator.deviceInfo['airTemp'])
        device.updateStateOnServer(u"setRoomTemp", self.communicator.deviceInfo['setRoomTemp'])
        device.updateStateOnServer(u"heatingOn", self.communicator.deviceInfo['heatingOn'])
        device.updateStateOnServer(u"temperatureFormat", self.communicator.deviceInfo['temperatureFormat'])
        device.updateStateOnServer(u"rateOfChange", self.communicator.deviceInfo['rateOfChange'])

        # update thermostat icon to reflect heating state:
        if self.communicator.deviceInfo['heatingOn']:
            device.updateStateImageOnServer(indigo.kStateImageSel.HvacHeating)
        else:
            device.updateStateImageOnServer(indigo.kStateImageSel.HvacOff)

        if 'hotWaterOn' in self.communicator.deviceInfo:
            device.updateStateOnServer(u"hotWaterOn", self.communicator.deviceInfo['hotWaterOn'])

        # show temperature in state column:
        if self.communicator.deviceInfo['temperatureFormat'] == 'C':
            device.updateStateOnServer("status", u"%d ℃" % self.communicator.deviceInfo['airTemp'])
        elif self.communicator.deviceInfo['temperatureFormat'] == 'F':
            device.updateStateOnServer("status", u"%d ℉" % self.communicator.deviceInfo['airTemp'])

    def syncAllDeviceClocks(self):
        """Iterates through all devices owned by this plugin, and calls syncDeviceClock for each device"""
        self.detailDebugLog("Synchronizing all device clocks...")
        for device in indigo.devices.iter("self"):
            self.syncDeviceClock(device)

    def syncDeviceClock(self, device):
        """Queues a clock sync for the specified device."""
        self.detailDebugLog("Queueing clock sync for %s" % device.name)
        self.q.put( (self._syncDeviceClock, [device]) )

    def _syncDeviceClock(self, device):
        """Worker function that carries out a clock sync. """
        self.detailDebugLog("Executing clock sync for %s" % device.name)
        found, address = self._addressFromProps(device)
        if not found:
            return

        if not "setRoomTemp" in device.states:
            self.errorLog("_syncDeviceClock: Device %s has no setRoomTemp state" % device.name)
            return False

        try:
            if device.states.get("temperatureFormat", "") == "F":
                temperatureUnit = TEMP_UNIT_FAHRENHEIT
                currentRoomSetTemp = int(device.states.get('setRoomTemp', self.communicator.fahrenheit(20)))
            else:
                temperatureUnit = TEMP_UNIT_CELSIUS
                currentRoomSetTemp = int(device.states.get('setRoomTemp', 20))

        except Exception as e:
            self.errorLog("Invalid setRoomTemp in device states for %s. Defaulting to %d" % (device.name,currentRoomSetTemp))
            self.errorLog(e)

        if not self.communicator.syncClock(address,currentRoomSetTemp, temperatureUnit):
            self.debugLog("Device with address %d did not reply to clock sync request - re-queueing..." % address)
            self.q.put((self._syncDeviceClock, [device]))
            return


    def _indigoDeviceWithAddress(self, address):
        """Returns the indigo device that matches address"""
        for dev in indigo.devices.iter("self"):
            props = dev.pluginProps
            if "address" in props:
                if props['address'] == address:
                    return dev
        return None

    def _knownDeviceAddresses(self):
        """Returns a list containing the addresses of all known devices"""
        knownAddresses = []
        for dev in indigo.devices.iter("self"):
            props = dev.pluginProps
            if "address" in props:
                try:
                    knownAddresses.append(int(props["address"]))
                except:
                    pass
        return knownAddresses

    def _addNewDevice(self, deviceInfo):
        new_device = None

        try:
            modelID = deviceInfo['modelID']

        except Exception as e:
            self.errorLog("_addNewDevice: missing model ID in device info block.")
            self.errorLog(e)
            return

        if modelID == 2:
            self.debugLog("Creating device for model: %s" % deviceInfo['model'])
            new_device = indigo.device.create(indigo.kProtocol.Plugin,
                                             self.__generateUniqueName(),
                                             None, deviceTypeId="PRT-N")
        elif modelID == 4:
            self.debugLog("Creating device for model: %s" % deviceInfo['model'])
            new_device = indigo.device.create(indigo.kProtocol.Plugin,
                                             self.__generateUniqueName(),
                                             None, deviceTypeId="PRT-HWN")
        else:
            self.errorLog("Unknown model ID in device info block.")
            return

        if new_device is not None:
            props = new_device.pluginProps
            props["address"] = str(deviceInfo['address'])
            props["version"] = str(deviceInfo['softwareVersion'])
            new_device.replacePluginPropsOnServer(props)

    ########################################
    # Menu Methods
    ########################################

    def discoverDevices(self):
        self.debugLog(u"Scanning RS485 bus to discover devices. This takes up to 35 seconds.")
        known_addresses = self._knownDeviceAddresses()

        for address in range(1, 33):
            if address not in known_addresses:
                self.q.put((self._discoverDevice, [address]))

    def _discoverDevice(self, address):
        self.detailDebugLog("Looking for device at address %s" % address)
        # ask communicator to try to get a device info block from the address:
        if not self.communicator.update_device_info(address):
            # no response from this address
            self.debugLog(u"No device found at address %d" % address)
        else:
            self.debugLog(u"New device found at address %d" % address)
            self._addNewDevice(self.communicator.deviceInfo)

    def toggleDebugging(self):
        if self.debug:
            indigo.server.log("Turning off debug logging")
            self.pluginPrefs["showDebugInfo"] = False
            self.pluginPrefs["showDetailDebugInfo"] = False
        else:
            indigo.server.log("Turning on debug logging")
            self.pluginPrefs["showDebugInfo"] = True

        self.debug = not self.debug

    ################################################################################
    # Custom Plugin Action callbacks (defined in Actions.xml)
    ################################################################################
    def setRoomTemp(self, pluginAction, device):
        self.detailDebugLog("Queueing setRoomTemp for %s" % device.name)
        self.q.put((self._setRoomTemp, [pluginAction, device]))

    def _setRoomTemp(self, pluginAction, device):
        self.detailDebugLog("Executing setRoomTemp for %s" % device.name)
        try:
            temp = int(self.substitute(pluginAction.props.get("setRoomTemp", "")))
            self.detailDebugLog("Variable substitution for setRoomTemp evaluates to %d" % temp)
        except ValueError:
            # The int() cast above might fail if the user didn't enter a number:
            indigo.server.log(u"set room temperature action to device \"%s\" -- invalid temperature value"
                              % (device.name,), isError=True)
            return

        found, address = self._addressFromProps(device)
        if not found:
            self.debugLog("No address configured for device %s." % device.name)
            return

        if device.states["temperatureFormat"] == "F":
            temperature_format = TEMP_UNIT_FAHRENHEIT
        else:
            temperature_format = TEMP_UNIT_SYMBOL_CELSIUS

        sendSuccess = self.communicator.set_temp(address, temp, temperature_format)

        if sendSuccess:
            # If success then log that the command was successfully sent.
            indigo.server.log(u"Sucessfully sent \"%s\" %s to %d" % (device.name, "set room temperature", temp))
            # poll device:
            self.pollDevice(device)
        else:
            # Else log failure but do NOT update state on Indigo Server.
            self.debugLog("Device with address %d did not reply to setRoomTemp request - re-queueing..." % address)
            self.q.put( (self._setRoomTemp, [pluginAction, device]) )

    def _setHotWaterOnState(self, pluginAction, device, state):
        """ Overrides hot water to on (state == 1) or runs the thermostat's programmed schedule (state == 0)"""
        self.detailDebugLog("Executing setHotWaterOnState for %s" % device.name)
        found, address = self._addressFromProps(device)
        if not found:
            self.debugLog("No address configured for device %s." % device.name)
            return

        sendSuccess = self.communicator.set_hw_on_state(address, state)

        if sendSuccess:
            # If success then log that the command was successfully sent.
            if self.detailed_debug:
                indigo.server.log(u"Sucessfully sent \"%s\" %s to %d" % (device.name, "set hot water state", state))
            # poll device:
            self.pollDevice(device)
        else:
            # Else log failure but do NOT update state on Indigo Server.
            self.debugLog("Device with address %d did not reply to setHotWaterState request - re-queueing..." % address)
            self.q.put((self._setHotWaterOnState, [pluginAction, device, state]))

    def setHotWaterOn (self, pluginAction, device):
        """Convenience function to override hot water to on"""
        self.detailDebugLog("Queueing setHotWaterOn for %s" % device.name)
        self.q.put( (self._setHotWaterOnState,[pluginAction, device, 1]) )

    def setHotWaterAsScheduled (self, pluginAction, device):
        """Convenience function to set hot water to run according to thermostat's program"""
        self.detailDebugLog("Queueing setHotWaterAsScheduled for %s" % device.name)
        self.q.put( (self._setHotWaterOnState,[pluginAction, device, 0]) )

