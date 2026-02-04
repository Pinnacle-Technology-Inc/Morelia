from Morelia.Devices.SerialPorts.SerialComm import PortIO
from Morelia.Devices.SerialPorts.PortAccess import FindPorts
from Morelia.Devices.SerialPorts.queue_manager import PacketManager

# D2XX support (optional - requires pylibftdi)
try:
    from Morelia.Devices.SerialPorts.D2XXComm import D2XXPortIO
    D2XX_AVAILABLE = True
except ImportError:
    D2XXPortIO = None
    D2XX_AVAILABLE = False
