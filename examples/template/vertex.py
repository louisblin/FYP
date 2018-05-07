
from pacman.model.partitioned_graph.partitioned_vertex import PartitionedVertex
from pacman.model.resources.cpu_cycles_per_tick_resource import \
    CPUCyclesPerTickResource
from pacman.model.resources.dtcm_resource import DTCMResource
from pacman.model.resources.resource_container import ResourceContainer
from pacman.model.resources.sdram_resource import SDRAMResource

from spinn_front_end_common.abstract_models.\
    abstract_partitioned_data_specable_vertex import \
    AbstractPartitionedDataSpecableVertex
from spinn_front_end_common.interface.buffer_management.\
    buffer_models.receives_buffers_to_host_basic_impl import \
    ReceiveBuffersToHostBasicImpl

from spinn_front_end_common.utilities import constants

from data_specification.data_specification_generator import \
    DataSpecificationGenerator

from spinnaker_graph_front_end.utilities.conf import config

from enum import Enum

import logging

logger = logging.getLogger(__name__)


class Vertex(
        PartitionedVertex, AbstractPartitionedDataSpecableVertex,
        ReceiveBuffersToHostBasicImpl):

    # The number of bytes for the has_key flag and the key
    TRANSMISSION_REGION_N_BYTES = 2 * 4

    # TODO: Update with the regions of the application
    DATA_REGIONS = Enum(
        value="DATA_REGIONS",
        names=[('SYSTEM', 0),
               ('TRANSMISSION', 1),
               ('RECORDED_DATA', 2),
               ('BUFFERED_STATE', 3)])

    def __init__(self, label, machine_time_step, time_scale_factor,
                 constraints=None):

        self._recording_size = 5000

        # TODO: Update with the resources required by the vertex
        resources = ResourceContainer(
            cpu=CPUCyclesPerTickResource(45),
            dtcm=DTCMResource(100),
            sdram=SDRAMResource(
                (constants.DATA_SPECABLE_BASIC_SETUP_INFO_N_WORDS * 4) +
                self.TRANSMISSION_REGION_N_BYTES +
                self.get_buffer_state_region_size(1) +
                self.get_recording_data_size(1) + self._recording_size))

        PartitionedVertex.__init__(
            self, label=label, resources_required=resources,
            constraints=constraints)
        AbstractPartitionedDataSpecableVertex.__init__(
            self, machine_time_step, time_scale_factor)
        ReceiveBuffersToHostBasicImpl.__init__(self)

        self._buffer_size_before_receive = config.getint(
            "Buffers", "buffer_size_before_receive")

        self._time_between_requests = config.getint(
            "Buffers", "time_between_requests")

        self.placement = None

    def get_binary_file_name(self):
        return "c_code.aplx"

    def model_name(self):
        return "Vertex"

    def generate_data_spec(
            self, placement, sub_graph, routing_info, hostname, report_folder,
            ip_tags, reverse_ip_tags, write_text_specs,
            application_run_time_folder):
        """ Generate data

        :param placement: the placement object for the dsg
        :param sub_graph: the partitioned graph object for this dsg
        :param routing_info: the routing info object for this dsg
        :param hostname: the machines hostname
        :param ip_tags: the collection of iptags generated by the tag allocator
        :param reverse_ip_tags: the collection of reverse iptags generated by\
                the tag allocator
        :param report_folder: the folder to write reports to
        :param write_text_specs: bool which says if test specs should be\
                written
        :param application_run_time_folder: the folder where application files\
                are written
        """
        self.placement = placement

        data_writer, report_writer = \
            self.get_data_spec_file_writers(
                placement.x, placement.y, placement.p, hostname, report_folder,
                write_text_specs, application_run_time_folder)

        spec = DataSpecificationGenerator(data_writer, report_writer)

        # Create the data regions
        self._reserve_memory_regions(spec)
        self._write_basic_setup_info(spec, self.DATA_REGIONS.SYSTEM.value)
        self.write_recording_data(
            spec, ip_tags, [self._recording_size],
            self._buffer_size_before_receive, self._time_between_requests)

        # Get the key, assuming all outgoing edges use the same key
        key = 0
        has_key = 0
        edge_partitions = sub_graph.outgoing_edges_partitions_from_vertex(self)
        if len(edge_partitions) > 0:

            # Assumes all outgoing edges use the same key
            keys_and_masks = routing_info.get_keys_and_masks_from_partition(
                edge_partitions[0])
            key = keys_and_masks[0].key
            has_key = 1

        # Write the transmission region
        spec.switch_write_focus(self.DATA_REGIONS.TRANSMISSION.value)
        spec.write_value(has_key)
        spec.write_value(key)

        # End-of-Spec:
        spec.end_specification()
        data_writer.close()

        # return file path for dsg targets
        return data_writer.filename

    def _reserve_memory_regions(self, spec):
        spec.reserve_memory_region(
            region=self.DATA_REGIONS.SYSTEM.value,
            size=constants.DATA_SPECABLE_BASIC_SETUP_INFO_N_WORDS * 4,
            label='systemInfo')
        spec.reserve_memory_region(
            region=self.DATA_REGIONS.TRANSMISSION.value,
            seiz=self.TRANSMISSION_REGION_N_BYTES, label="transmission")
        self.reserve_buffer_regions(
            spec, self.DATA_REGIONS.BUFFERED_STATE.value,
            [self.DATA_REGIONS.RECORDED_DATA.value],
            [self._recording_size])

    def read(self, placement, buffer_manager):
        """ Get the recorded data

        :param placement: the location of this vertex
        :param buffer_manager: the buffer manager
        :return: The data read
        """
        data_pointer, is_missing_data = buffer_manager.get_data_for_vertex(
            placement, self.DATA_REGIONS.RECORDED_DATA.value,
            self.DATA_REGIONS.BUFFERED_STATE.value)
        if is_missing_data:
            logger.warn("Some data was lost when recording")
        record_raw = data_pointer.read_all()
        return record_raw

    def is_partitioned_data_specable(self):
        return True
