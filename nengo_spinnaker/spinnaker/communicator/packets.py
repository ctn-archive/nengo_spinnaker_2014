"""Representations of SDP and SCP Packets."""
import struct
from weakref import WeakKeyDictionary

# SDP header flags
FLAG_REPLY = 0x87
FLAG_NO_REPLY = 0x07


class RangedIntAttribute(object):
    """Descriptor that ensures values fit within a range of values."""
    def __init__(self, minimum, maximum, min_inclusive=True,
                 max_inclusive=False):
        """Create a new ranged descriptor with specified minimum and maximum
        values.
        """
        if not min_inclusive:
            minimum += 1  # Convert from [x, y) to (x, y)
        if max_inclusive:
            maximum += 1  # Convert from [x, y) to [x, y]

        if not minimum <= maximum:
            raise ValueError('min should be smaller than max')

        self.default = minimum
        self.min = minimum
        self.max = maximum
        self.data = WeakKeyDictionary()

    def __get__(self, instance, owner):
        # Get the value, or the default
        return self.data.get(instance, self.default)

    def __set__(self, instance, value):
        # Check that min <= value < max
        if not self.min <= value < self.max:
            raise ValueError(
                "Value outside range: [{} to {})".format(self.min, self.max))
        if not isinstance(value, int):
            raise TypeError("Value should be an integer: {!s}".format(value))
        self.data[instance] = value


class ByteStringAttribute(object):
    """Descriptor that ensures values are bytestrings of the correct length."""
    def __init__(self, default=b'', max_length=None):
        self.max_length = max_length
        self.default = default
        self.data = WeakKeyDictionary()

    def __get__(self, instance, owner):
        return self.data.get(instance, self.default)

    def __set__(self, instance, value):
        if self.max_length is not None and len(value) > self.max_length:
            raise ValueError(
                "Byte string is too long: should be less than {} bytes"
                .format(self.max_length)
            )
        self.data[instance] = value


class SDPPacket(object):
    """An SDP Packet"""
    __slots__ = ['reply_expected', 'tag', 'dest_port', 'dest_cpu', 'src_port',
                 'src_cpu', 'dest_x', 'dest_y', 'src_x', 'src_y', 'data',
                 '__weakref__']
    tag = RangedIntAttribute(0, 256)
    dest_port = RangedIntAttribute(0, 8)
    dest_cpu = RangedIntAttribute(0, 18)
    src_port = RangedIntAttribute(0, 8)
    src_cpu = RangedIntAttribute(0, 18)
    dest_x = RangedIntAttribute(0, 256)
    dest_y = RangedIntAttribute(0, 256)
    src_x = RangedIntAttribute(0, 256)
    src_y = RangedIntAttribute(0, 256)
    data = ByteStringAttribute(max_length=272)

    def __init__(self, reply_expected, tag, dest_port, dest_cpu, src_port,
                 src_cpu, dest_x, dest_y, src_x, src_y, data):
        """Create a new SDPPacket.

        Parameters
        ----------
        reply_expected : bool
            True if a reply is expected, otherwise False.
        tag : int
            An integer representing the IPTag that should be used to transmit
            the packer over an IPv4 network.
        """
        self.reply_expected = reply_expected
        self.tag = tag
        self.dest_port = dest_port
        self.dest_cpu = dest_cpu
        self.src_port = src_port
        self.src_cpu = src_cpu
        self.dest_x = dest_x
        self.dest_y = dest_y
        self.src_x = src_x
        self.src_y = src_y
        self.data = data

    @classmethod
    def unpack_packet(cls, bytestring):
        """Unpack the SDP header from a bytestring."""
        # Extract the header and the data from the packet
        header = bytestring[0:8]  # First 8 bytes
        data = bytestring[8:]  # Everything else

        # Unpack the header
        (flags, tag, dest_cpu_port, src_cpu_port, dest_x, dest_y,
         src_x, src_y) = struct.unpack('<8B', header)

        # Neaten up the combined VCPU and port fields
        dest_cpu, dest_port = cls.unpack_dest_cpu_port(dest_cpu_port)
        src_cpu, src_port = cls.unpack_dest_cpu_port(src_cpu_port)

        # Create a dictionary representing the packet.
        return dict(
            reply_expected=flags == FLAG_REPLY, tag=tag, dest_port=dest_port,
            dest_cpu=dest_cpu, src_port=src_port, src_cpu=src_cpu,
            dest_x=dest_x, dest_y=dest_y, src_x=src_x, src_y=src_y, data=data
        )

    @classmethod
    def from_bytestring(cls, bytestring):
        """Create a new SDPPacket from a bytestring.

        Returns
        -------
        SDPPacket
            An SDPPacket containing the data from the bytestring.
        """
        return cls(**cls.unpack_packet(bytestring))

    @staticmethod
    def pack_dest_cpu_port(port, cpu):
        return ((port & 0x07) << 5) | (cpu & 0x1f)

    @staticmethod
    def unpack_dest_cpu_port(portcpu):
        return portcpu & 0x1f, ((portcpu >> 5) & 0x07)

    @property
    def packed_dest_cpu_port(self):
        return self.pack_dest_cpu_port(self.dest_port, self.dest_cpu)

    @property
    def packed_src_cpu_port(self):
        return self.pack_dest_cpu_port(self.src_port, self.src_cpu)

    @property
    def packed_data(self):
        return self.data

    @property
    def bytestring(self):
        """Convert the packet into a bytestring."""
        # Construct the header
        header = struct.pack(
            '<8B', FLAG_REPLY if self.reply_expected else FLAG_NO_REPLY,
            self.tag, self.packed_dest_cpu_port, self.packed_src_cpu_port,
            self.dest_x, self.dest_y, self.src_x, self.src_y
        )

        # Return the header and the packed data
        return header + self.packed_data


class SCPPacket(SDPPacket):
    """An SCP Packet"""
    __slots__ = ['cmd_rc', 'seq', 'arg1', 'arg2', 'arg3', 'scp_data']
    cmd_rc = RangedIntAttribute(0, 0xFFFF, max_inclusive=True)
    seq = RangedIntAttribute(0, 0xFFFF, max_inclusive=True)
    arg1 = RangedIntAttribute(0, 0xFFFFFFFF, max_inclusive=True)
    arg2 = RangedIntAttribute(0, 0xFFFFFFFF, max_inclusive=True)
    arg3 = RangedIntAttribute(0, 0xFFFFFFFF, max_inclusive=True)
    data = ByteStringAttribute(max_length=256)

    def __init__(self, reply_expected, tag, dest_port, dest_cpu, src_port,
                 src_cpu, dest_x, dest_y, src_x, src_y, cmd_rc, seq, arg1,
                 arg2, arg3, data):
        super(SCPPacket, self).__init__(
            reply_expected, tag, dest_port, dest_cpu, src_port,
            src_cpu, dest_x, dest_y, src_x, src_y, data)

        # Store additional data for the SCP packet
        self.cmd_rc = cmd_rc
        self.seq = seq
        self.arg1 = arg1
        self.arg2 = arg2
        self.arg3 = arg3

    @classmethod
    def from_sdp_packet(cls, sdp_packet):
        """Create a new SCPPacket from an existing SDPPacket.
        
        Parameters
        ----------
        sdp_packet : :py:class:`SDPPacket`
            An existing SDP packet.
        """
        # Get the SCP header from the SDP packet
        assert isinstance(sdp_packet, SDPPacket)
        scp_header = cls.unpack_scp_header(sdp_packet.data)

        # Create the new SCP packet and return
        # ***YUCK***
        return cls(
            reply_expected=sdp_packet.reply_expected,
            tag=sdp_packet.tag, dest_port=sdp_packet.dest_port,
            dest_cpu=sdp_packet.dest_cpu, src_port=sdp_packet.src_port,
            src_cpu=sdp_packet.src_cpu, dest_x=sdp_packet.dest_x,
            dest_y=sdp_packet.dest_y, src_x=sdp_packet.src_x,
            src_y=sdp_packet.src_y, **scp_header
        )

    @classmethod
    def unpack_scp_header(cls, data):
        """Unpack the SCP header from a bytestring."""
        # Unpack the SCP header from the data
        (cmd_rc, seq, arg1, arg2, arg3) = struct.unpack(
            '<2H3I', data[0:16])

        # Return the SCP header
        scp_header = {
            'cmd_rc': cmd_rc, 'seq': seq, 'arg1': arg1, 'arg2': arg2, 'arg3':
            arg3, 'data': data[16:]}
        return scp_header

    @property
    def packed_data(self):
        """Pack the data for the SCP packet."""
        scp_header = struct.pack("<2H3I", self.cmd_rc, self.seq, self.arg1,
                                 self.arg2, self.arg3)

        # Return the SCP header and the rest of the data
        return scp_header + self.data