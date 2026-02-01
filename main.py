#!/usr/bin/env python3
"""Read comprehensive data from SIM card using PC/SC"""

import argparse
import sys
from datetime import datetime
from smartcard.System import readers
from smartcard.util import toHexString, toBytes


class OutputCapture:
    """Capture print output to both console and file"""
    def __init__(self, filename=None):
        self.terminal = sys.stdout
        self.filename = filename
        self.lines = []

    def write(self, message):
        self.terminal.write(message)
        self.lines.append(message)

    def flush(self):
        self.terminal.flush()

    def save(self):
        if self.filename:
            with open(self.filename, 'w') as f:
                f.writelines(self.lines)
            print(f"\nOutput saved to: {self.filename}")

class SIMReader:
    def __init__(self, reader_index=0):
        self.connection = None
        self.reader_index = reader_index
        self.is_usim = False
        self.usim_aid = None
        self.iccid = None

    def connect(self):
        """Connect to SIM card"""
        r = readers()
        print(f"Available readers: {len(r)}")
        for i, reader in enumerate(r):
            print(f"  [{i}] {reader}")

        if not r or self.reader_index >= len(r):
            raise Exception("Reader not found")

        reader = r[self.reader_index]
        print(f"\nUsing reader: {reader}")

        self.connection = reader.createConnection()
        self.connection.connect()
        print(f"ATR: {toHexString(self.connection.getATR())}")

    def send_apdu(self, apdu):
        """Send APDU command and return response"""
        data, sw1, sw2 = self.connection.transmit(apdu)
        return data, sw1, sw2

    def select_file_gsm(self, file_id, debug=False):
        """Select file using GSM commands (Class A0)"""
        apdu = [0xA0, 0xA4, 0x00, 0x00, 0x02, (file_id >> 8) & 0xFF, file_id & 0xFF]
        data, sw1, sw2 = self.send_apdu(apdu)

        if debug:
            print(f"    SELECT {file_id:04X}: SW={sw1:02X}{sw2:02X}")

        if sw1 == 0x9F:
            # Get response
            apdu = [0xA0, 0xC0, 0x00, 0x00, sw2]
            data, sw1, sw2 = self.send_apdu(apdu)
            if debug:
                print(f"    GET RESPONSE: SW={sw1:02X}{sw2:02X} len={len(data)}")
            return data, sw1, sw2

        return data, sw1, sw2

    def read_binary(self, length, offset=0):
        """Read binary data from selected file"""
        apdu = [0xA0, 0xB0, (offset >> 8) & 0xFF, offset & 0xFF, length]
        data, sw1, sw2 = self.send_apdu(apdu)

        if sw1 == 0x9F:
            apdu = [0xA0, 0xC0, 0x00, 0x00, sw2]
            data, sw1, sw2 = self.send_apdu(apdu)

        return data, sw1, sw2

    def read_record(self, record_num, length):
        """Read record from selected file"""
        apdu = [0xA0, 0xB2, record_num, 0x04, length]
        data, sw1, sw2 = self.send_apdu(apdu)
        return data, sw1, sw2

    def select_usim(self):
        """Try to select USIM ADF"""
        # First, read EF_DIR to find USIM AID
        self.select_file_gsm(0x3F00)

        # Select EF_DIR (2F00)
        apdu = [0x00, 0xA4, 0x00, 0x04, 0x02, 0x2F, 0x00]
        data, sw1, sw2 = self.send_apdu(apdu)

        if sw1 == 0x61:
            apdu = [0x00, 0xC0, 0x00, 0x00, sw2]
            data, sw1, sw2 = self.send_apdu(apdu)

        if sw1 != 0x90:
            # Try common USIM AID directly
            usim_aid = [0xA0, 0x00, 0x00, 0x00, 0x87, 0x10, 0x02, 0xFF, 0xFF, 0xFF, 0xFF, 0x89, 0x06, 0x01, 0x00, 0x00]
            apdu = [0x00, 0xA4, 0x04, 0x04, len(usim_aid)] + usim_aid
            data, sw1, sw2 = self.send_apdu(apdu)

            if sw1 == 0x61:
                apdu = [0x00, 0xC0, 0x00, 0x00, sw2]
                data, sw1, sw2 = self.send_apdu(apdu)

            if sw1 == 0x90:
                self.is_usim = True
                self.usim_aid = usim_aid
                return True
            return False

        # Read first record from EF_DIR
        apdu = [0x00, 0xB2, 0x01, 0x04, 0x20]
        data, sw1, sw2 = self.send_apdu(apdu)

        if sw1 == 0x90 and data:
            # Parse TLV to find AID
            # Look for tag 4F (AID)
            i = 0
            while i < len(data) - 2:
                if data[i] == 0x61:  # Application template
                    i += 1
                    template_len = data[i]
                    i += 1
                    end = i + template_len
                    while i < end and i < len(data) - 2:
                        tag = data[i]
                        i += 1
                        length = data[i]
                        i += 1
                        if tag == 0x4F:  # AID tag
                            aid = list(data[i:i+length])
                            self.usim_aid = aid
                            break
                        i += length
                    break
                i += 1

        # Select USIM ADF using discovered or default AID
        if not self.usim_aid:
            self.usim_aid = [0xA0, 0x00, 0x00, 0x00, 0x87, 0x10, 0x02, 0xFF, 0xFF, 0xFF, 0xFF, 0x89, 0x06, 0x01, 0x00, 0x00]

        apdu = [0x00, 0xA4, 0x04, 0x04, len(self.usim_aid)] + self.usim_aid
        data, sw1, sw2 = self.send_apdu(apdu)

        if sw1 == 0x61:
            apdu = [0x00, 0xC0, 0x00, 0x00, sw2]
            data, sw1, sw2 = self.send_apdu(apdu)

        if sw1 == 0x90:
            self.is_usim = True
            return True

        return False

    def select_file_usim(self, file_id, debug=False):
        """Select file using USIM commands (Class 00)"""
        apdu = [0x00, 0xA4, 0x00, 0x04, 0x02, (file_id >> 8) & 0xFF, file_id & 0xFF]
        data, sw1, sw2 = self.send_apdu(apdu)

        if debug:
            print(f"    SELECT {file_id:04X}: SW={sw1:02X}{sw2:02X}")

        if sw1 == 0x61:
            apdu = [0x00, 0xC0, 0x00, 0x00, sw2]
            data, sw1, sw2 = self.send_apdu(apdu)
            if debug:
                print(f"    GET RESPONSE: SW={sw1:02X}{sw2:02X} len={len(data)}")

        return data, sw1, sw2

    def read_binary_usim(self, length, offset=0):
        """Read binary data using USIM commands"""
        apdu = [0x00, 0xB0, (offset >> 8) & 0xFF, offset & 0xFF, length]
        data, sw1, sw2 = self.send_apdu(apdu)
        return data, sw1, sw2

    def read_record_usim(self, record_num, length):
        """Read record using USIM commands"""
        apdu = [0x00, 0xB2, record_num, 0x04, length]
        data, sw1, sw2 = self.send_apdu(apdu)
        return data, sw1, sw2

    def decode_imsi(self, data):
        """Decode IMSI from EF_IMSI binary data"""
        if len(data) < 9:
            return None
        length = data[0]
        imsi = ""
        for i in range(1, length + 1):
            if i < len(data):
                byte = data[i]
                if i == 1:
                    high = (byte >> 4) & 0x0F
                    if high != 0x0F:
                        imsi += str(high)
                else:
                    low = byte & 0x0F
                    high = (byte >> 4) & 0x0F
                    if low != 0x0F:
                        imsi += str(low)
                    if high != 0x0F:
                        imsi += str(high)
        return imsi

    def decode_iccid(self, data):
        """Decode ICCID from EF_ICCID"""
        iccid = ""
        for byte in data:
            low = byte & 0x0F
            high = (byte >> 4) & 0x0F
            if low != 0x0F:
                iccid += str(low)
            if high != 0x0F:
                iccid += str(high)
        return iccid

    def decode_spn(self, data):
        """Decode Service Provider Name"""
        if len(data) < 2:
            return None
        # First byte is display condition, rest is name
        display_condition = data[0]
        name_bytes = data[1:]
        # Remove padding (0xFF)
        name_bytes = [b for b in name_bytes if b != 0xFF]
        try:
            # Try GSM 7-bit first, fallback to ASCII
            name = bytes(name_bytes).decode('utf-8', errors='replace')
        except:
            name = bytes(name_bytes).decode('latin-1', errors='replace')
        return name.strip()

    def decode_msisdn(self, data):
        """Decode phone number from EF_MSISDN"""
        if len(data) < 14:
            return None

        # Alpha identifier length varies, phone number is in last 14 bytes
        # Structure: Alpha ID (variable) + BCD number length (1) + TON/NPI (1) + Number (10) + CCI (1) + EXT (1)
        alpha_len = len(data) - 14
        alpha = data[:alpha_len]

        bcd_len = data[alpha_len]
        if bcd_len == 0xFF or bcd_len == 0:
            return None

        ton_npi = data[alpha_len + 1]
        number_bytes = data[alpha_len + 2:alpha_len + 12]

        # Decode BCD number
        number = ""
        if ton_npi == 0x91:  # International
            number = "+"

        for byte in number_bytes:
            low = byte & 0x0F
            high = (byte >> 4) & 0x0F
            if low != 0x0F:
                number += str(low)
            if high != 0x0F:
                number += str(high)

        # Decode alpha tag
        alpha_tag = ""
        alpha_clean = [b for b in alpha if b != 0xFF]
        if alpha_clean:
            try:
                alpha_tag = bytes(alpha_clean).decode('utf-8', errors='replace').strip()
            except:
                pass

        return {"number": number, "alpha": alpha_tag} if number else None

    def decode_smsp(self, data):
        """Decode SMS Parameters (SMSC number)"""
        if len(data) < 28:
            return None

        # Alpha ID is variable, SMSC is at specific offset from end
        # Structure varies, but SMSC is typically near the end
        # Try to find the SMSC number (starts with length byte, then TON/NPI)
        alpha_len = len(data) - 28

        # Parameter indicators
        params = data[alpha_len] if alpha_len >= 0 else 0xFF

        # SMSC address starts after alpha and param indicator
        smsc_len_offset = alpha_len + 1
        if smsc_len_offset >= len(data):
            return None

        smsc_len = data[smsc_len_offset]
        if smsc_len == 0xFF or smsc_len == 0 or smsc_len > 12:
            return None

        ton_npi = data[smsc_len_offset + 1] if smsc_len_offset + 1 < len(data) else 0xFF
        number_start = smsc_len_offset + 2
        number_bytes = data[number_start:number_start + smsc_len - 1]

        smsc = ""
        if ton_npi == 0x91:
            smsc = "+"

        for byte in number_bytes:
            low = byte & 0x0F
            high = (byte >> 4) & 0x0F
            if low != 0x0F:
                smsc += str(low)
            if high != 0x0F:
                smsc += str(high)

        return smsc if smsc else None

    def decode_plmn(self, data):
        """Decode PLMN list (MCC + MNC pairs)"""
        plmns = []
        for i in range(0, len(data), 3):
            if i + 2 >= len(data):
                break
            b1, b2, b3 = data[i], data[i+1], data[i+2]
            if b1 == 0xFF and b2 == 0xFF and b3 == 0xFF:
                continue

            # MCC is in b1 and low nibble of b2
            mcc = f"{b1 & 0x0F}{(b1 >> 4) & 0x0F}{b2 & 0x0F}"
            # MNC is in b3 and high nibble of b2
            mnc_d1 = b3 & 0x0F
            mnc_d2 = (b3 >> 4) & 0x0F
            mnc_d3 = (b2 >> 4) & 0x0F

            if mnc_d3 == 0x0F:
                mnc = f"{mnc_d1}{mnc_d2}"
            else:
                mnc = f"{mnc_d1}{mnc_d2}{mnc_d3}"

            if mcc != "FFF":
                plmns.append(f"{mcc}-{mnc}")

        return plmns

    def decode_loci(self, data):
        """Decode Location Information"""
        if len(data) < 11:
            return None

        # TMSI (4 bytes) + LAI (5 bytes) + TMSI TIME (1 byte) + Location update status (1 byte)
        tmsi = toHexString(data[0:4]).replace(" ", "")
        lai = data[4:9]

        # LAI = MCC (3 digits) + MNC (2-3 digits) + LAC (2 bytes)
        mcc = f"{lai[0] & 0x0F}{(lai[0] >> 4) & 0x0F}{lai[1] & 0x0F}"
        mnc_d3 = (lai[1] >> 4) & 0x0F
        mnc_d1 = lai[2] & 0x0F
        mnc_d2 = (lai[2] >> 4) & 0x0F

        if mnc_d3 == 0x0F:
            mnc = f"{mnc_d1}{mnc_d2}"
        else:
            mnc = f"{mnc_d1}{mnc_d2}{mnc_d3}"

        lac = (lai[3] << 8) | lai[4]
        update_status = data[10] if len(data) > 10 else 0

        status_map = {0: "Updated", 1: "Not updated", 2: "PLMN not allowed", 3: "Location area not allowed"}

        return {
            "tmsi": tmsi,
            "mcc": mcc,
            "mnc": mnc,
            "lac": f"0x{lac:04X} ({lac})",
            "update_status": status_map.get(update_status & 0x07, f"Unknown ({update_status})")
        }

    def decode_acc(self, data):
        """Decode Access Control Class"""
        if len(data) < 2:
            return None
        acc = (data[0] << 8) | data[1]
        classes = []
        for i in range(16):
            if acc & (1 << i):
                if i < 10:
                    classes.append(f"Class {i}")
                elif i == 10:
                    classes.append("Emergency")
                elif i == 11:
                    classes.append("PLMN operator 11")
                elif i == 12:
                    classes.append("Security services 12")
                elif i == 13:
                    classes.append("Public utilities 13")
                elif i == 14:
                    classes.append("Emergency services 14")
                elif i == 15:
                    classes.append("PLMN operator 15")
        return {"value": f"0x{acc:04X}", "classes": classes}

    def decode_ad(self, data):
        """Decode Administrative Data"""
        if len(data) < 3:
            return None

        ms_operation = data[0]
        op_map = {
            0x00: "Normal operation",
            0x80: "Type approval",
            0x01: "Normal + specific facilities",
            0x02: "Normal + type approval",
            0x04: "Cell test operation"
        }

        result = {
            "ms_operation": op_map.get(ms_operation, f"Unknown (0x{ms_operation:02X})"),
            "ofm": "OFM supported" if (data[2] & 0x01) else "OFM not supported"
        }

        if len(data) >= 4:
            mnc_len = data[3] & 0x0F
            result["mnc_length"] = mnc_len

        return result

    def decode_alpha_id(self, data):
        """Decode alpha identifier (contact name)"""
        # Remove trailing 0xFF padding
        clean = []
        for b in data:
            if b == 0xFF:
                break
            clean.append(b)

        if not clean:
            return None

        # Check for UCS2 encoding
        if clean[0] == 0x80:
            # UCS2 encoding
            try:
                return bytes(clean[1:]).decode('utf-16-be', errors='replace').strip()
            except:
                pass
        elif clean[0] == 0x81 and len(clean) > 3:
            # UCS2 with base pointer
            try:
                num_chars = clean[1]
                base = clean[2] << 7
                result = ""
                for i in range(3, min(3 + num_chars, len(clean))):
                    if clean[i] < 0x80:
                        result += chr(clean[i])
                    else:
                        result += chr(base + (clean[i] & 0x7F))
                return result.strip()
            except:
                pass

        # GSM 7-bit default alphabet or ASCII
        try:
            return bytes(clean).decode('utf-8', errors='replace').strip()
        except:
            return bytes(clean).decode('latin-1', errors='replace').strip()

    def decode_bcd_number(self, data, include_ton=True):
        """Decode BCD encoded phone number"""
        if not data or len(data) < 2:
            return None

        bcd_len = data[0]
        if bcd_len == 0xFF or bcd_len == 0:
            return None

        ton_npi = data[1]
        number_bytes = data[2:2 + bcd_len - 1]

        number = ""
        if include_ton and ton_npi == 0x91:  # International
            number = "+"

        for byte in number_bytes:
            low = byte & 0x0F
            high = (byte >> 4) & 0x0F

            # Handle special digits
            digit_map = {0x0A: '*', 0x0B: '#', 0x0C: 'p', 0x0D: 'w', 0x0E: '+'}

            if low != 0x0F:
                number += digit_map.get(low, str(low))
            if high != 0x0F:
                number += digit_map.get(high, str(high))

        return number if number else None

    def decode_sms(self, data):
        """Decode SMS from EF_SMS record"""
        if not data or len(data) < 1:
            return None

        status = data[0]
        status_map = {
            0x00: "Free",
            0x01: "Received unread",
            0x03: "Received read",
            0x05: "Sent unsent",
            0x07: "Sent"
        }

        if status == 0x00 or status == 0xFF:
            return None  # Empty slot

        # SMSC address length
        smsc_len = data[1]
        smsc_offset = 2

        if smsc_len > 0 and smsc_len != 0xFF:
            smsc_data = data[1:2 + smsc_len]
            smsc = self.decode_bcd_number([smsc_len] + list(data[2:2+smsc_len]))
            pdu_start = 2 + smsc_len
        else:
            smsc = None
            pdu_start = 2

        if pdu_start >= len(data):
            return {"status": status_map.get(status, f"Unknown ({status})")}

        # PDU parsing
        pdu = data[pdu_start:]

        if len(pdu) < 2:
            return {"status": status_map.get(status, f"Unknown ({status})")}

        # First octet
        first_octet = pdu[0]
        mti = first_octet & 0x03  # Message type indicator

        result = {
            "status": status_map.get(status, f"Unknown ({status})"),
            "smsc": smsc
        }

        if mti == 0x00:  # SMS-DELIVER (received)
            # Sender address
            if len(pdu) < 3:
                return result

            sender_len = pdu[1]  # Number of digits
            sender_type = pdu[2] if len(pdu) > 2 else 0x81

            sender_bytes_len = (sender_len + 1) // 2
            sender_data = [sender_bytes_len + 1, sender_type] + list(pdu[3:3 + sender_bytes_len])
            sender = self.decode_bcd_number(sender_data)
            result["sender"] = sender

            # Protocol ID, DCS, SCTS, UDL, UD
            offset = 3 + sender_bytes_len
            if offset + 7 < len(pdu):
                pid = pdu[offset]
                dcs = pdu[offset + 1]

                # Service Centre Time Stamp (7 bytes)
                scts = pdu[offset + 2:offset + 9]
                if len(scts) == 7:
                    year = ((scts[0] >> 4) * 10) + (scts[0] & 0x0F)
                    month = ((scts[1] >> 4) * 10) + (scts[1] & 0x0F)
                    day = ((scts[2] >> 4) * 10) + (scts[2] & 0x0F)
                    hour = ((scts[3] >> 4) * 10) + (scts[3] & 0x0F)
                    minute = ((scts[4] >> 4) * 10) + (scts[4] & 0x0F)
                    second = ((scts[5] >> 4) * 10) + (scts[5] & 0x0F)
                    result["timestamp"] = f"20{year:02d}-{month:02d}-{day:02d} {hour:02d}:{minute:02d}:{second:02d}"

                # User data
                ud_offset = offset + 9
                if ud_offset < len(pdu):
                    udl = pdu[ud_offset]
                    ud = pdu[ud_offset + 1:]

                    # Decode based on DCS
                    if (dcs & 0x0C) == 0x08:  # UCS2
                        try:
                            result["message"] = bytes(ud[:udl]).decode('utf-16-be', errors='replace')
                        except:
                            result["message"] = f"[UCS2: {toHexString(ud[:udl])}]"
                    elif (dcs & 0x0C) == 0x00:  # GSM 7-bit
                        result["message"] = self.decode_gsm7(ud, udl)
                    else:
                        result["message"] = f"[Data: {toHexString(ud[:udl])}]"

        elif mti == 0x01:  # SMS-SUBMIT (sent)
            # Message reference
            if len(pdu) < 3:
                return result

            mr = pdu[1]
            dest_len = pdu[2]
            dest_type = pdu[3] if len(pdu) > 3 else 0x81

            dest_bytes_len = (dest_len + 1) // 2
            dest_data = [dest_bytes_len + 1, dest_type] + list(pdu[4:4 + dest_bytes_len])
            dest = self.decode_bcd_number(dest_data)
            result["recipient"] = dest

            # PID, DCS, VP (if present), UDL, UD
            offset = 4 + dest_bytes_len
            if offset + 2 < len(pdu):
                pid = pdu[offset]
                dcs = pdu[offset + 1]

                # Check for validity period
                vpf = (first_octet >> 3) & 0x03
                if vpf == 0x02:  # Relative
                    offset += 1
                elif vpf == 0x03:  # Absolute
                    offset += 7

                ud_offset = offset + 2
                if ud_offset < len(pdu):
                    udl = pdu[ud_offset]
                    ud = pdu[ud_offset + 1:]

                    if (dcs & 0x0C) == 0x08:  # UCS2
                        try:
                            result["message"] = bytes(ud[:udl]).decode('utf-16-be', errors='replace')
                        except:
                            result["message"] = f"[UCS2: {toHexString(ud[:udl])}]"
                    elif (dcs & 0x0C) == 0x00:  # GSM 7-bit
                        result["message"] = self.decode_gsm7(ud, udl)
                    else:
                        result["message"] = f"[Data: {toHexString(ud[:udl])}]"

        return result

    def decode_gsm7(self, data, num_chars):
        """Decode GSM 7-bit packed data"""
        gsm7_basic = (
            "@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞ ÆæßÉ !\"#¤%&'()*+,-./0123456789:;<=>?"
            "¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§¿abcdefghijklmnopqrstuvwxyzäöñüà"
        )

        result = ""
        bits = 0
        byte_pos = 0
        bit_pos = 0

        for i in range(num_chars):
            # Extract 7 bits
            if byte_pos >= len(data):
                break

            char_val = (data[byte_pos] >> bit_pos) & 0x7F

            if bit_pos > 1 and byte_pos + 1 < len(data):
                char_val |= (data[byte_pos + 1] << (8 - bit_pos)) & 0x7F

            bit_pos += 7
            if bit_pos >= 8:
                bit_pos -= 8
                byte_pos += 1

            if char_val < len(gsm7_basic):
                result += gsm7_basic[char_val]
            else:
                result += '?'

        return result

    def read_all(self):
        """Read all accessible SIM data"""
        print("\n" + "="*60)
        print("SIM CARD DATA DUMP")
        print("="*60)

        # Select MF (3F00)
        self.select_file_gsm(0x3F00)

        # ===== ICCID (EF_ICCID - 2FE2) =====
        print("\n--- ICCID (SIM Serial Number) ---")
        self.select_file_gsm(0x3F00)
        data, sw1, sw2 = self.select_file_gsm(0x2FE2)
        if sw1 in [0x90, 0x9F, 0x91]:
            data, sw1, sw2 = self.read_binary(10)
            if sw1 == 0x90:
                self.iccid = self.decode_iccid(data)
                print(f"ICCID: {self.iccid}")
                print(f"Raw: {toHexString(data)}")

        # Select DF GSM (7F20)
        self.select_file_gsm(0x3F00)
        self.select_file_gsm(0x7F20)

        # ===== IMSI (EF_IMSI - 6F07) =====
        print("\n--- IMSI ---")
        data, sw1, sw2 = self.select_file_gsm(0x6F07)
        if sw1 in [0x90, 0x9F, 0x91]:
            data, sw1, sw2 = self.read_binary(9)
            if sw1 == 0x90:
                imsi = self.decode_imsi(data)
                print(f"IMSI: {imsi}")
                if imsi:
                    print(f"  MCC: {imsi[:3]}")
                    print(f"  MNC: {imsi[3:5] if len(imsi) > 4 else 'N/A'}")
                    print(f"  MSIN: {imsi[5:] if len(imsi) > 5 else 'N/A'}")
                print(f"Raw: {toHexString(data)}")

        # ===== SPN (EF_SPN - 6F46) =====
        print("\n--- Service Provider Name ---")
        self.select_file_gsm(0x3F00)
        self.select_file_gsm(0x7F20)
        data, sw1, sw2 = self.select_file_gsm(0x6F46)
        if sw1 in [0x90, 0x9F, 0x91]:
            data, sw1, sw2 = self.read_binary(17)
            if sw1 == 0x90:
                spn = self.decode_spn(data)
                print(f"SPN: {spn}")
                print(f"Raw: {toHexString(data)}")
        else:
            print("Not available")

        # ===== MSISDN - Phone Number (EF_MSISDN - 6F40) =====
        print("\n--- Phone Number (MSISDN) ---")
        self.select_file_gsm(0x3F00)
        self.select_file_gsm(0x7F20)
        data, sw1, sw2 = self.select_file_gsm(0x6F40)
        if sw1 in [0x90, 0x9F, 0x91]:
            # Get file info to determine record length
            record_len = data[14] if len(data) > 14 else 34
            data, sw1, sw2 = self.read_record(1, record_len)
            if sw1 == 0x90:
                msisdn = self.decode_msisdn(data)
                if msisdn:
                    print(f"Phone Number: {msisdn['number']}")
                    if msisdn['alpha']:
                        print(f"Alpha Tag: {msisdn['alpha']}")
                else:
                    print("No number stored")
                print(f"Raw: {toHexString(data)}")
        else:
            print("Not available")

        # ===== SMSP - SMS Parameters (EF_SMSP - 6F42) =====
        print("\n--- SMS Service Center ---")
        self.select_file_gsm(0x3F00)
        self.select_file_gsm(0x7F20)
        data, sw1, sw2 = self.select_file_gsm(0x6F42)
        if sw1 in [0x90, 0x9F, 0x91]:
            record_len = data[14] if len(data) > 14 else 40
            data, sw1, sw2 = self.read_record(1, record_len)
            if sw1 == 0x90:
                smsc = self.decode_smsp(data)
                print(f"SMSC: {smsc if smsc else 'Not set'}")
                print(f"Raw: {toHexString(data)}")
        else:
            print("Not available")

        # ===== PLMNsel - PLMN Selector (EF_PLMNsel - 6F30) =====
        print("\n--- Preferred PLMNs ---")
        self.select_file_gsm(0x3F00)
        self.select_file_gsm(0x7F20)
        data, sw1, sw2 = self.select_file_gsm(0x6F30)
        if sw1 in [0x90, 0x9F, 0x91]:
            data, sw1, sw2 = self.read_binary(30)  # Read first 10 PLMNs
            if sw1 == 0x90:
                plmns = self.decode_plmn(data)
                if plmns:
                    for plmn in plmns:
                        print(f"  {plmn}")
                else:
                    print("  None")
        else:
            print("Not available")

        # ===== FPLMN - Forbidden PLMNs (EF_FPLMN - 6F7B) =====
        print("\n--- Forbidden PLMNs ---")
        self.select_file_gsm(0x3F00)
        self.select_file_gsm(0x7F20)
        data, sw1, sw2 = self.select_file_gsm(0x6F7B)
        if sw1 in [0x90, 0x9F, 0x91]:
            data, sw1, sw2 = self.read_binary(12)  # 4 forbidden PLMNs
            if sw1 == 0x90:
                plmns = self.decode_plmn(data)
                if plmns:
                    for plmn in plmns:
                        print(f"  {plmn}")
                else:
                    print("  None")
                print(f"Raw: {toHexString(data)}")
        else:
            print("Not available")

        # ===== LOCI - Location Information (EF_LOCI - 6F7E) =====
        print("\n--- Location Information ---")
        self.select_file_gsm(0x3F00)
        self.select_file_gsm(0x7F20)
        data, sw1, sw2 = self.select_file_gsm(0x6F7E)
        if sw1 in [0x90, 0x9F, 0x91]:
            data, sw1, sw2 = self.read_binary(11)
            if sw1 == 0x90:
                loci = self.decode_loci(data)
                if loci:
                    print(f"  TMSI: {loci['tmsi']}")
                    print(f"  MCC: {loci['mcc']}")
                    print(f"  MNC: {loci['mnc']}")
                    print(f"  LAC: {loci['lac']}")
                    print(f"  Status: {loci['update_status']}")
                print(f"Raw: {toHexString(data)}")
        else:
            print("Not available")

        # ===== ACC - Access Control Class (EF_ACC - 6F78) =====
        print("\n--- Access Control Class ---")
        self.select_file_gsm(0x3F00)
        self.select_file_gsm(0x7F20)
        data, sw1, sw2 = self.select_file_gsm(0x6F78)
        if sw1 in [0x90, 0x9F, 0x91]:
            data, sw1, sw2 = self.read_binary(2)
            if sw1 == 0x90:
                acc = self.decode_acc(data)
                if acc:
                    print(f"  Value: {acc['value']}")
                    print(f"  Classes: {', '.join(acc['classes']) if acc['classes'] else 'None'}")
                print(f"Raw: {toHexString(data)}")
        else:
            print("Not available")

        # ===== AD - Administrative Data (EF_AD - 6FAD) =====
        print("\n--- Administrative Data ---")
        self.select_file_gsm(0x3F00)
        self.select_file_gsm(0x7F20)
        data, sw1, sw2 = self.select_file_gsm(0x6FAD)
        if sw1 in [0x90, 0x9F, 0x91]:
            data, sw1, sw2 = self.read_binary(4)
            if sw1 == 0x90:
                ad = self.decode_ad(data)
                if ad:
                    print(f"  Operation Mode: {ad['ms_operation']}")
                    print(f"  OFM: {ad['ofm']}")
                    if 'mnc_length' in ad:
                        print(f"  MNC Length: {ad['mnc_length']} digits")
                print(f"Raw: {toHexString(data)}")
        else:
            print("Not available")

        # ===== HPLMN Search Period (EF_HPLMN - 6F31) =====
        print("\n--- HPLMN Search Period ---")
        self.select_file_gsm(0x3F00)
        self.select_file_gsm(0x7F20)
        data, sw1, sw2 = self.select_file_gsm(0x6F31)
        if sw1 in [0x90, 0x9F, 0x91]:
            data, sw1, sw2 = self.read_binary(1)
            if sw1 == 0x90 and data:
                interval = data[0]
                if interval == 0:
                    print(f"  Interval: Use default (60 min)")
                else:
                    print(f"  Interval: {interval * 6} minutes")
                print(f"Raw: {toHexString(data)}")
        else:
            print("Not available")

        # ===== Phase (EF_Phase - 6FAE) =====
        print("\n--- SIM Phase ---")
        self.select_file_gsm(0x3F00)
        self.select_file_gsm(0x7F20)
        data, sw1, sw2 = self.select_file_gsm(0x6FAE)
        if sw1 in [0x90, 0x9F, 0x91]:
            data, sw1, sw2 = self.read_binary(1)
            if sw1 == 0x90 and data:
                phase_map = {0: "Phase 1", 2: "Phase 2", 3: "Phase 2+"}
                print(f"  Phase: {phase_map.get(data[0], f'Unknown ({data[0]})')}")
        else:
            print("Not available")

        # ===== ADN - Contacts (EF_ADN - 6F3A) =====
        print("\n--- Contacts (ADN) ---")
        contacts_found = 0

        # Try GSM first
        self.select_file_gsm(0x3F00)
        self.select_file_gsm(0x7F20)
        data, sw1, sw2 = self.select_file_gsm(0x6F3A)

        use_usim = False
        if sw1 not in [0x90, 0x9F, 0x91]:
            # Try USIM
            print("  (Trying USIM ADF...)")
            if self.select_usim():
                data, sw1, sw2 = self.select_file_usim(0x6F3A)
                use_usim = True

        if sw1 in [0x90, 0x9F, 0x91, 0x61]:
            # Parse FCP template for USIM or use GSM response
            record_len = 34  # default
            num_records = 250

            if use_usim and data:
                # Parse FCP template (tag 62)
                i = 0
                while i < len(data) - 2:
                    if data[i] == 0x82:  # File descriptor
                        i += 1
                        fd_len = data[i]
                        i += 1
                        if fd_len >= 3:
                            record_len = (data[i+1] << 8) | data[i+2]
                        if fd_len >= 5:
                            num_records = data[i+3]
                        break
                    elif data[i] in [0x62, 0x80, 0x81, 0x83, 0x84, 0x8A, 0x8B, 0x8C, 0xA5, 0xAB, 0xC6]:
                        i += 1
                        i += data[i] + 1
                    else:
                        i += 1
            elif data and len(data) > 14:
                record_len = data[14]
                num_records = ((data[2] << 8) | data[3]) // record_len if record_len > 0 else 10

            print(f"  Record length: {record_len}, Max records: {num_records}")

            for rec in range(1, min(num_records + 1, 251)):
                if use_usim:
                    data, sw1, sw2 = self.read_record_usim(rec, record_len)
                else:
                    data, sw1, sw2 = self.read_record(rec, record_len)

                if sw1 == 0x90 and data:
                    if all(b == 0xFF for b in data):
                        continue

                    alpha_len = record_len - 14
                    alpha = self.decode_alpha_id(data[:alpha_len])
                    number_data = data[alpha_len:]
                    number = self.decode_bcd_number(number_data)

                    if alpha or number:
                        contacts_found += 1
                        print(f"  [{rec}] {alpha or 'No name'}: {number or 'No number'}")

                elif sw1 == 0x6A and sw2 == 0x83:
                    # Record not found - end of file
                    break

        if contacts_found == 0:
            print("  No contacts stored")

        # ===== FDN - Fixed Dialing Numbers (EF_FDN - 6F3B) =====
        print("\n--- Fixed Dialing Numbers (FDN) ---")
        self.select_file_gsm(0x3F00)
        self.select_file_gsm(0x7F20)
        data, sw1, sw2 = self.select_file_gsm(0x6F3B)

        use_usim_fdn = False
        if sw1 not in [0x90, 0x9F, 0x91]:
            if self.select_usim():
                data, sw1, sw2 = self.select_file_usim(0x6F3B)
                use_usim_fdn = True

        if sw1 in [0x90, 0x9F, 0x91, 0x61]:
            record_len = data[14] if len(data) > 14 else 34
            num_records = ((data[2] << 8) | data[3]) // record_len if len(data) > 3 and record_len > 0 else 10

            fdn_found = 0
            for rec in range(1, min(num_records + 1, 51)):
                if use_usim_fdn:
                    data, sw1, sw2 = self.read_record_usim(rec, record_len)
                else:
                    data, sw1, sw2 = self.read_record(rec, record_len)
                if sw1 == 0x90 and data:
                    if all(b == 0xFF for b in data):
                        continue

                    alpha_len = record_len - 14
                    alpha = self.decode_alpha_id(data[:alpha_len])
                    number = self.decode_bcd_number(data[alpha_len:])

                    if alpha or number:
                        fdn_found += 1
                        print(f"  [{rec}] {alpha or 'No name'}: {number or 'No number'}")
                elif sw1 == 0x6A and sw2 == 0x83:
                    break

            if fdn_found == 0:
                print("  No FDN entries")
        else:
            print("Not available or PIN2 protected")

        # ===== SDN - Service Dialing Numbers (EF_SDN - 6F49) =====
        print("\n--- Service Dialing Numbers (SDN) ---")
        self.select_file_gsm(0x3F00)
        self.select_file_gsm(0x7F20)
        data, sw1, sw2 = self.select_file_gsm(0x6F49)

        use_usim_sdn = False
        if sw1 not in [0x90, 0x9F, 0x91]:
            if self.select_usim():
                data, sw1, sw2 = self.select_file_usim(0x6F49)
                use_usim_sdn = True

        if sw1 in [0x90, 0x9F, 0x91, 0x61]:
            record_len = data[14] if len(data) > 14 else 34
            num_records = ((data[2] << 8) | data[3]) // record_len if len(data) > 3 and record_len > 0 else 10

            sdn_found = 0
            for rec in range(1, min(num_records + 1, 51)):
                if use_usim_sdn:
                    data, sw1, sw2 = self.read_record_usim(rec, record_len)
                else:
                    data, sw1, sw2 = self.read_record(rec, record_len)
                if sw1 == 0x90 and data:
                    if all(b == 0xFF for b in data):
                        continue

                    alpha_len = record_len - 14
                    alpha = self.decode_alpha_id(data[:alpha_len])
                    number = self.decode_bcd_number(data[alpha_len:])

                    if alpha or number:
                        sdn_found += 1
                        print(f"  [{rec}] {alpha or 'No name'}: {number or 'No number'}")
                elif sw1 == 0x6A and sw2 == 0x83:
                    break

            if sdn_found == 0:
                print("  No service numbers")
        else:
            print("Not available")

        # ===== LND - Last Numbers Dialed (EF_LND - 6F44) =====
        print("\n--- Last Numbers Dialed ---")
        self.select_file_gsm(0x3F00)
        self.select_file_gsm(0x7F20)
        data, sw1, sw2 = self.select_file_gsm(0x6F44)

        use_usim_lnd = False
        if sw1 not in [0x90, 0x9F, 0x91]:
            if self.select_usim():
                data, sw1, sw2 = self.select_file_usim(0x6F44)
                use_usim_lnd = True

        if sw1 in [0x90, 0x9F, 0x91, 0x61]:
            record_len = data[14] if len(data) > 14 else 34
            num_records = ((data[2] << 8) | data[3]) // record_len if len(data) > 3 and record_len > 0 else 5

            lnd_found = 0
            for rec in range(1, min(num_records + 1, 21)):
                if use_usim_lnd:
                    data, sw1, sw2 = self.read_record_usim(rec, record_len)
                else:
                    data, sw1, sw2 = self.read_record(rec, record_len)
                if sw1 == 0x90 and data:
                    if all(b == 0xFF for b in data):
                        continue

                    alpha_len = record_len - 14
                    alpha = self.decode_alpha_id(data[:alpha_len])
                    number = self.decode_bcd_number(data[alpha_len:])

                    if number:
                        lnd_found += 1
                        print(f"  [{rec}] {alpha or 'Unknown'}: {number}")
                elif sw1 == 0x6A and sw2 == 0x83:
                    break

            if lnd_found == 0:
                print("  No recent calls")
        else:
            print("Not available")

        # ===== SMS - Short Messages (EF_SMS - 6F3C) =====
        print("\n--- SMS Messages ---")
        sms_found = 0

        # Try GSM first
        self.select_file_gsm(0x3F00)
        self.select_file_gsm(0x7F20)
        data, sw1, sw2 = self.select_file_gsm(0x6F3C)

        use_usim_sms = False
        if sw1 not in [0x90, 0x9F, 0x91]:
            # Try USIM
            print("  (Trying USIM ADF...)")
            if self.select_usim():
                data, sw1, sw2 = self.select_file_usim(0x6F3C)
                use_usim_sms = True

        if sw1 in [0x90, 0x9F, 0x91, 0x61]:
            record_len = 176  # SMS records are always 176 bytes
            num_records = 50  # default

            if data and len(data) > 3:
                file_size = (data[2] << 8) | data[3]
                num_records = file_size // record_len

            print(f"  Max SMS slots: {num_records}")

            for rec in range(1, min(num_records + 1, 51)):
                if use_usim_sms:
                    data, sw1, sw2 = self.read_record_usim(rec, record_len)
                else:
                    data, sw1, sw2 = self.read_record(rec, record_len)

                if sw1 == 0x90 and data:
                    sms = self.decode_sms(data)
                    if sms:
                        sms_found += 1
                        print(f"\n  Message {rec}:")
                        print(f"    Status: {sms.get('status', 'Unknown')}")
                        if sms.get('sender'):
                            print(f"    From: {sms['sender']}")
                        if sms.get('recipient'):
                            print(f"    To: {sms['recipient']}")
                        if sms.get('timestamp'):
                            print(f"    Date: {sms['timestamp']}")
                        if sms.get('smsc'):
                            print(f"    SMSC: {sms['smsc']}")
                        if sms.get('message'):
                            print(f"    Text: {sms['message']}")

                elif sw1 == 0x6A and sw2 == 0x83:
                    break

        if sms_found == 0:
            print("  No SMS messages stored")

        print("\n" + "="*60)
        print("DUMP COMPLETE")
        print("="*60)


def show_help():
    """Display help message"""
    help_text = """
SIM Card Reader - Read data from SIM/USIM cards

USAGE:
    python main.py [OPTIONS]

OPTIONS:
    -s, --save          Save output to file (uses ICCID as filename)
    -o, --output FILE   Save output to custom filename
    -r, --reader NUM    Select reader by index (default: 0)
    -l, --list          List available readers and exit
    -h, --help          Show this help message

EXAMPLES:
    python main.py                     Read SIM and display output
    python main.py --save              Save output to ICCID_timestamp.txt
    python main.py -o dump.txt         Save output to dump.txt
    python main.py --reader 1          Use second reader
    python main.py --list              Show available readers

TROUBLESHOOTING:
    - No readers found: sudo systemctl start pcscd
    - Card not detected: Remove and reinsert SIM card
    - Permission denied: sudo usermod -aG pcscd $USER
"""
    print(help_text)


def list_readers():
    """List available smart card readers"""
    try:
        r = readers()
        if not r:
            print("No smart card readers found.")
            print("\nTroubleshooting:")
            print("  1. Check reader is connected: lsusb | grep -i smart")
            print("  2. Start PC/SC daemon: sudo systemctl start pcscd")
            print("  3. Install drivers: sudo apt install pcscd pcsc-tools")
            return False

        print(f"Available readers ({len(r)}):\n")
        for i, reader in enumerate(r):
            print(f"  [{i}] {reader}")
        print("\nUse --reader NUM to select a specific reader")
        return True
    except Exception as e:
        print(f"Error listing readers: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description='Read data from SIM/USIM cards',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py                Read SIM and display output
  python main.py --save         Save to ICCID_timestamp.txt
  python main.py -o dump.txt    Save to custom file
  python main.py --list         Show available readers
        """
    )
    parser.add_argument('-s', '--save', action='store_true',
                        help='Save output to file (uses ICCID as filename)')
    parser.add_argument('-o', '--output', type=str, metavar='FILE',
                        help='Save output to custom filename')
    parser.add_argument('-r', '--reader', type=int, default=0, metavar='NUM',
                        help='Select reader by index (default: 0)')
    parser.add_argument('-l', '--list', action='store_true',
                        help='List available readers and exit')

    # Handle no arguments or invalid arguments gracefully
    try:
        args = parser.parse_args()
    except SystemExit as e:
        if e.code != 0:
            print("\nUse --help for usage information")
        raise

    # List readers and exit
    if args.list:
        list_readers()
        return

    output_capture = None

    sim = SIMReader(reader_index=args.reader)
    try:
        sim.connect()

        # If saving, set up output capture after connection
        if args.save or args.output:
            # We'll determine filename after reading ICCID
            output_capture = OutputCapture(filename=None)
            sys.stdout = output_capture

        sim.read_all()

        # Save output if requested
        if output_capture:
            sys.stdout = output_capture.terminal  # Restore stdout

            if args.output:
                filename = args.output
            elif sim.iccid:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"{sim.iccid}_{timestamp}.txt"
            else:
                filename = f"sim_dump_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"

            output_capture.filename = filename
            output_capture.save()

    except Exception as e:
        if output_capture:
            sys.stdout = output_capture.terminal

        error_msg = str(e).lower()

        print(f"\nError: {e}\n")

        # Provide helpful troubleshooting based on error type
        if "no smart card inserted" in error_msg or "card absent" in error_msg:
            print("Troubleshooting:")
            print("  1. Check the SIM card is properly inserted in the reader")
            print("  2. Try removing and reinserting the SIM card")
            print("  3. Ensure the SIM adapter (if used) makes good contact")
            print("  4. Try: sudo systemctl restart pcscd")

        elif "no reader" in error_msg or "reader not found" in error_msg:
            print("Troubleshooting:")
            print("  1. Check the reader is connected: lsusb")
            print("  2. Start PC/SC daemon: sudo systemctl start pcscd")
            print("  3. List readers: python read_sim.py --list")

        elif "permission" in error_msg or "access" in error_msg:
            print("Troubleshooting:")
            print("  1. Add user to pcscd group: sudo usermod -aG pcscd $USER")
            print("  2. Log out and back in")
            print("  3. Or run with sudo: sudo python read_sim.py")

        elif "connection" in error_msg:
            print("Troubleshooting:")
            print("  1. Restart PC/SC daemon: sudo systemctl restart pcscd")
            print("  2. Check no other application is using the reader")
            print("  3. Try unplugging and replugging the reader")

        else:
            print("Use --help for usage information")
            print("Use --list to check available readers")


if __name__ == "__main__":
    main()
