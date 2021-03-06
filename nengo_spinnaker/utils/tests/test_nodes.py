import mock
import numpy as np

import nengo
from nengo.utils.builder import objs_and_connections, remove_passthrough_nodes
import nengo_spinnaker
from nengo_spinnaker.utils import nodes


def test_output_to_board_node_simple():
    io = mock.Mock()
    m = nengo.Node(output=None, size_out=5, add_to_container=False)
    n = nodes.create_output_node(m, io)

    output = np.random.uniform(-1, 1, 5)
    n.output(0.5, output)

    assert(io.set_node_output.call_count == 1)
    for call in io.set_node_output.call_args_list:
        assert(call[0][0] == m)
        assert(np.all(call[0][1] == output))


def test_input_from_board_node_simple():
    io = mock.Mock()
    io.get_node_input.return_value = np.zeros(5)

    m = nengo.Node(output=None, size_in=5, add_to_container=False)
    n = nodes.create_input_node(m, io)

    input_to_m = n.output(0.5)

    assert(io.get_node_input.call_count == 1)
    io.get_node_input.assert_called_with(m)
    assert(np.all(np.zeros(5) == input_to_m))


def test_input_from_board_node_simple_2():
    io = mock.Mock()
    io.get_node_input.return_value = None

    m = nengo.Node(output=None, size_in=5, add_to_container=False)
    n = nodes.create_input_node(m, io)

    input_to_m = n.output(0.5)

    assert(io.get_node_input.call_count == 1)
    io.get_node_input.assert_called_with(m)
    assert(np.all(np.zeros(5) == input_to_m))


def test_replace_node_ensemble_connections_no_conf():
    model = nengo.Network()
    with model:
        a = nengo.Node(0.5)
        b = nengo.Node(lambda t: [np.sin(t), np.cos(t)])
        c = nengo.Node(lambda t, v: v, size_in=1)

        e = nengo.Ensemble(1, 1)

        c1 = nengo.Connection(a, e)
        c2 = nengo.Connection(b, e, transform=[[1., 0.]])
        c3 = nengo.Connection(a, c)

    mock_io = mock.Mock()
    (ns, conns) = nodes.replace_node_ensemble_connections(model.connections,
                                                          mock_io)

    # There should be one additional Node: for B
    assert(len(ns) == 1)
    assert(ns[0].output.node == b)

    # There should be 2 connections B->(B) and A->C
    assert(len(conns) == 2)
    assert(c3 in conns)
    for conn in conns:
        assert(conn.pre == a or conn.pre == b)
        if conn.pre == a: assert(conn.post == c)
        if conn.pre == b: assert(conn.post.output.node == b)


def test_replace_node_ensemble_connections_conf():
    model = nengo.Network()
    with model:
        a = nengo.Node(lambda t: np.sin)
        b = nengo.Node(lambda t: [np.sin(t), np.cos(t)])
        c = nengo.Node(lambda t, v: v, size_in=1)

        e = nengo.Ensemble(1, 1)

        c1 = nengo.Connection(a, e)
        c2 = nengo.Connection(b, e, transform=[[1., 0.]])
        c3 = nengo.Connection(a, c)

    config = nengo_spinnaker.Config()
    config[a].f_of_t = True

    mock_io = mock.Mock()
    (ns, conns) = nodes.replace_node_ensemble_connections(
        model.connections, mock_io, config)

    # There should be one additional Node: for B
    assert(len(ns) == 1)
    assert(ns[0].output.node == b)

    # There should be 2 connections B->(B) and A->C
    assert(len(conns) == 2)
    assert(c3 in conns)
    for conn in conns:
        assert(conn.pre == a or conn.pre == b)
        if conn.pre == a: assert(conn.post == c)
        if conn.pre == b: assert(conn.post.output.node == b)


def test_replace_ensemble_node_connections():
    model = nengo.Network()
    with model:
        a = nengo.Ensemble(1, 1)
        b = nengo.Node(lambda t, v: v, size_in=1)
        c = nengo.Node(lambda t, v: v**2, size_in=1)
        d = nengo.Node(lambda t, v: v**2, size_in=1)

        nengo.Connection(a, b)
        nengo.Connection(a, c)
        c_d = nengo.Connection(c, d)

    mock_io = mock.Mock()
    (ns, conns) = nodes.replace_ensemble_node_connections(
        model.connections, mock_io)

    # There should be 2 additional nodes, for A->B and A->C
    assert(len(ns) == 2)

    # There should be 3 connections, (B)->B and (C)->C, C->D
    assert(len(conns) == 3)
    for c in conns:
        if c.post == b: assert(c.pre.output.node == b)
        if c.post == c: assert(c.pre.output.node == c)
        if c.post == d: assert(c == c_d)


def test_remove_custom_nodes():
    """Remove Nodes which have a `spinnaker_build` method.  Connections to/from
    them from Nodes should be treated like connections to/from Ensembles.
    """
    class TestNode(nengo.Node):
        def spinnaker_build(self, builder):
            pass

    model = nengo.Network()
    with model:
        n = TestNode(output=lambda t, v: v, size_in=1, size_out=1, label='n')
        a = nengo.Ensemble(1, 1, label='a')
        b = nengo.Node(lambda t, v: v, size_in=1, size_out=1, label='b')
        c = nengo.Node(lambda t: t, size_in=0, size_out=1, label='c')
        d = nengo.Node(lambda t, v: t, size_in=1, size_out=1, label='d')

        n_a = nengo.Connection(n, a)
        a_b = nengo.Connection(a, b)
        b_n = nengo.Connection(b, n)
        c_n = nengo.Connection(c, n)
        n_d = nengo.Connection(n, d)

    mock_io = mock.Mock()
    (ns, conns) = nodes.remove_custom_nodes(
        model.nodes, model.connections, mock_io)

    # There should be the 3 nodes b, c, d and (b->n), (c->n), n->d)
    assert(len(ns) == 6)
    assert(n not in ns)

    # There should be the connections A->(B), B->(N), C->(N) and N->(D)
    assert(len(conns) == 4)
    for c in conns:
        if c.post == b: assert(c.pre == a)
        if c.pre == b: assert(c.post.output.node == b)
        if c.pre == c: assert(c.post.output.node == c)
        if c.post == d: assert(c.pre.output.node == d)


def test_get_connected_nodes():
    model = nengo.Network()
    with model:
        a = nengo.Ensemble(1, 1)
        b = nengo.Node(lambda t, v: t, size_in=1, size_out=1)

        c = nengo.Node(lambda t, v: None, size_in=1, size_out=0)
        d = nengo.Node(lambda t, v: None, size_in=1, size_out=0)

        a_c = nengo.Connection(a, c)
        b_c = nengo.Connection(b, c)

    ns = nodes.get_connected_nodes(model.connections)
    assert(a not in ns)
    assert(b in ns)
    assert(c in ns)
    assert(d not in ns)


def test_create_host_network():
    """Test creating a network to simulate on the host.  All I/O connections
    will have been replaced with new Nodes which handle communication with the
    IO system.
    """
    class TestNode(nengo.Node):
        def spinnaker_build(self, builder):
            pass

    model = nengo.Network()
    with model:
        a = nengo.Ensemble(1, 1, label="A")
        b = nengo.Node(lambda t, v: v, size_in=1, size_out=1, label="B")
        c = nengo.Node(lambda t, v: v**2, size_in=1, size_out=1, label="C")
        d = nengo.Ensemble(1, 1, label="D")
        n = TestNode(output=lambda t, v: v, size_in=1, size_out=1, label="N")
        o = nengo.Node(lambda t, v: v, size_in=1, size_out=1, label="Orphan")
        e = nengo.Ensemble(1, 1, label="E")

        a_b = nengo.Connection(a, b)
        b_c = nengo.Connection(b, c)
        c_d = nengo.Connection(c, d)

        a_n = nengo.Connection(a, n)
        b_n = nengo.Connection(b, n)
        n_d = nengo.Connection(n, d)

        d_e = nengo.Connection(d, e)

    mock_io = mock.Mock()
    (objs, conns) = remove_passthrough_nodes(*objs_and_connections(model))
    host_network = nodes.create_host_network(
        [n for n in objs if isinstance(n, nengo.Node)], conns, mock_io)

    assert(len(host_network.ensembles) == 0)
    assert(len(host_network.nodes) == 5)  # b, c, (a->b), (c->d), (b->n)
    assert(len(host_network.connections) == 4) # (a)->b, b->c, c->(d), b->(n)

    assert(b in host_network.nodes)
    assert(c in host_network.nodes)

    assert(a_n not in host_network.connections)
    assert(b_n not in host_network.connections)
    assert(n_d not in host_network.connections)
    assert(d_e not in host_network.connections)
    assert(n not in host_network.nodes)
    assert(o not in host_network.nodes)

    for c_ in host_network.connections:
        if c_.post == b: assert(c_.pre.output.node == b)
        if c_.pre == b: assert(c_.post == c or c_.post.output.node == b)
        if c_.pre == c: assert(c_.post.output.node == c)


def test_create_host_network_nested():
    model = nengo.Network()
    with model:
        m2 = nengo.Network()
        with m2:
            pn0 = nengo.Node(None, size_in=1, label='PassNode')
            a = nengo.Ensemble(1, 1)
            n1 = nengo.Node(lambda t, v: v, size_in=1, label='n1')

            nengo.Connection(pn0, a, synapse=None)
            nengo.Connection(a, n1)

        n2 = nengo.Node(np.sin, label='input')
        n3 = nengo.Node(lambda t, v: v, size_in=1, size_out=1, label='output')

        nengo.Connection(n2, pn0)
        nn = nengo.Connection(n1, n3)

    mock_io = mock.Mock()
    (objs, conns) = remove_passthrough_nodes(*objs_and_connections(model))
    host_network = nodes.create_host_network(
        [n for n in objs if isinstance(n, nengo.Node)], conns, mock_io)

    # Should be 5 nodes
    # n1, n2, n3, Input for n1, Output for n2
    assert(len(host_network.nodes) == 5)
    assert(pn0 not in host_network.nodes)
    assert(n1 in host_network.nodes)
    assert(n2 in host_network.nodes)
    assert(n3 in host_network.nodes)

    assert(len(host_network.connections) == 3)
    assert(nn in host_network.connections)
