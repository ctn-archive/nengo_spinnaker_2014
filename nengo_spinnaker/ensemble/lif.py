import numpy as np
import warnings

import nengo
from nengo.builder import sample as builder_sample
from nengo.utils import distributions as dists
import nengo.utils.builder as builder_utils
import nengo.utils.numpy as npext
from nengo.utils.stdlib import checked_call

from . import connections as ens_conn_utils
from . import decoders as decoder_utils
from . import intermediate
from ..utils.fixpoint import bitsk

from ..spinnaker import regions, vertices


class IntermediateLIF(intermediate.IntermediateEnsemble):
    def __init__(self, n_neurons, gains, bias, encoders, decoders, tau_rc,
                 tau_ref, eval_points, decoder_headers, learning_rules):
        super(IntermediateLIF, self).__init__(
            n_neurons, gains, bias, encoders, decoders, eval_points,
            decoder_headers, learning_rules)
        self.tau_rc = tau_rc
        self.tau_ref = tau_ref

    @classmethod
    def from_object(cls, ens, out_conns, dt, rng):
        assert isinstance(ens.neuron_type, nengo.neurons.LIF)
        assert isinstance(ens, nengo.Ensemble)

        rng = np.random.RandomState(ens.seed)

        # Generate evaluation points
        if isinstance(ens.eval_points, dists.Distribution):
            n_points = ens.n_eval_points
            if n_points is None:
                n_points = builder_utils.default_n_eval_points(ens.n_neurons,
                                                               ens.dimensions)
            eval_points = ens.eval_points.sample(n_points, ens.dimensions, rng)
            eval_points *= ens.radius
        else:
            if (ens.eval_points is not None and
                    ens.eval_points.shape[0] != ens.n_eval_points):
                warnings.warn("Number of eval points doesn't match "
                              "n_eval_points.  Ignoring n_eval_points.")
            eval_points = np.array(ens.eval_points, dtype=np.float64)

        # Determine max_rates and intercepts
        max_rates = builder_sample(ens.max_rates, ens.n_neurons, rng)
        intercepts = builder_sample(ens.intercepts, ens.n_neurons, rng)

        # Generate gains, bias
        gain, bias = ens.neuron_type.gain_bias(max_rates, intercepts)

        # Generate encoders
        if isinstance(ens.encoders, dists.Distribution):
            encoders = ens.encoders.sample(ens.n_neurons, ens.dimensions,
                                           rng=rng)
        else:
            encoders = npext.array(ens.encoders, min_dims=2, dtype=np.float64)
            encoders /= npext.norm(encoders, axis=1, keepdims=True)

        # Generate decoders for outgoing connections
        decoders = list()
        tfses, tfse_map = \
            ens_conn_utils.get_combined_outgoing_ensemble_connections(
                out_conns)

        def build_decoder(function, evals, solver):
            """Internal function for building a single decoder."""
            if evals is None:
                evals = npext.array(eval_points, min_dims=2)
            else:
                evals = npext.array(evals, min_dims=2)

            assert solver is None or not solver.weights

            x = np.dot(evals, encoders.T / ens.radius)
            activities = ens.neuron_type.rates(x, gain, bias)

            if function is None:
                targets = evals
            else:
                (value, _) = checked_call(function, evals[0])
                function_size = np.asarray(value).size
                targets = np.zeros((len(evals), function_size))

                for i, ep in enumerate(evals):
                    targets[i] = function(ep)

            if solver is None:
                solver = nengo.solvers.LstsqL2()

            return solver(activities, targets, rng=rng)[0]

        decoder_builder = decoder_utils.DecoderBuilder(build_decoder)

        # Build each of the decoders in turn
        for tfse in tfses:
            decoders.append(decoder_builder.get_transformed_decoder(
                tfse.function, tfse.transform, tfse.eval_points, tfse.solver))

        # Build list of learning rule, connection-index tuples
        learning_rules = list()
        for c in tfse_map:
            for l in ens_conn_utils.get_learning_rules(c):
                learning_rules.append((l, tfse_map[c]))

        # By default compress all decoders
        decoders_to_compress = [True for d in decoders]

        # Turn off compression for all decoders associated with learning rules
        for l in learning_rules:
            decoders_to_compress[l[1]] = False

        # Compress and merge the decoders
        (decoder_headers, decoders) =\
            decoder_utils.get_combined_compressed_decoders(
                decoders, compress=decoders_to_compress)
        decoders /= dt

        return cls(ens.n_neurons, gain, bias, encoders, decoders,
                   ens.neuron_type.tau_rc, ens.neuron_type.tau_ref,
                   eval_points, decoder_headers, learning_rules)


class SystemRegion(regions.Region):
    """Region representing parameters for a LIF ensemble.
    """
    def __init__(self, n_input_dimensions, n_output_dimensions,
                 machine_timestep, t_ref, dt_over_t_rc, record_spikes):
        """Create a new system region for a LIF ensemble.

        :param n_input_dimensions: Number of input dimensions (TODO: remove)
        :param n_output_dimensions: Number of output dimensions (TODO: remove)
        :param machine_timestep: Timestep in microseconds (TODO: remove)
        :param float t_ref: Refractory period.
        :param float dt_over_t_rc:
        :param bool: Record spikes (TODO: Move elsewhere?)
        """
        self.n_input_dimensions = n_input_dimensions
        self.n_output_dimensions = n_output_dimensions
        self.machine_timestep = machine_timestep
        self.t_ref_in_ticks = int(t_ref / (machine_timestep * 10**-6))
        self.dt_over_t_rc = bitsk(dt_over_t_rc)
        self.record_flags = 0x1 if record_spikes else 0x0

    def sizeof(self, vertex_slice):
        """Get the size of this region in WORDS."""
        # Is a constant, 8
        return 8

    def create_subregion(self, vertex_slice, vertex_index):
        """Create a subregion for this slice of the vertex.
        """
        data = np.array([
            self.n_input_dimensions,
            self.n_output_dimensions,
            vertex_slice.stop - vertex_slice.start,
            self.machine_timestep,
            self.t_ref_in_ticks,
            self.dt_over_t_rc,
            self.record_flags,
            1,
        ], dtype=np.uint32)

        return regions.Subregion(data, len(data), False)


class EnsembleLIF(vertices.Vertex):
    executable_path = None  # TODO

    def __init__(self, n_neurons, system_region, bias_region, encoders_region,
                 decoders_region, output_keys_region, input_filter_region,
                 input_filter_routing, inhib_filter_region,
                 inhib_filter_routing, gain_region, modulatory_filter_region,
                 modulatory_filter_routing, pes_region, spikes_region):
        regions = [
            system_region,  # 1
            bias_region,  # 2
            encoders_region,  # 3
            decoders_region,  # 4
            output_keys_region,  # 5
            input_filter_region,  # 6
            input_filter_routing,  # 7
            inhib_filter_region,  # 8
            inhib_filter_routing,  # 9
            gain_region,  # 10
            modulatory_filter_region,  # 11
            modulatory_filter_routing,  # 12
            pes_region,  # 13
            None,  # 14
            spikes_region,  # 15
        ]
        super(EnsembleLIF, self).__init__(n_neurons, '', regions)

    @classmethod
    def assemble_from_intermediate(cls, ens, assembler):
        raise NotImplementedError

"""
    @classmethod
    def assemble(cls, ens, assembler):
        # Prepare the system region
        system_items = [
            ens.n_dimensions,
            len(ens.output_keyspaces),
            ens.n_neurons,
            assembler.timestep,
            int(ens.tau_ref / (assembler.timestep * 10**-6)),
            utils.fp.bitsk(assembler.dt / ens.tau_rc),
            0x1 if ens.record_spikes else 0x0,
            1
        ]

        # Prepare the input filtering regions
        # Prepare the inhibitory filtering regions
        in_conns = assembler.get_incoming_connections(ens)
        inhib_conns =\
            [c for c in in_conns if isinstance(
                c, ens_conn_utils.IntermediateGlobalInhibitionConnection)]
        modul_conns = [c for c in in_conns if c.modulatory]
        input_conns = [c for c in in_conns
                       if c not in inhib_conns and c not in modul_conns]

        (input_filter_region, input_filter_routing, _) =\
            utils.vertices.make_filter_regions(input_conns, assembler.dt)
        (inhib_filter_region, inhib_filter_routing, _) =\
            utils.vertices.make_filter_regions(inhib_conns, assembler.dt)
        (modul_filter_region, modul_filter_routing, modul_filter_assign) =\
            utils.vertices.make_filter_regions(modul_conns, assembler.dt)

        # From list of learning rules, extract list of PES learning rules
        pes_learning_rules = [l for l in ens.learning_rules
                              if isinstance(l[0], nengo.PES)]

        # Check no non-supported learning rules were present in original list
        if len(pes_learning_rules) != len(ens.learning_rules):
            raise NotImplementedError("Only PES learning rules currently "
                                      "supported.")

        # Begin PES items with number of learning rules
        pes_items = [len(pes_learning_rules)]
        for p in pes_learning_rules:
            # Generate block of data for this learning rule
            data = [
                utils.fp.bitsk(p[0].learning_rate * assembler.dt),
                modul_filter_assign[p[0].error_connection],
                p[1]
            ]

            # Add to PES items
            pes_items.extend(data)

        # Generate all the regions in turn, then return a new vertex
        # instance.
        encoders_with_gain = ens.encoders * ens.gains[:, np.newaxis]
        bias_with_di = np.dot(encoders_with_gain, ens.direct_input) + ens.bias

        system_region = utils.vertices.UnpartitionedListRegion(
            system_items, n_atoms_index=2)
        bias_region = utils.vertices.MatrixRegionPartitionedByRows(
            bias_with_di, formatter=utils.fp.bitsk)
        encoders_region = utils.vertices.MatrixRegionPartitionedByRows(
            encoders_with_gain, formatter=utils.fp.bitsk)
        decoders_region = utils.vertices.MatrixRegionPartitionedByRows(
            ens.decoders, formatter=utils.fp.bitsk)
        output_keys_region = utils.vertices.UnpartitionedKeysRegion(
            ens.output_keyspaces)
        gain_region = utils.vertices.MatrixRegionPartitionedByRows(
            ens.gains, formatter=utils.fp.bitsk)
        pes_region = utils.vertices.UnpartitionedListRegion(pes_items)
        spikes_region = utils.vertices.BitfieldBasedRecordingRegion(
            assembler.n_ticks)

        vertex = cls(ens.n_neurons, system_region, bias_region,
                     encoders_region, decoders_region, output_keys_region,
                     input_filter_region, input_filter_routing,
                     inhib_filter_region, inhib_filter_routing, gain_region,
                     modul_filter_region, modul_filter_routing,
                     pes_region, spikes_region)
        vertex.probes = ens.probes
        return vertex
"""
