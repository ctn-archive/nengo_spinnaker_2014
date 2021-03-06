#include "filter.h"

filter_parameters_t g_filter;
uint delay_remaining;
input_filter_t g_input;

void filter_update(uint ticks, uint arg1) {
  use(arg1);
  if (simulation_ticks != UINT32_MAX && ticks >= simulation_ticks) {
    spin1_exit(0);
  }

  // Update the filters
  input_filter_step(&g_input, true);

  // Apply the transform to the input to get the output
  for (uint j = 0; j < g_filter.size_out; j++) {
    g_filter.output[j] = 0;

    for (uint k = 0; k < g_filter.size_in; k++) {
      g_filter.output[j] += g_filter.transform[j*g_filter.size_in + k] *
                            g_filter.input[k];
    }
  }

  // Increment the counter and transmit if necessary
  delay_remaining--;
  if(delay_remaining == 0) {
    delay_remaining = g_filter.transmission_delay;

    uint val = 0x0000;
    for(uint d = 0; d < g_filter.size_out; d++) {
      val = bitsk(g_filter.output[d]);
      spin1_send_mc_packet(g_filter.keys[d], val, WITH_PAYLOAD);
      spin1_delay_us(g_filter.interpacket_pause);
    }
  }
}

bool data_system(address_t addr) {
  g_filter.size_in = addr[0];
  g_filter.size_out = addr[1];
  g_filter.machine_timestep = addr[2];
  g_filter.transmission_delay = addr[3];
  g_filter.interpacket_pause = addr[4];

  delay_remaining = g_filter.transmission_delay;
  io_printf(IO_BUF, "[Filter] transmission delay = %d\n", delay_remaining);

  g_filter.input = input_filter_initialise(&g_input, g_filter.size_in);

  if (g_filter.input == NULL)
    return false;
  return true;
}

bool data_get_output_keys(address_t addr) {
  MALLOC_FAIL_FALSE(g_filter.keys,
                    g_filter.size_out * sizeof(uint));
  spin1_memcpy(
    g_filter.keys, addr, g_filter.size_out * sizeof(uint));

  for (uint i = 0; i < g_filter.size_out; i++)
    io_printf(IO_BUF, "g_filter.keys[%d] = %08x\n", i, g_filter.keys[i]);

  return true;
}

bool data_get_transform(address_t addr) {
  MALLOC_FAIL_FALSE(g_filter.transform,
                    sizeof(value_t) * g_filter.size_in * g_filter.size_out);

  spin1_memcpy(g_filter.transform, addr,
               g_filter.size_in * g_filter.size_out * sizeof(uint));

  io_printf(IO_BUF, "Transform = [");
  for (uint i = 0; i < g_filter.size_out; i++) {
    for (uint j = 0; j < g_filter.size_in; j++) {
      io_printf(IO_BUF, "%k ", g_filter.transform[i*g_filter.size_in + j]);
    }
    io_printf(IO_BUF, "\n");
  }
  io_printf(IO_BUF, "]\n");

  return true;
}

void mcpl_callback(uint key, uint payload) {
  input_filter_mcpl_rx(&g_input, key, payload);
}

void c_main(void) {
  address_t address = system_load_sram();
  if (!data_system(region_start(1, address)) ||
      !data_get_output_keys(region_start(2, address)) ||
      !input_filter_get_filters(&g_input, region_start(3, address)) ||
      !input_filter_get_filter_routes(&g_input, region_start(4, address)) ||
      !data_get_transform(region_start(5, address))
  ) {
    io_printf(IO_BUF, "[Filter] Failed to initialise.\n");
    return;
  }

  // Set up routing tables
  if(leadAp) {
    system_lead_app_configured();
  }

  // Setup timer tick, start
  spin1_set_timer_tick(g_filter.machine_timestep);
  spin1_callback_on(MCPL_PACKET_RECEIVED, mcpl_callback, -1);
  spin1_callback_on(TIMER_TICK, filter_update, 2);
  spin1_start(SYNC_WAIT);
}
