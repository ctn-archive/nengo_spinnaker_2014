import sys

from pacman103.core import control
from pacman103 import conf
from pacman103.lib import parameters

from . import builder
from . import io as io_builders


class Simulator(object):
    def __init__(self, model, dt=0.001, seed=None, io=None):
        # Build the model
        self.builder = builder.Builder()

        if io is None:
            # TODO Get IP address of machine from perspective of SpiNNaker
            # board
            # io = io_builders.Ethernet(addr)
            raise NotImplementedError

        self.dao = self.builder(model, dt, seed, io_builder=io)
        self.dao.writeTextSpecs = True

    def run(self, time):
        """Run the model, currently ignores the time."""
        self.controller = control.Controller(
            sys.modules[__name__],
            conf.config.get('Machine', 'machineName')
        )

        # Preparation functions
        # Consider moving this into PACMAN103
        for vertex in self.dao.vertices:
            if hasattr(vertex, 'prepare_vertex'):
                vertex.prepare_vertex()

        self.controller.dao = self.dao
        self.dao.set_hostname(conf.config.get('Machine', 'machineName'))
        self.controller.map_model()
        if self.builder.use_serial:
            self.generate_serial_key_maps()
        self.controller.generate_output()
        self.controller.load_targets()
        self.controller.load_write_mem()
        self.controller.run(self.dao.app_id)

        if self.builder.use_serial:
            self.start_serial_io(time)

    def generate_serial_key_maps(self):
        self.serial_rx = {}
        self.serial_tx = {}
        for edge in self.builder.serial.in_edges:
            for subedge in edge.subedges:
                key = edge.prevertex.generate_routing_info(subedge)[0]
                node = edge.post
                self.serial_tx[key] = node

        for edge in self.builder.serial.out_edges:
            for subedge in edge.subedges:
                key = edge.prevertex.generate_routing_info(subedge)[0]
                node = edge.pre
                if node not in self.serial_rx:
                    self.serial_rx[node] = [key]
                else:
                    self.serial_rx[node].append(key)

    def send_inputs(self, t):
        for node, keys in self.serial_rx.iteritems():
            value = parameters.s1615(node.output(t))
            for key in keys:
                for d, v in enumerate(value):
                    if v<0:
                        v += 0x100000000
                    msg = '%08x.%08x\n' % (key | d, v)
                    self.serial.write(msg)
        self.serial.flush()

        #TODO: handle node to node and nodes that are both inputs and outputs


    def handle_retina(self, x, y):
        print 'retina', x, y


    def start_serial_io(self, time):
        import serial
        import time

        input_period = 0.1
        last_input = None

        self.serial = serial.Serial('/dev/ttyUSB0', baudrate=8000000,
                                    rtscts=True)
        self.serial.write("S+\n")   # send spinnaker packets to host
        #self.serial.write("E+\n")   # send retina packets to host
        #self.serial.write("Z+\n")   # turn on retina
        start = time.time()
        buffer = {}
        line = ''
        retina = False
        while True:
            now = time.time()
            if last_input is None or now > last_input + input_period:
                self.send_inputs(now - start)

            c = self.serial.read()
            assert len(c) == 1
            line += c

            if retina and len(line) >= 2:
                self.handle_retina(ord(line[-2]), ord(line[-1]))
                line = ''
                retina = False
                continue

            if ord(c) & 0x80:
                retina = True
                line = c
                continue

            if c == '\n':
                if ord(line[0])==0:
                    line = line[1:]
                print line
                if '.' not in line:
                    continue
                parts = line.split('.')
                parts = [int(p,16) for p in parts]
                if len(parts) == 3:
                    header, key, payload = parts

                    if payload & 0x80000000:
                        payload -= 0x100000000
                    value = (payload * 1.0) / (2**15)

                    base_key = key & 0xFFFFF800
                    d = (key & 0x0000003F)

                    if base_key in self.serial_tx:
                        node = self.serial_tx[base_key]

                        vector = buffer.get(base_key, None)
                        if vector is None:
                            vector = [None]*node.size_in
                            buffer[base_key] = vector
                        vector[d] = value
                        if None not in vector:
                            node.output(now - start, vector)
                            del buffer[base_key]
                line = ''
                retina = False

