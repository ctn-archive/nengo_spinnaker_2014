/**
 * Ensemble - Data
 *
 * Authors:
 *   - Andrew Mundy <mundya@cs.man.ac.uk>
 *   - Terry Stewart
 * 
 * Copyright:
 *   - Advanced Processor Technologies, School of Computer Science,
 *      University of Manchester
 *   - Computational Neuroscience Research Group, Centre for
 *      Theoretical Neuroscience, University of Waterloo
 * 
 * \addtogroup ensemble
 * @{
 */

#include "ensemble.h"
#include "common-impl.h"

#ifndef __ENSEMBLE_DATA_H__
#define __ENSEMBLE_DATA_H__

/** \brief Representation of system region. See ::data_system. */
typedef struct region_system {
  uint n_input_dimensions;
  uint n_output_dimensions;
  uint n_neurons;
  uint machine_timestep;
  uint t_ref;
  value_t one_over_t_rc;
  value_t n_filters;
  value_t n_filter_keys;
} region_system_t;

/**
* \brief Copy in data pertaining to the system region of the Ensemble.
*
* We expect there to be 7 ```uint``` size pieces of information within the
* system region (region 1). These are:
*
* Description | Units | Type | Becomes
* ----------- | ----- | ---- | -------
* Number of input dimensions | | ```uint``` | ::n_input_dimensions
* Number of output dimensions | | ```uint``` | ::n_output_dimensions
* Number of neurons | | ```uint``` | ::n_neurons
* dt | Microseconds | ```uint``` | ::dt
* Refactory time constant | Steps of dt | ```uint``` | ::t_ref
* Inverse of membrane time constant | | ```accum``` | ::one_over_t_rc
* Number of filters | | ```uint``` |
* Number of filter keys | | ```uint``` |
*/
bool data_system( address_t addr );

bool data_get_bias(
  address_t addr,
  uint n_neurons
);

bool data_get_encoders(
  address_t addr,
  uint n_neurons,
  uint n_input_dimensions
);

bool data_get_decoders(
  address_t addr,
  uint n_neurons,
  uint n_output_dimensions
);

bool data_get_keys(
  address_t addr,
  uint n_output_dimensions
);

bool data_get_filters(
  address_t addr,
  region_system_t *pars
);

bool data_get_filter_keys(
  address_t addr,
  region_system_t *pars
);

#endif

/** @} */
