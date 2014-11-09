"""Tests for the Simulator."""

import mock
import nengo
import numpy as np

from ..builder import Builder
from ..connections.connection_tree import ConnectionTree
from ..simulator import Simulator
from .test_assembler import reset_assembler
from .test_builder import reset_builder


# Create a sample Nengo network for testing purposes.
with nengo.Network(label="Test Network") as model:
    a = nengo.Ensemble(100, 3)
    a.eval_points = np.random.normal(size=(100, 3))
    b = nengo.Ensemble(100, 2)
    b.eval_points = np.random.normal(size=(100, 2))
    c = nengo.Connection(a[:2], b)


def test_simulator_init_uses_builder(reset_builder):
    """Test that initialising the simulator calls builder methods."""
    # Create a test network transform that we register with the builder to
    # ensure that it is called.  If the builder is used we can be relatively
    # sure that it is called correctly.
    def test_network_transform(*args):
        return args[:2]
    network_transform = mock.Mock(wraps=test_network_transform)
    Builder.add_network_transform(network_transform)

    # Create a simulator with the network and ensure that the builder function
    # is called with the objects, connections and probes from the model.
    config = mock.Mock(name='Config')
    sim = Simulator(model, dt=0.5, time_scaling=3.0, config=config)

    assert network_transform.called, "Builder not called"
    called_objs = network_transform.call_args[0][0]
    called_conns = network_transform.call_args[0][1]
    called_probes = network_transform.call_args[0][2]
    called_rngs = network_transform.call_args[0][3]

    assert sorted(called_objs) == sorted([a, b])
    assert called_conns == [c]
    assert called_probes == []
    assert a in called_rngs and b in called_rngs

    # Assert that the dt and machine timestep are saved correctly
    assert sim.config is config
    assert sim.dt == 0.5
    assert sim.machine_timestep == 1500000  # int((0.5 * 3.0) / 10**-6)


def test_simulator_calls_io_prepare_connection_tree(reset_builder):
    """Test that initialising the simulator calls the `process_network` method
    on the IO builder.
    """
    # Create a mock IO object which has a `process_network` static method
    # equivalent
    io_handler = mock.Mock(spec_set=['prepare_connection_tree'])
    io_handler.prepare_connection_tree = mock.Mock()
    io_handler.prepare_connection_tree.side_effect = lambda ctree: ctree

    # Initialise a new simulator with this IO type
    Simulator(model, io_type=io_handler)

    assert io_handler.prepare_connection_tree.called
    assert (type(io_handler.prepare_connection_tree.call_args[0][0]) is
            ConnectionTree)

def test_simulator_run(reset_builder):
    """Test that running the simulator:
      - Processes the model with the PACMAN toolchain
      - Initialises the IO object
    """
    raise NotImplementedError
