import collections
import enum
import numpy as np


class Region(object):
    """Generic memory region object.

    :attr in_dtcm: Whether the region of memory is loaded into DTCM.
    :attr unfilled: Region is left unfilled.
    :attr prepend_length: Prepend the length of the region when writing out.
    """
    def __init__(self, in_dtcm=True, unfilled=False):
        """
        :param bool in_dtcm: Whether the region is stored in DTCM.
        :param bool unfilled: Whether the region is to be left unfilled.
        :param func formatter: Formatting function to apply to each element in
                               the array before writing out.
        """
        self.in_dtcm = in_dtcm
        self.unfilled = unfilled

    def sizeof(self, vertex_slice):
        """Get the size (in words) of the region."""
        raise NotImplementedError

    def create_subregion(self, vertex_slice, subvertex_index):
        """Create a smaller version of the region ready to write to memory.
        """
        raise NotImplementedError


Subregion_ = collections.namedtuple('Subregion', 'data size_words unfilled')


def Subregion(data, size_words, unfilled):
    if data is not None:
        assert data.dtype == np.uint32  # May want to revise this later
        d = np.copy(data)
        d.flags.writeable = False
        data = d.data
    return Subregion_(data, size_words, unfilled)


MatrixRegionPrepends = enum.Enum('MatrixRegionPrepends',
                                 'N_ATOMS N_ROWS N_COLUMNS SIZE INDEX')


class MatrixRegion(Region):
    """An unpartitioned region of memory representing a matrix.
    """
    partition_index = None  # Not partitioned along any axis

    def __init__(self, matrix=None, shape=None, dtype=np.uint32, in_dtcm=True,
                 unfilled=False, prepends=list(), formatter=None):
        """Create a new region representing a matrix.

        :param matrix: Matrix to represent in this region.
        :param shape: Shape of the matrix, will be taken from the passed matrix
                      if not specified.
        """
        super(MatrixRegion, self).__init__(in_dtcm=in_dtcm, unfilled=unfilled)
        self.prepends = prepends
        self.formatter = formatter

        # Assert the matrix matches the given shape
        assert shape is not None or matrix is not None

        if shape is not None and matrix is not None:
            assert shape == matrix.shape

        if shape is None and matrix is not None:
            shape = matrix.shape

        # Store the matrix and shape
        self.matrix = matrix
        self.shape = shape
        self.dtype = dtype

    def sizeof(self, vertex_slice):
        """Get the size of the region for the specified atoms in words."""
        return (self.size_from_shape(vertex_slice) + len(self.prepends))

    def __getitem__(self, index):
        return self.matrix

    def size_from_shape(self, vertex_slice):
        # If the shape is n-D then multiply the length of the axes together,
        # accounting for the clipping of the partitioned axis.
        if isinstance(self.shape, tuple):
            return reduce(
                lambda x, y: x*y,
                [s if i != self.partition_index else
                 (min(s, vertex_slice.stop) - max(0, vertex_slice.start)) for
                 i, s in enumerate(self.shape)])

        # Otherwise just clip
        return min(self.shape, vertex_slice.stop) - max(0, vertex_slice.start)

    def create_subregion(self, vertex_slice, subvertex_index):
        """Return the data to write to memory for this region.
        """
        # Get the data, flatten
        data = self[vertex_slice]
        flat_data = data.reshape(data.size)

        # Format the data as required
        if self.formatter is None:
            formatted_data = flat_data
        else:
            formatted_data = np.array(map(self.formatter, flat_data.tolist()),
                                      dtype=np.uint32)

        # Prepend any required additional data
        prepend_data = {
            MatrixRegionPrepends.N_ATOMS: (vertex_slice.stop -
                                           vertex_slice.start),
            MatrixRegionPrepends.N_ROWS: data.shape[0],
            MatrixRegionPrepends.N_COLUMNS: data.shape[1],
            MatrixRegionPrepends.SIZE: data.size,
            MatrixRegionPrepends.INDEX: subvertex_index,
        }
        prepends = np.array([prepend_data[p] for p in self.prepends],
                            dtype=self.dtype)

        srd = np.hstack([prepends, formatted_data])
        return Subregion(srd, len(srd), self.unfilled)


class MatrixRegionPartitionedByColumns(MatrixRegion):
    """A region representing a matrix which is partitioned by columns.
    """
    partition_index = 1

    def __getitem__(self, index):
        return self.matrix.T[index].T


class MatrixRegionPartitionedByRows(MatrixRegion):
    """A region representing a matrix which is partitioned by rows.
    """
    partition_index = 0

    def __getitem__(self, index):
        return self.matrix[index]


class KeysRegion(Region):
    """A region which represents a series of keys.

    A region which represents keys to be used in transmitting or receiving
    multicast packets.  If desired a field may be filled in with the subvertex
    index when a subregion is created.

    The region is not partitioned.
    """
    def __init__(self, keys, fill_in_field=None, extra_fields=list(),
                 in_dtcm=True, prepend_n_keys=False):
        super(KeysRegion, self).__init__(
            in_dtcm=in_dtcm, unfilled=False)
        self.prepend_n_keys = prepend_n_keys

        self.keys = keys

        if fill_in_field is None:
            self.fields = [lambda k, i: k.key()]
        else:
            self.fields = [lambda k, i: k.key(**{fill_in_field: i})]

        self.fields.extend(extra_fields)

    def sizeof(self, vertex_slice):
        """The size of the region in WORDS.
        """
        return (len(self.keys) * (len(self.fields)) +
                (1 if self.prepend_n_keys else 0))

    def create_subregion(self, vertex_slice, subvertex_index):
        # Create the data for each key
        data = []
        for k in self.keys:
            data.extend(f(k, subvertex_index) for f in self.fields)

        # Prepend any required additional data
        prepends = []
        if self.prepend_n_keys:
            prepends.append(len(self.keys))

        # Create the subregion and return
        srd = np.hstack([np.array(prepends, dtype=np.uint32),
                         np.array(data, dtype=np.uint32)])
        return Subregion(srd, len(srd), False)
