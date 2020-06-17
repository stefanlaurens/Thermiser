# -*- coding: utf-8 -*-

#  Implements a PyMiser low-level communication object to interface with HeatMiser DT / DT-E / PRT / PRT-E / PRT-HW
#  thermostats over a serial connection and RS485 interface.

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

import datetime
from pm_crc import *

FUNCTION_READ = 0
FUNCTION_WRITE = 1
MASTER_ADDRESS = 0x81  # address of 'master' unit, i.e. this computer.
MAX_REPLY_SIZE = 200
MODEL_NAMES = ['DT', 'DT-E', 'PRT', 'PRT-E', 'PRT-HW']
SENSOR_NAMES = ['built-in air only', 'remote air only', 'floor only', 'built-in air + floor', 'remote-air + floor']
FROST_PROTECTION_NAMES = ['disabled', 'enabled']
RUN_MODE_NAMES = ['heating', 'frost protection']
PROGRAM_MODE_NAMES = ['5/2 mode', '7 day mode']
UNKNOWN_NAME = '(unknown)'
MIN_TEMP_C = 5
MAX_TEMP_C = 35
TEMP_UNIT_CELSIUS = 0
TEMP_UNIT_FAHRENHEIT = 1
TEMP_UNIT_SYMBOL_CELSIUS = u"℃"
TEMP_UNIT_SYMBOL_FAHRENHEIT = u"℉"


class PyMiser(object):
    def __init__(self, owner):
        self.crc = crc()  # CRC calculator object
        self.owner = owner  # Indigo plugin
        self.deviceInfo = dict()

    def fahrenheit (self, celsius):
        """ Converts celsius to Fahrenheit"""
        return celsius * (9.0 / 5.0) + 32

    def _parseDCB(self, dcb):
        """Returns a dictionary with the contents of the dcb"""
        result = {'frameLength': dcb[2] * 256 + dcb[1], 'address': dcb[3]}
        dcb_offset = 9  # type: int
        result['dcbLen'] = dcb[dcb_offset] * 256 + dcb[dcb_offset+1]
        vendor_id = dcb[dcb_offset+2]
        if vendor_id == 0:
            result['vendor'] = 'Heatmiser'
        else:
            result['vendor'] = 'o.e.m.'

        result['softwareVersion'] = dcb[dcb_offset + 3] & 0x7f
        result['floorLimitState'] = dcb[dcb_offset + 3] >> 7

        model_id = dcb[dcb_offset + 4]
        result['modelID'] = model_id
        if 0 <= model_id < len(MODEL_NAMES):
            result['model'] = MODEL_NAMES[model_id]
        else:
            result['model'] = UNKNOWN_NAME

        if dcb[dcb_offset + 5] == 0:
            result['temperatureFormat'] = 'C'
        else:
            result['temperatureFormat'] = 'F'

        result['switchDifferential'] = dcb[dcb_offset + 6]

        frost_protection_code = dcb[dcb_offset + 7]
        if 0 <= frost_protection_code < len(FROST_PROTECTION_NAMES):
            result['frostProtection'] = FROST_PROTECTION_NAMES[frost_protection_code]
        else:
            result['frostProtection'] = UNKNOWN_NAME

        result['calibrationOffset'] = dcb[dcb_offset +8] * 256 + dcb[dcb_offset+9]
        result['outputDelay'] = dcb[dcb_offset+10]
        # offset +11 is the address, which we already know, so we're ignoring it.
        result['upDownKeyLimit'] = dcb[dcb_offset+12]

        sensor_selection_code = dcb[dcb_offset+13]
        result['sensorSelectionCode'] = sensor_selection_code
        if 0 <= sensor_selection_code < len(SENSOR_NAMES):
            result['sensor'] = SENSOR_NAMES[sensor_selection_code]
        else:
            result['sensor'] = UNKNOWN_NAME

        result['optimumStart'] = dcb[dcb_offset+14]
        result['rateOfChange'] = dcb[dcb_offset+15]

        program_mode_code = dcb[dcb_offset+16]
        result['programModeCode'] = program_mode_code
        if 0 <= program_mode_code < len(PROGRAM_MODE_NAMES):
            result['programMode'] = PROGRAM_MODE_NAMES[program_mode_code]

        result['frostProtectTemp'] = dcb[dcb_offset+17]
        result['setRoomTemp'] = dcb[dcb_offset+18]
        result['floorMaxLimit'] = dcb[dcb_offset + 19]
        result['floorMaxLimitEnable'] = dcb[dcb_offset + 19]
        result['On'] = dcb[dcb_offset + 21]
        result['keyLock'] = dcb[dcb_offset + 22]

        run_mode_code = dcb[dcb_offset + 23]
        if 0 <= run_mode_code < len(RUN_MODE_NAMES):
            result['runMode'] = RUN_MODE_NAMES[run_mode_code]
        else:
            result['runMode'] = UNKNOWN_NAME

        result['holidayHours'] = dcb[dcb_offset + 24] * 256 + dcb[dcb_offset+25]
        result['tempHoldMinutes'] = dcb[dcb_offset + 26] * 256 + dcb[dcb_offset+27]

        remote_air_temp = (dcb[dcb_offset + 28] * 256 + dcb[dcb_offset+29]) / 10
        if remote_air_temp == 0xFFFF:
            remote_air_temp = None
        result['remoteAirTemp'] = remote_air_temp

        floor_temp = (dcb[dcb_offset + 30] * 256 + dcb[dcb_offset + 31]) / 10
        if floor_temp == 0xFFFF:
            floor_temp = None
        result['floorTemp'] = floor_temp

        air_temp = (dcb[dcb_offset + 32] * 256 + dcb[dcb_offset + 33]) / 10
        if air_temp == 0xFFFF:
            air_temp = None
        result['airTemp'] = air_temp
        result['heatingOn'] = dcb[dcb_offset+35]

        # This is where the DCB finishes for DT / DT-E model
        if model_id == 0 or model_id == 1:
            return result

        # PRT-HW has an extra byte in the DCB for hot water, so after this everything shifts by one byte.
        if model_id == 4:
            result['hotWaterOn'] = dcb[dcb_offset+36]
            # shift subsequent offsets:
            dcb_offset = dcb_offset + 1

        result['weekDayNumber'] = dcb[dcb_offset+36]
        result['timeHour'] = dcb[dcb_offset+37]
        result['timeMinute'] = dcb[dcb_offset+38]
        result['timeSecond'] = dcb[dcb_offset+39]

        return result

    def _form_frame(self, destination, start, end, payload):
        """Returns a valid frame including checksum based on start and end addresses and payload."""
        if payload is None:
            function = FUNCTION_READ  # read
            payload_len = 0
        else:
            function = FUNCTION_WRITE  # write
            payload_len = len(payload)
        frame_length = 10 + payload_len
        frame = bytearray(frame_length)
        frame[0] = destination
        frame[1] = frame_length
        frame[2] = MASTER_ADDRESS
        frame[3] = function
        frame[4] = start & 0xFF
        frame[5] = start >> 8
        frame[6] = end & 0xFF
        frame[7] = end >> 8
        if payload is not None:
            offset = 8
            for x in payload:
                frame[offset] = x
                offset = offset + 1
        return self.crc.addCCITTtoBytearray(frame)

    def _request_dcb(self, destination):
        """Requests a DCD from the device at address destination and returns the raw reply."""
        frame = self._form_frame(destination, 0, 0xFFFF, None)
        self.owner.comm_port.write(frame)
        reply = bytearray(self.owner.comm_port.read(MAX_REPLY_SIZE))

        if self.crc.verifyCCITTfromByteArray(reply):
            return reply
        else:
            return None

    def update_device_info(self, address):
        """Requests dcd from device at specified address and populates the deviceInfo dictionary"""
        reply = self._request_dcb(address)
        if reply is not None:
            self.deviceInfo = self._parseDCB(reply)
            if self.deviceInfo:
                return True

        return False

    def syncClock(self, address, currentRoomSetTemp, temperature_unit):
        """Updates device clock to current local time"""
        # when setting the clock, the thermostats revert to the frost temp if no schedules
        # are programmed, so we're going to re-set the temp after setting the clock.
        if not self._syncClock(address):
            self.owner.errorLog(u"syncClock: clock-sync did not work for address %d" % address)
            return False

        if not self.set_temp(address, currentRoomSetTemp, temperature_unit):
            self.owner.errorLog(u"syncClock: re-setting temperature post clock-sync did not work for address %d" % address)
            return False
        else:
            if self.owner.detailed_debug:
                self.owner.debugLog(u"syncClock: re-set temperature post clock-sync for address %d" % address)

        return True

    def _syncClock(self, address):
        dt = datetime.datetime.now()
        weekday = dt.isoweekday()
        second = dt.second + 2  # the +2 is to compensate for the time it takes to set the clock
        if second > 59:
            second = second - 59
        payload = [weekday, dt.hour, dt.minute, second]
        frame = self._form_frame(address, 43, len(payload), payload)
        self.owner.comm_port.write(frame)
        reply = bytearray(self.owner.comm_port.read(MAX_REPLY_SIZE)) # read up to 200 bytes

        if reply is None:
            self.owner.errorLog(u"syncClock: no reply from address %d" % address)
            return False

        if len(reply) != 7:
            self.owner.errorLog(u"syncClock: received reply with incorrect length of reply from address %d" % address)
            return False

        if not self.crc.verifyCCITTfromByteArray(reply):
            self.owner.errorLog(u"syncClock: received reply with incorrect CRC from address %d" % address)
            if self.owner.detailed_debug:
                self.owner.debugLog(u"syncClock: received OK reply from address %d" % address)
            return False
        return True

    def set_temp(self, address, temp, temperature_unit):
        """ sets the desired temperature for device with given address"""
        if address is None:
            self.owner.errorLog(u"setTemp: no address specified.")
            return False

        if temp is None:
            self.owner.errorLog(u"setTemp: no temperature specified.")
            return False

        if temperature_unit == TEMP_UNIT_FAHRENHEIT:
            minimum_set_temperature = self.fahrenheit(MIN_TEMP_C)
            maximum_set_temperature = self.fahrenheit(MAX_TEMP_C)
            temperature_unit_symbol = TEMP_UNIT_SYMBOL_FAHRENHEIT
        else:
            minimum_set_temperature = MIN_TEMP_C
            maximum_set_temperature = MAX_TEMP_C
            temperature_unit_symbol = TEMP_UNIT_SYMBOL_CELSIUS

        if temp < minimum_set_temperature:
            self.owner.errorLog(u"setTemp: specified temp (%d) is below minimum (%d deg %s)"
                                % (temp, minimum_set_temperature, temperature_unit_symbol))
            return False

        if temp > maximum_set_temperature:
            self.owner.errorLog(u"setTemp: specified temp (%d) is above maximum (%d deg %s)"
                                % (temp, maximum_set_temperature, temperature_unit_symbol))
            return False

        payload = [temp]
        frame = self._form_frame(address, 18, len(payload), payload)

        self.owner.comm_port.write(frame)
        reply = bytearray(self.owner.comm_port.read(MAX_REPLY_SIZE)) # read up to 200 bytes

        if self.crc.verifyCCITTfromByteArray(reply):
            if self.owner.detailed_debug:
                self.owner.debugLog(u"setTemp: received OK reply from address %d" % address)
            return True
        else:
            self.owner.errorLog(u"setTemp: received reply with incorrect CRC from address %d" % address)
            return False


    def set_hw_on_state(self, address, state):
        if address is None:
            self.owner.errorLog(u"set_hw_on_state: no address specified.")
            return False
        payload = [state]
        frame = self._form_frame(address, 42, len(payload), payload)
        self.owner.comm_port.write(frame)
        reply = bytearray(self.owner.comm_port.read(MAX_REPLY_SIZE))
        if self.crc.verifyCCITTfromByteArray(reply):
            self.owner.detailDebugLog(u"setTemp: received OK reply from address %d" % address)
            return True
        else:
            return False

