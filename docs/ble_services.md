Connected to 86F78E05-B6ED-BA13-4128-FC5A30F77EEE
MTU: 247

Service: 0000180d-0000-1000-8000-00805f9b34fb
  Description: Heart Rate
  Handle: 0x0020

  Characteristic: 00002a37-0000-1000-8000-00805f9b34fb
    Description: Heart Rate Measurement
    Handle: 0x0021
    Properties: notify
    Descriptor: 00002902-0000-1000-8000-00805f9b34fb
      Handle: 0x0023
      Value (hex): 

Service: 0000180a-0000-1000-8000-00805f9b34fb
  Description: Device Information
  Handle: 0x0030

  Characteristic: 00002a29-0000-1000-8000-00805f9b34fb
    Description: Manufacturer Name String
    Handle: 0x0031
    Properties: read
    Value (hex): 57484f4f5020496e632e
    Value (str): WHOOP Inc.

  Characteristic: 00002a24-0000-1000-8000-00805f9b34fb
    Description: Model Number String
    Handle: 0x0033
    Properties: read
    Value (hex): 352e3000

  Characteristic: 00002a25-0000-1000-8000-00805f9b34fb
    Description: Serial Number String
    Handle: 0x0035
    Properties: read
    Value (hex): 3541473032333330353300

  Characteristic: 00002a26-0000-1000-8000-00805f9b34fb
    Description: Firmware Revision String
    Handle: 0x0037
    Properties: read
    Value (hex): 35302e33352e332e30
    Value (str): 50.35.3.0

  Characteristic: 00002a27-0000-1000-8000-00805f9b34fb
    Description: Hardware Revision String
    Handle: 0x0039
    Properties: read
    Value (hex): 574735305f723532
    Value (str): WG50_r52

Service: 0000180f-0000-1000-8000-00805f9b34fb
  Description: Battery Service
  Handle: 0x0088

  Characteristic: 00002a19-0000-1000-8000-00805f9b34fb
    Description: Battery Level
    Handle: 0x0089
    Properties: notify, read
    Value (hex): 59
    Value (str): Y
    Descriptor: 00002902-0000-1000-8000-00805f9b34fb
      Handle: 0x008B
      Value (hex): 00

Service: fd4b0001-cce1-4033-93ce-002d5875f58a
  Description: Unknown
  Handle: 0x0999

  Characteristic: fd4b0002-cce1-4033-93ce-002d5875f58a
    Description: Unknown
    Handle: 0x099A
    Properties: write, write-without-response

  Characteristic: fd4b0003-cce1-4033-93ce-002d5875f58a
    Description: Unknown
    Handle: 0x099C
    Properties: notify
    Descriptor: 00002902-0000-1000-8000-00805f9b34fb
      Handle: 0x099E
      Value (hex): 00

  Characteristic: fd4b0004-cce1-4033-93ce-002d5875f58a
    Description: Unknown
    Handle: 0x099F
    Properties: notify
    Descriptor: 00002902-0000-1000-8000-00805f9b34fb
      Handle: 0x09A1
      Value (hex): 00

  Characteristic: fd4b0005-cce1-4033-93ce-002d5875f58a
    Description: Unknown
    Handle: 0x09A2
    Properties: notify
    Descriptor: 00002902-0000-1000-8000-00805f9b34fb
      Handle: 0x09A4
      Value (hex): 00

  Characteristic: fd4b0007-cce1-4033-93ce-002d5875f58a
    Description: Unknown
    Handle: 0x09A5
    Properties: notify
    Descriptor: 00002902-0000-1000-8000-00805f9b34fb
      Handle: 0x09A7
      Value (hex): 00
