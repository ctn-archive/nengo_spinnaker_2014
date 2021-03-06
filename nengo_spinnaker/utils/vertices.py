import numpy as np
import struct

from pacman103.lib import graph, data_spec_gen, lib_map
from pacman103.core.utilities import memory_utils
from pacman103.core.spinnman.scp import scamp

from . import connections, fp

try:
    from pkg_resources import resource_filename
except ImportError:
    import os.path

    def resource_filename(module_name, filename):
        """Get the filename for a given resource."""
        mod = __import__(module_name)
        return os.path.join(os.path.dirname(mod.__file__), filename)


class NengoVertex(graph.Vertex):
    runtime = None

    @property
    def model_name(self):
        return self.MODEL_NAME

    def get_maximum_atoms_per_core(self):
        return self.MAX_ATOMS

    def get_resources_for_atoms(self, lo_atom, hi_atom, n_machine_time_steps,
                                *args):
        cpu_usage = 0
        if hasattr(self, 'cpu_usage'):
            cpu_usage = self.cpu_usage(lo_atom, hi_atom)

        sdram_usage = sum([r.sizeof(lo_atom, hi_atom) for r in self.regions if
                           r is not None])
        dtcm_usage = sum([r.sizeof(lo_atom, hi_atom) for f in self.regions if
                          r is not None and r.in_dtcm])

        return lib_map.Resources(cpu_usage, dtcm_usage, sdram_usage)

    def generateDataSpec(self, processor, subvertex, dao):
        # Create a spec, reserve regions and fill in as necessary
        spec = data_spec_gen.DataSpec(processor, dao)
        spec.initialise(0xABCD, dao)
        self.__reserve_regions(subvertex, spec)
        self.__write_regions(subvertex, spec)
        spec.endSpec()
        spec.closeSpecFile()

        # Write the runtime to the core
        x, y, p = processor.get_coordinates()
        self.run_ticks = ((1 << 32) - 1 if self.runtime is None else
                          int(self.runtime * 1000))  # TODO timestep scaling

        addr = 0xe5007000 + 128 * p + 116  # Space reserved for _p_
        mem_writes = [lib_map.MemWriteTarget(x, y, p, addr, self.run_ticks)]

        # Get the executable
        executable_target = lib_map.ExecutableTarget(
            resource_filename(self.__class__.__module__.split('.')[0],
                              "binaries/%s.aplx" % self.MODEL_NAME),
            x, y, p)

        return (executable_target, list(), mem_writes)

    def __reserve_regions(self, subvertex, spec):
        # Reserve a region of memory for each specified region
        for i, region in enumerate(self.regions, start=1):
            if region is None:
                continue

            # Get the size (in words) of the region to reserve space for
            size = region.sizeof(subvertex.lo_atom, subvertex.hi_atom)

            # Only reserve memory for regions that actually require space
            if size > 0:
                spec.reserveMemRegion(i, size*4, leaveUnfilled=region.unfilled)

    def __write_regions(self, subvertex, spec):
        # Write each region in turn
        for i, region in enumerate(self.regions, start=1):
            if region is None:
                continue

            # Determine the size (in words) of the region (size=0 means
            # unreserved)
            size = region.sizeof(subvertex.lo_atom, subvertex.hi_atom)

            # If space is reserved and the region is to be filled then
            # write the region
            if size > 0 and not region.unfilled:
                spec.switchWriteFocus(i)
                if isinstance(region, UnpartitionedKeysRegion):
                    index = self.subvertices.index(subvertex)
                    region.write_out(subvertex.lo_atom, subvertex.hi_atom,
                                     index, spec)
                else:
                    region.write_out(subvertex.lo_atom, subvertex.hi_atom,
                                     spec)

    def generate_routing_info(self, subedge):
        # TODO When PACMAN is refactored we can get rid of this because we've
        #      already allocated keys to connections, and there is a map of 1
        #      connection to 1 edge and keys are placement independent (hence
        #      all subedges of an edge share a key).
        c = subedge.edge.prevertex.subvertices.index(subedge.presubvertex)
        return (subedge.edge.keyspace.routing_key(c=c),
                subedge.edge.keyspace.routing_mask)


def retrieve_region_data(txrx, x, y, p, region_id, region_size):
    """Get the data from the given processor and region.

    :param txrx: transceiver to use when communicating with the board
    :param region_id: id of the region to retrieve
    :param region_size: size of the region (in words)
    :returns: a string containing data from the region
    """
    # Get the application pointer table to get the address for the region
    txrx.select(x, y)
    app_data_base_offset = memory_utils.getAppDataBaseAddressOffset(p)
    _app_data_table = txrx.memory_calls.read_mem(app_data_base_offset,
                                                 scamp.TYPE_WORD, 4)
    app_data_table = struct.unpack('<I', _app_data_table)[0]

    # Get the position of the desired region
    region_base_offset = memory_utils.getRegionBaseAddressOffset(
        app_data_table, region_id)
    _region_base = txrx.memory_calls.read_mem(region_base_offset,
                                              scamp.TYPE_WORD, 4)
    region_address = struct.unpack('<I', _region_base)[0] + app_data_table

    # Read the region
    data = txrx.memory_calls.read_mem(region_address, scamp.TYPE_WORD,
                                      region_size * 4)
    return data


def make_filter_regions(conns, dt):
    """Generate the filter and filter routing entries for the given connections

    :param connections_with_keys: List of tuples (connection, keyspace)
    :param dt: Timestep of the simulation
    :returns: The filter region and the filter routing region
    """
    # Generate the set of unique filters, fill in the values for this region
    filter_assigns = connections.Filters(set([c for c in conns]))

    filters = [len(filter_assigns.filters)]
    for f in filter_assigns.filters:
        fv = fp.bitsk(np.exp(-dt / f.time_constant) if
                      f.time_constant is not None else 0.)
        fv_ = fp.bitsk(1. - np.exp(-dt / f.time_constant) if
                       f.time_constant is not None else 1.)
        filters.append(fv)
        filters.append(fv_)
        filters.append(0x0 if f.is_accumulatory else 0xffffffff)
        filters.append(f.width)

    # Generate the routing entries
    filter_routes = [len(conns)]
    for c in conns:
        assert getattr(c, 'keyspace', None) is not None
        filter_routes.append(c.keyspace.filter_key())
        filter_routes.append(c.keyspace.filter_mask)
        filter_routes.append(filter_assigns[c])
        filter_routes.append(c.keyspace.mask_d)

    # Make the regions and return
    return (UnpartitionedListRegion(filters),
            UnpartitionedListRegion(filter_routes),
            filter_assigns)


class _MatrixRegion(object):
    def __init__(self, matrix=None, shape=None, in_dtcm=True, unfilled=False,
                 prepend_length=False, formatter=None):
        """Create a new MatrixRegion.

        :param matrix: Matrix to represent in this region.
        :param shape: Shape of the matrix, will be taken from the passed matrix
                      if not supplied.
        :param in_dtcm: Whether the region is copied into DTCM
        :param unfilled: Whether the region has data written to it or otherwise
        :param prepend_length: Include the length of the array as the first
                               element.
        :param formatter: Function to apply to each value before writing.
        """
        # Assert that the matrix matches the given shape
        if matrix is not None:
            if shape is not None and shape != matrix.shape:
                raise ValueError
            if shape is None:
                shape = matrix.shape

        # Store the matrix and the shape, and various options
        self.matrix = matrix
        self.shape = shape
        self.in_dtcm = in_dtcm
        self.unfilled = unfilled
        self.prepend_length = prepend_length
        self.formatter = formatter

    def write_out(self, lo_atom, hi_atom, spec):
        """Write the given region to the spec file.

        :param lo_atom: Index of the first row/column to write.
        :param hi_atom: Index of the last row/column to write.
        :param spec: The spec file to write the array to.
        """
        # Get the limited version of the array, flatten and write
        data = self[lo_atom:hi_atom+1]
        flat_data = data.reshape(data.size)

        # Format the data if required
        if self.formatter is None:
            formatted_data = np.array(flat_data, dtype=np.uint32)
        else:
            formatted_data = np.array(self.formatter(flat_data.tolist()),
                                      dtype=np.uint32)

        # Add the length as the first word if desired
        if self.prepend_length:
            final_data = np.array(np.hstack([[data.size], formatted_data]),
                                  dtype=np.uint32)
        else:
            final_data = formatted_data

        # Write to the provided spec
        spec.write_array(final_data)

    def sizeof(self, lo_atom, hi_atom):
        """Return the size (in cells -- assumed to be words) of the data
        contained in the block indexed by lo_atom to hi_atom.
        """
        return self[lo_atom:hi_atom+1].size + (1 if self.prepend_length else 0)


class MatrixRegionPartitionedByColumns(_MatrixRegion):
    """A region representing a matrix which is partitioned by columns.
    """
    def __getitem__(self, index):
        return self.matrix.T[index].T


class MatrixRegionPartitionedByRows(_MatrixRegion):
    """A region representing a matrix which is partitioned by rows.
    """
    def __getitem__(self, index):
        return self.matrix[index]


class UnpartitionedListRegion(object):
    """A region representing non-homogeneous data which won't be partitioned.
    """
    def __init__(self, data=None, prepend_length=False, size=None,
                 in_dtcm=True, unfilled=False, n_atoms_index=None,
                 dtype='uint32'):
        if data is None:
            size = 0
        if data is not None and size is None:
            size = len(data)

        self.data = data
        self.dtype = dtype
        self.size = size
        self.in_dtcm = in_dtcm
        self.unfilled = unfilled
        self.prepend_length = prepend_length
        self.n_atoms_index = n_atoms_index

    def sizeof(self, lo_atom, hi_atom):
        return self.size + (1 if self.prepend_length else 0)

    def write_out(self, lo_atom, hi_atom, spec):
        if self.prepend_length:
            spec.write(data=self.size)

        for i, data in enumerate(self.data):
            if self.n_atoms_index is not None and self.n_atoms_index == i:
                spec.write(data=hi_atom-lo_atom+1, sizeof=self.dtype)
            else:
                spec.write(data=data, sizeof=self.dtype)


class BitfieldBasedRecordingRegion(object):
    """A region representing a recorded region.
    """
    def __init__(self, n_ticks):
        self.n_ticks = n_ticks
        self.in_dtcm = False
        self.unfilled = True

    def sizeof(self, lo_atom, hi_atom):
        n_atoms = hi_atom - lo_atom + 1
        frame_size = (n_atoms >> 5) + (1 if n_atoms & 0x1f else 0)
        return frame_size * self.n_ticks


class FrameBasedRecordingRegion(object):
    in_dtcm = False
    unfilled = True

    def __init__(self, width, n_ticks):
        self.size = width*n_ticks

    def sizeof(self, lo_atom, hi_atom):
        return self.size


class UnpartitionedMatrixRegion(object):
    def __init__(self, matrix=None, shape=None, in_dtcm=True, unfilled=False,
                 prepend_length=False, formatter=None):
        """Create a new MatrixRegion.

        :param matrix: Matrix to represent in this region.
        :param shape: Shape of the matrix, will be taken from the passed matrix
                      if not supplied.
        :param in_dtcm: Whether the region is copied into DTCM
        :param unfilled: Whether the region has data written to it or otherwise
        :param prepend_length: Include the length of the array as the first
                               element.
        :param formatter: Function to apply to each value before writing.
        """
        # Assert that the matrix matches the given shape
        if matrix is not None:
            if shape is not None and shape != matrix.shape:
                raise ValueError
            if shape is None:
                shape = matrix.shape

        # Store the matrix and the shape, and various options
        self.matrix = matrix
        self.shape = shape
        self.in_dtcm = in_dtcm
        self.unfilled = unfilled
        self.prepend_length = prepend_length
        self.formatter = formatter

    def sizeof(self, lo_atom, hi_atom):
        return self.shape[0] * self.shape[1]

    def write_out(self, lo_atom, hi_atom, spec):
        """Write the given region to the spec file.

        :param lo_atom: Index of the first row/column to write.
        :param hi_atom: Index of the last row/column to write.
        :param spec: The spec file to write the array to.
        """
        # Get the limited version of the array, flatten and write
        data = self.matrix
        flat_data = data.reshape(data.size)

        # Format the data if required
        if self.formatter is None:
            formatted_data = np.array(flat_data, dtype=np.uint32)
        else:
            formatted_data = np.vectorize(self.formatter)(flat_data).astype(
                np.uint32)

        # Add the length as the first word if desired
        if self.prepend_length:
            final_data = np.array(np.hstack([[data.size], formatted_data]),
                                  dtype=np.uint32)
        else:
            final_data = formatted_data

        # Write to the provided spec
        spec.write_array(final_data)


class UnpartitionedKeysRegion(object):
    in_dtcm = True
    unfilled = False

    def __init__(self, keyspaces):
        self.keyspaces = keyspaces

    def sizeof(self, lo_atom, hi_atom):
        return len(self.keyspaces)

    def write_out(self, lo_atom, hi_atom, index, spec):
        for ks in self.keyspaces:
            spec.write(data=ks.key(c=index))
