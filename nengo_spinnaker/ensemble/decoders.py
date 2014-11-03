"""Tools for regularising the building and compression of decoders.
"""
import numpy as np


def get_compressed_decoder(decoder, threshold=0.):
    """Get a list of used dimensions and a compressed version of the decoder
    with zeroed columns removed.
    """
    # Used dimensions (columns where there is at least one non zero value)
    dims = np.where(np.any(np.abs(decoder) > threshold, axis=0))[0].tolist()

    # Compress the decoder (remove zeroed columns)
    cdec = (decoder.T[dims]).T

    return dims, cdec


def get_combined_compressed_decoders(decoders, indices=None, headers=None,
                                     threshold=0., compress=True):
    """Create a compressed decoder block, and return a list of tuples
    samples from headers, indices and dimension numbers.

    :param decoders: A list of decoders to compress.
    :param indices: A list of indices for the decoders.
    :param headers: A list of headers for the decoders (might be KeySpaces).
    :param threshold: Any columns containing a value greater than the threshold
                      will be retained.
    :param compress: A boolean or list of booleans describing whether to
                     compress or otherwise a decoders.
    :returns: A list of tuples of (header, index, dimension) and a combined
              compressed decoder block (NxD).
    """
    if isinstance(compress, bool):
        compress = [compress] * len(decoders)

    assert(indices is None or len(decoders) == len(indices))
    assert(headers is None or len(decoders) == len(headers))
    assert(len(compress) == len(decoders))
    assert(np.all(decoders[0].shape[0] == d.shape[0] for d in decoders))

    # Compress all of the decoders, with threshold -1. for those we don't want
    # to compress
    dimsdecs = [get_compressed_decoder(d, threshold if c else -1.) for
                (d, c) in zip(decoders, compress)]

    # Combine the final decoder
    if len(dimsdecs) > 0:
        decoder = np.hstack([d[1] for d in dimsdecs])
    else:
        decoder = np.array([])

    # Generate the header (header element, index and dimension)
    final_headers = list()
    dims = [d[0] for d in dimsdecs]

    if indices is None:
        indices = range(len(decoders))
    if headers is None:
        headers = [None]*len(decoders)

    for (h, i, ds) in zip(headers, indices, dims):
        final_headers.extend([(h, i, d) for d in ds])

    return final_headers, decoder
