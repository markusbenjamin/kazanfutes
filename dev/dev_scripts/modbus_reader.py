#!/usr/bin/env python3
"""
Modbus Heat Meter Reader
Reads all accessible values from heat meters 1-4 via Modbus TCP
"""
import struct
from typing import Dict, Any, Optional
from pymodbus.client import ModbusTcpClient


class ModbusMeterReader:
    """Reader for Modbus heat meters with comprehensive register mapping"""
   
    # Register offsets for each meter (Meter 1 starts at 0, Meter 2 at 55, etc.)
    METER_OFFSETS = {
        1: 0,    # Registers 4x00001 - 4x00055
        2: 55,   # Registers 4x00056 - 4x00110
        3: 110,  # Registers 4x00111 - 4x00165
        4: 165,  # Registers 4x00166 - 4x00220
    }
   
    # Register definitions (offset from meter base, count, type, description, unit, scaling)
    REGISTERS = [
        (0, 2, 'uint32', 'fabrication_number', '', 1),
        (2, 2, 'float32', 'energy_kwh', 'kWh', 1),
        (4, 2, 'float32', 'volume_m3', 'm³', 1),
        (6, 2, 'float32', 'power_w', 'W', 1),
        (8, 2, 'float32', 'max_power_w', 'W', 1),
        (10, 2, 'float32', 'volume_flow_m3h', 'm³/h', 1),
        (12, 2, 'float32', 'max_volume_flow_m3h', 'm³/h', 1),
        (14, 2, 'float32', 'flow_temperature_c', '°C', 1),
        (16, 2, 'float32', 'return_temperature_c', '°C', 1),
        (18, 2, 'float32', 'temperature_difference_k', 'K', 1),
        (20, 1, 'uint16', 'on_time_days', 'days', 1),
        # Date/time at 21 (2 regs) - skipping for now as it requires special parsing
        (23, 2, 'float32', 'energy_kwh_tariff1', 'kWh', 1),
        (25, 2, 'float32', 'volume_m3_tariff1', 'm³', 1),
        # Date at 27 (1 reg) - skipping
        (28, 1, 'uint16', 'error_flags', '', 1),
        (29, 2, 'uint32', 'model_version', '', 1),
        (31, 2, 'float32', 'energy_kwh_month1', 'kWh', 1),
        (33, 2, 'float32', 'energy_kwh_month1_tariff1', 'kWh', 1),
        (35, 2, 'float32', 'energy_kwh_month2', 'kWh', 1),
        (37, 2, 'float32', 'energy_kwh_month2_tariff1', 'kWh', 1),
        (39, 2, 'float32', 'energy_kwh_month3', 'kWh', 1),
        (41, 2, 'float32', 'energy_kwh_month3_tariff1', 'kWh', 1),
    ]
   
    def __init__(self, ip: str, port: int = 502, device_id: int = 255, timeout: int = 2):
        """
        Initialize Modbus meter reader
       
        Args:
            ip: IP address of Modbus gateway
            port: Modbus TCP port (default 502)
            device_id: Modbus device ID (default 255)
            timeout: Connection timeout in seconds
        """
        self.ip = ip
        self.port = port
        self.device_id = device_id
        self.timeout = timeout
        self.client: Optional[ModbusTcpClient] = None
   
    def connect(self) -> bool:
        """Establish connection to Modbus gateway"""
        self.client = ModbusTcpClient(self.ip, port=self.port, timeout=self.timeout)
        return self.client.connect()
   
    def disconnect(self):
        """Close connection to Modbus gateway"""
        if self.client:
            self.client.close()
   
    def _read_registers(self, address: int, count: int) -> list:
        """
        Read holding registers from Modbus
       
        Args:
            address: Starting register address (0-indexed)
            count: Number of registers to read
           
        Returns:
            List of register values
           
        Raises:
            RuntimeError: If read fails
        """
        if not self.client:
            raise RuntimeError("Not connected. Call connect() first.")
       
        rr = self.client.read_holding_registers(address, count=count, device_id=self.device_id)
        if rr is None or rr.isError():
            raise RuntimeError(f"Failed to read registers at address {address}: {rr}")
       
        return rr.registers
   
    def _decode_value(self, registers: list, data_type: str) -> Any:
        """
        Decode register values based on data type
       
        Args:
            registers: List of register values
            data_type: Type of data ('float32', 'uint32', 'uint16')
           
        Returns:
            Decoded value
        """
        if data_type == 'float32':
            # FLOAT32: MSW first, LSW second, big-endian
            return struct.unpack(">f", struct.pack(">HH", registers[0], registers[1]))[0]
       
        elif data_type == 'uint32':
            # UINT32: MSW first, LSW second
            return (registers[0] << 16) | registers[1]
       
        elif data_type == 'uint16':
            # UINT16: Single register
            return registers[0]
       
        else:
            raise ValueError(f"Unsupported data type: {data_type}")
   
    def read_meter(self, meter_num: int, fields: Optional[list] = None) -> Dict[str, Any]:
        """
        Read all accessible values from specified meter
       
        Args:
            meter_num: Meter number (1, 2, 3, or 4)
            fields: Optional list of field names to read. If None, reads all fields.
                   If provided, only returns the specified fields (no metadata).
           
        Returns:
            Dictionary with meter readings. If fields is None:
            {
                'fabrication_number': int,
                'energy_kwh': float,
                'volume_m3': float,
                'power_w': float,
                'max_power_w': float,
                'volume_flow_m3h': float,
                'max_volume_flow_m3h': float,
                'flow_temperature_c': float,
                'return_temperature_c': float,
                'temperature_difference_k': float,
                'on_time_days': int,
                'energy_kwh_tariff1': float,
                'volume_m3_tariff1': float,
                'error_flags': int,
                'model_version': int,
                'energy_kwh_month1': float,
                'energy_kwh_month1_tariff1': float,
                'energy_kwh_month2': float,
                'energy_kwh_month2_tariff1': float,
                'energy_kwh_month3': float,
                'energy_kwh_month3_tariff1': float,
                '_meter_num': int,
                '_units': dict  # Unit information for each field
            }
           
            If fields is specified, returns only those fields without metadata.
           
        Raises:
            ValueError: If meter_num is not 1-4 or if any field name is invalid
            RuntimeError: If connection fails or reading fails
        """
        if meter_num not in self.METER_OFFSETS:
            raise ValueError(f"Invalid meter number: {meter_num}. Must be 1, 2, 3, or 4.")
       
        if not self.client:
            raise RuntimeError("Not connected. Call connect() first.")
       
        # If specific fields requested, validate them
        if fields is not None:
            available_fields = {reg[3] for reg in self.REGISTERS}
            invalid_fields = set(fields) - available_fields
            if invalid_fields:
                raise ValueError(f"Invalid field names: {invalid_fields}. "
                               f"Available fields: {sorted(available_fields)}")
       
        meter_base = self.METER_OFFSETS[meter_num]
        results = {} if fields else {
            '_meter_num': meter_num,
            '_units': {}
        }
       
        # Read each register group
        for reg_offset, reg_count, data_type, field_name, unit, scaling in self.REGISTERS:
            # Skip if specific fields requested and this isn't one of them
            if fields is not None and field_name not in fields:
                continue
           
            try:
                # Calculate absolute register address
                abs_address = meter_base + reg_offset
               
                # Read registers
                registers = self._read_registers(abs_address, reg_count)
               
                # Decode value
                value = self._decode_value(registers, data_type)
               
                # Apply scaling if needed
                if scaling != 1:
                    value *= scaling
               
                # Store result
                results[field_name] = value
                if unit and fields is None:
                    results['_units'][field_name] = unit
               
            except Exception as e:
                # Store error but continue reading other registers
                results[field_name] = None
                if fields is None:
                    results[f'_{field_name}_error'] = str(e)
       
        return results
   
    def read_all_meters(self) -> Dict[int, Dict[str, Any]]:
        """
        Read all values from all 4 meters
       
        Returns:
            Dictionary with meter number as key and meter data as value:
            {
                1: {...meter 1 data...},
                2: {...meter 2 data...},
                3: {...meter 3 data...},
                4: {...meter 4 data...}
            }
        """
        results = {}
        for meter_num in [1, 2, 3, 4]:
            try:
                results[meter_num] = self.read_meter(meter_num)
            except Exception as e:
                results[meter_num] = {'_error': str(e), '_meter_num': meter_num}
       
        return results


def get_heatmeter_data(meter_num: int, ip: str = "192.168.29.25",
                   port: int = 502, device_id: int = 255,
                   fields: Optional[list] = None) -> Dict[str, Any]:
    """
    Convenience function to read a single meter
   
    Args:
        meter_num: Meter number (1-4)
        ip: Modbus gateway IP
        port: Modbus TCP port
        device_id: Modbus device ID
        fields: Optional list of field names to read. If None, reads all fields.
                If provided, only returns the specified fields (no metadata).
       
    Returns:
        Dictionary with meter readings (all fields or only specified fields)
       
    Example:
        >>> # Read all fields with metadata
        >>> data = get_meter_data(1)
        >>> print(f"Flow temp: {data['flow_temperature_c']:.2f} {data['_units']['flow_temperature_c']}")
        Flow temp: 74.00 °C
       
        >>> # Read only specific fields (no metadata)
        >>> data = get_meter_data(1, fields=['flow_temperature_c', 'power_w', 'volume_flow_m3h'])
        >>> print(data)
        {'flow_temperature_c': 74.0, 'power_w': 16878.0, 'volume_flow_m3h': 1.083}
    """
    reader = ModbusMeterReader(ip, port, device_id)
    try:
        if not reader.connect():
            raise RuntimeError(f"Failed to connect to {ip}:{port}")
        return reader.read_meter(meter_num, fields=fields)
    finally:
        reader.disconnect()


def get_all_heatmeters_data(ip: str = "192.168.29.25",
                        port: int = 502, device_id: int = 255) -> Dict[int, Dict[str, Any]]:
    """
    Convenience function to read all meters
   
    Args:
        ip: Modbus gateway IP
        port: Modbus TCP port
        device_id: Modbus device ID
       
    Returns:
        Dictionary with all meters' readings
       
    Example:
        >>> all_data = get_all_meters_data()
        >>> for meter_num, data in all_data.items():
        >>>     print(f"Meter {meter_num}: {data['flow_temperature_c']:.2f}°C")
    """
    reader = ModbusMeterReader(ip, port, device_id)
    try:
        if not reader.connect():
            raise RuntimeError(f"Failed to connect to {ip}:{port}")
        return reader.read_all_meters()
    finally:
        reader.disconnect()


if __name__ == "__main__":
    # Example usage
    import json
   
    print("\n" + "=" * 60)
    print("Example 2: Reading only directly measured values from Meter 1")
    print("=" * 60)
    print("(Excludes calculated values like temperature_difference_k, max_power_w, etc.)")
    try:
        # Only directly measured/metered values (not calculated)
        measured_fields = [
            'flow_temperature_c',      # Direct sensor measurement
            'return_temperature_c',    # Direct sensor measurement
            'volume_flow_m3h',         # Direct sensor measurement
            'power_w',                 # Metered (integrated)
            'energy_kwh',              # Metered (integrated power over time)
            'volume_m3'                # Metered (integrated flow over time)
        ]
        vals = get_heatmeter_data(1, fields=measured_fields)
        print(json.dumps(vals, indent=2, default=str))
       
    except Exception as e:
        print(f"Error: {e}")