
from statistics import mode
from sai_test_base import T0TestBase
from multiprocessing import Process
from sai_thrift.sai_headers import *
from ptf import config
from ptf.testutils import *
from ptf.thriftutils import *
from sai_utils import *
import pdb
from ptf import mask, testutils
from ptf.packet import IP


class BufferStatistics(T0TestBase):
    """
    Test buffer pool and ingress priority group statictics.
    To observe the proper counting of buffer statistics,
    it is recommended to run the test on hardware.
    """

    def setUp(self):
        super().setUp(is_create_fdb=False)

        self.tx_cnt = 10000
        self.pkt_len = 700
        # this value will impact SAI_INGRESS_PRIORITY_GROUP_STAT_CURR_OCCUPANCY_BYTES
        # and SAI_INGRESS_PRIORITY_GROUP_STAT_WATERMARK_BYTES = reserved_buf_size X 2
        self.reserved_buf_size = 5120
        self.xoff_size = 1280000
        self.buf_size = 25600000

        self.xon_th = 1024
        # SAI_INGRESS_PRIORITY_GROUP_STAT_XOFF_ROOM_CURR_OCCUPANCY_BYTES
        self.xoff_th = 2048
        self.xon_offset_th = 4096
        self.sleep_time = 2
        self.pkts = []
        pkt = simple_tcp_packet(eth_dst=ROUTER_MAC, eth_src=self.servers[1][0].mac,  ip_dst=self.servers[11][0].ipv4, ip_src=self.servers[1][0].ipv4, ip_id=105, ip_ttl=64)
        exp_pkt = simple_tcp_packet(eth_dst=self.t1_list[1][100].mac, eth_src=ROUTER_MAC,  ip_dst=self.servers[11][0].ipv4, ip_src=self.servers[1][0].ipv4, ip_id=105, ip_ttl=64)
        self.exp_pkt = mask.Mask(exp_pkt)
        self.exp_pkt.set_do_not_care_scapy(IP, "ihl")
        self.exp_pkt.set_do_not_care_scapy(IP, "tos")
        self.exp_pkt.set_do_not_care_scapy(IP, "len")
        self.exp_pkt.set_do_not_care_scapy(IP, "flags")
        self.exp_pkt.set_do_not_care_scapy(IP, "frag")
        self.exp_pkt.set_do_not_care_scapy(IP, "ttl")
        self.exp_pkt.set_do_not_care_scapy(IP, "proto")
        self.exp_pkt.set_do_not_care_scapy(IP, "chksum")

        self.dataplane.flush()
        send_packet(self, self.dut.port_obj_list[1].dev_port_index, pkt)
        verify_packet(self, pkt=self.exp_pkt, port_id=self.dut.port_obj_list[17].dev_port_index)

        for i in range(8):
            self.pkt = simple_udp_packet(eth_dst=ROUTER_MAC, eth_src=self.servers[1][0].mac,  ip_dst=self.servers[11][0].ipv4, ip_src=self.servers[1][0].ipv4, ip_id=105, ip_ttl=64,
                pktlen=self.pkt_len - 4, ip_dscp=i)  # account for 4B FCS
            self.pkts.append(self.pkt)
        #|c|SAI_OBJECT_TYPE_BUFFER_POOL:oid:0x180000000009f2|SAI_BUFFER_POOL_ATTR_THRESHOLD_MODE=SAI_BUFFER_POOL_THRESHOLD_MODE_DYNAMIC|SAI_BUFFER_POOL_ATTR_SIZE=32689152|SAI_BUFFER_POOL_ATTR_TYPE=SAI_BUFFER_POOL_TYPE_INGRESS|SAI_BUFFER_POOL_ATTR_XOFF_SIZE=2058240


        self.ingr_pool = sai_thrift_create_buffer_pool(
            self.client, type=SAI_BUFFER_POOL_TYPE_INGRESS, size=self.buf_size, threshold_mode=SAI_BUFFER_POOL_THRESHOLD_MODE_DYNAMIC, xoff_size=self.xoff_size)
        self.assertGreater(self.ingr_pool, 0)
        #|c|SAI_OBJECT_TYPE_BUFFER_POOL:oid:0x180000000009f1|SAI_BUFFER_POOL_ATTR_THRESHOLD_MODE=SAI_BUFFER_POOL_THRESHOLD_MODE_DYNAMIC|SAI_BUFFER_POOL_ATTR_SIZE=24192256|SAI_BUFFER_POOL_ATTR_TYPE=SAI_BUFFER_POOL_TYPE_EGRESS
        self.egr_pool = sai_thrift_create_buffer_pool(
            self.client, type=SAI_BUFFER_POOL_TYPE_EGRESS, size=self.buf_size, threshold_mode=SAI_BUFFER_POOL_THRESHOLD_MODE_DYNAMIC, xoff_size=self.xoff_size)
        self.assertGreater(self.ingr_pool, 0)

        #|c|SAI_OBJECT_TYPE_BUFFER_PROFILE:oid:0x190000000009f6|SAI_BUFFER_PROFILE_ATTR_POOL_ID=oid:0x180000000009f2|SAI_BUFFER_PROFILE_ATTR_XON_TH=4608|SAI_BUFFER_PROFILE_ATTR_XON_OFFSET_TH=4608|SAI_BUFFER_PROFILE_ATTR_XOFF_TH=60416|SAI_BUFFER_PROFILE_ATTR_RESERVED_BUFFER_SIZE=4608|SAI_BUFFER_PROFILE_ATTR_THRESHOLD_MODE=SAI_BUFFER_PROFILE_THRESHOLD_MODE_DYNAMIC|SAI_BUFFER_PROFILE_ATTR_SHARED_DYNAMIC_TH=-3
        self.buffer_profile = sai_thrift_create_buffer_profile(
            self.client, pool_id=self.ingr_pool,
            xon_th=self.xon_th,
            xon_offset_th=self.xon_offset_th,
            xoff_th=self.xoff_th,
            reserved_buffer_size=self.reserved_buf_size,
            threshold_mode=SAI_BUFFER_PROFILE_THRESHOLD_MODE_DYNAMIC,
            shared_dynamic_th=-3)
        #|c|SAI_OBJECT_TYPE_BUFFER_PROFILE:oid:0x190000000009f4|SAI_BUFFER_PROFILE_ATTR_THRESHOLD_MODE=SAI_BUFFER_PROFILE_THRESHOLD_MODE_DYNAMIC|SAI_BUFFER_PROFILE_ATTR_SHARED_DYNAMIC_TH=-1|SAI_BUFFER_PROFILE_ATTR_POOL_ID=oid:0x180000000009f1|SAI_BUFFER_PROFILE_ATTR_RESERVED_BUFFER_SIZE=1792
        self.ebuffer_profile = sai_thrift_create_buffer_profile(
            self.client, pool_id=self.egr_pool,
            reserved_buffer_size=self.reserved_buf_size,
            threshold_mode=SAI_BUFFER_PROFILE_THRESHOLD_MODE_DYNAMIC,
            shared_dynamic_th=-1)
        self.assertGreater(self.buffer_profile, 0)

        sw_attrs = sai_thrift_get_switch_attribute(
            self.client, ingress_buffer_pool_num=True,
            egress_buffer_pool_num=True,
            total_buffer_size=True)
        

        pg_list = sai_thrift_object_list_t(count=100)
        ipg_list = sai_thrift_get_port_attribute(self.client, port_oid=self.dut.port_obj_list[1].oid, ingress_priority_group_list=pg_list)
        self.ipg_list = ipg_list['ingress_priority_group_list'].idlist
        self.ipgs = []

        q_list = sai_thrift_object_list_t(count=100)
        q_list = sai_thrift_get_port_attribute(self.client, port_oid=self.dut.port_obj_list[17].oid, qos_queue_list=q_list)
        self.q_list = q_list['qos_queue_list'].idlist
        self.qs = []

        index=0
        for ipg in self.ipg_list:
            # self.ipg = sai_thrift_create_ingress_priority_group(
            #     self.client, port=self.dut.port_obj_list[1].oid, index=self.ipg_idx,
            #     buffer_profile=self.buffer_profile)
            
            self.assertGreater(ipg, 0)
            status = sai_thrift_set_ingress_priority_group_attribute(self.client, ingress_priority_group_oid=ipg, buffer_profile=self.buffer_profile)
            self.assertEqual(status, SAI_STATUS_SUCCESS)
            print("Assign profile for PG index:{} oid:{}".format(index, ipg))
            self.ipgs.append(ipg)
            index = index + 1

        for q in self.q_list:
            # self.ipg = sai_thrift_create_ingress_priority_group(
            #     self.client, port=self.dut.port_obj_list[1].oid, index=self.ipg_idx,
            #     buffer_profile=self.buffer_profile)
            
            self.assertGreater(q, 0)
            status = sai_thrift_set_queue_attribute(self.client, queue_oid=q, buffer_profile_id=self.ebuffer_profile)
            self.assertEqual(status, SAI_STATUS_SUCCESS)
            print("Assign profile for Queue index:{} oid:{}".format(index, q))
            self.qs.append(q)
            index = index + 1

        # Configure QoS maps.
        dscp_to_tc = []
        tc_to_ipg = []
        prio_to_ipg = []
        tc_to_q = []

        for i in range(8):
            dscp_to_tc.append(
                sai_thrift_qos_map_t(
                    key=sai_thrift_qos_map_params_t(color=SAI_PACKET_COLOR_GREEN, dot1p=0, dscp=i, mpls_exp=0, pg=0, prio=0, queue_index=0, tc=0),
                    value=sai_thrift_qos_map_params_t(color=SAI_PACKET_COLOR_GREEN, dot1p=0, dscp=0, mpls_exp=0, pg=0, prio=0, queue_index=0, tc=i)))

        for i in range(8):
            tc_to_ipg.append(
                sai_thrift_qos_map_t(
                    key=sai_thrift_qos_map_params_t(color=SAI_PACKET_COLOR_GREEN, dot1p=0, dscp=0, mpls_exp=0, pg=0, prio=0, queue_index=0, tc=i),
                    value=sai_thrift_qos_map_params_t(color=SAI_PACKET_COLOR_GREEN, dot1p=0, dscp=0, mpls_exp=0, pg=i, prio=0, queue_index=0, tc=0)))

            # prio_to_ipg.append(
            #     sai_thrift_qos_map_t(
            #         key=sai_thrift_qos_map_params_t(prio=i),
            #         value=sai_thrift_qos_map_params_t(pg=i)))

        for i in range(8):
            tc_to_q.append(
                sai_thrift_qos_map_t(
                    key=sai_thrift_qos_map_params_t(color=SAI_PACKET_COLOR_GREEN, dot1p=0, dscp=0, mpls_exp=0, pg=0, prio=0, queue_index=0, tc=i),
                    value=sai_thrift_qos_map_params_t(color=SAI_PACKET_COLOR_GREEN, dot1p=0, dscp=0, mpls_exp=0, pg=0, prio=0, queue_index=i, tc=0)))

        # prio_to_pg = sai_thrift_qos_map_t(
        #     key=sai_thrift_qos_map_params_t(prio=0),
        #     value=sai_thrift_qos_map_params_t(pg=self.ipg_idx))

        # qos_map_list = sai_thrift_qos_map_list_t(maplist=[prio_to_pg], count=1)

        print("Create DSCP to TC map")
        qos_map_list = sai_thrift_qos_map_list_t(
            maplist=dscp_to_tc, count=len(dscp_to_tc))

        self.dscp_to_tc_map = sai_thrift_create_qos_map(
            self.client, type=SAI_QOS_MAP_TYPE_DSCP_TO_TC,
            map_to_value_list=qos_map_list)
        self.assertGreater(self.dscp_to_tc_map, 0)

        status = sai_thrift_set_port_attribute(
            self.client, self.dut.port_obj_list[1].oid, qos_dscp_to_tc_map=self.dscp_to_tc_map)
        self.assertEqual(status, SAI_STATUS_SUCCESS)

        print("Create TC to iCoS map")
        qos_map_list = sai_thrift_qos_map_list_t(
            maplist=tc_to_ipg, count=len(tc_to_ipg))

        self.tc_to_ipg_map = sai_thrift_create_qos_map(
            self.client, type=SAI_QOS_MAP_TYPE_TC_TO_PRIORITY_GROUP,
            map_to_value_list=qos_map_list)
        self.assertGreater(self.tc_to_ipg_map, 0)

        status = sai_thrift_set_port_attribute(
            self.client, self.dut.port_obj_list[1].oid,
            qos_tc_to_priority_group_map=self.tc_to_ipg_map)
        self.assertEqual(status, SAI_STATUS_SUCCESS)

        #set all the port as lossless port by enable the FLOW_CONTROL as mention in broadcom doc
        #those attribute relate to the pfc_enable in PORT_QOS_MAP
        # the rule is, pfc_enable is 3,4, then we use the SAI_PORT_ATTR_PRIORITY_FLOW_CONTROL as 24 11000
        # if the pfc_enable is 2,3,4,6, then we use SAI_PORT_ATTR_PRIORITY_FLOW_CONTROL as 92 1011100
        # there we enable all the PG as lossless
        # the range is -128 <= number <= 127
        print("Set all PGs as lossless")
        status = sai_thrift_set_port_attribute(
            self.client, self.dut.port_obj_list[1].oid,
            priority_flow_control=127)
        self.assertEqual(status, SAI_STATUS_SUCCESS)
        # status = sai_thrift_set_port_attribute(
        #     self.client, self.dut.port_obj_list[1].oid,
        #     priority_flow_control_tx=-127)
        # self.assertEqual(status, SAI_STATUS_SUCCESS)
        # status = sai_thrift_set_port_attribute(
        #     self.client, self.dut.port_obj_list[1].oid,
        #     priority_flow_control_rx=-127)
        # self.assertEqual(status, SAI_STATUS_SUCCESS)

        print("Create DSCP to TC map")
        qos_map_list = sai_thrift_qos_map_list_t(
            maplist=dscp_to_tc, count=len(dscp_to_tc))

        self.dscp_to_tc_map = sai_thrift_create_qos_map(
            self.client, type=SAI_QOS_MAP_TYPE_DSCP_TO_TC,
            map_to_value_list=qos_map_list)
        self.assertGreater(self.dscp_to_tc_map, 0)

        status = sai_thrift_set_port_attribute(
            self.client, self.dut.port_obj_list[17].oid, qos_dscp_to_tc_map=self.dscp_to_tc_map)
        self.assertEqual(status, SAI_STATUS_SUCCESS)

        print("Create TC to queue map")
        qos_map_list = sai_thrift_qos_map_list_t(
            maplist=tc_to_q, count=len(tc_to_q))

        self.tc_to_q_map = sai_thrift_create_qos_map(
            self.client, type=SAI_QOS_MAP_TYPE_TC_TO_QUEUE,
            map_to_value_list=qos_map_list)
        self.assertGreater(self.tc_to_q_map, 0)

        status = sai_thrift_set_port_attribute(
            self.client, self.dut.port_obj_list[17].oid, qos_tc_to_queue_map=self.tc_to_q_map)
        self.assertEqual(status, SAI_STATUS_SUCCESS)        
        print("OK")

        print("Disable port tx")
        self.dataplane.flush()
        send_packet(self, self.dut.port_obj_list[1].dev_port_index, self.pkts[2])
        result = dp_poll(self, timeout=1)
        status = sai_thrift_set_port_attribute(self.client, self.dut.port_obj_list[result.port].oid, pkt_tx_enable=False)
        self.assertEqual(status, SAI_STATUS_SUCCESS)

        self.dataplane.flush()
        send_packet(self, self.dut.port_obj_list[1].dev_port_index, self.pkts[2])
        #result = Ether(dp_poll(self, timeout=1).packet)
        verify_no_packet(self, pkt=self.exp_pkt, port_id=self.dut.port_obj_list[result.port].dev_port_index)

        # self.qos_map = sai_thrift_create_qos_map(
        #     self.client, type=SAI_QOS_MAP_TYPE_PFC_PRIORITY_TO_PRIORITY_GROUP,
        #     map_to_value_list=qos_map_list)
        # self.assertGreater(self.qos_map, 0)

        # status = sai_thrift_set_port_attribute(
        #     self.client, self.dut.port_obj_list[1].oid,
        #     qos_pfc_priority_to_priority_group_map=self.qos_map)
        # self.assertEqual(status, SAI_STATUS_SUCCESS)

    def sendTraffic(self):
        """
        Send traffic.
        """
        print()
        print("Send {} pkts, pkt size: {} B".format(self.tx_cnt, self.pkt_len))
        for _ in range(self.tx_cnt):
            send_packet(self, self.dut.port_obj_list[1].dev_port_index, self.pkts[2])
        print()

    def sendVerify(self, expected_drops, verify_reserved_buffer_size):
        """
        Send traffic in parallel while polling for current occupancy stats.
        Once traffic is sent verifies other stats.

        Args:
            expected_drops (int): Number of expected dropped packets.
            verify_reserved_buffer_size (bool): Whether to verify
                SAI_BUFFER_PROFILE_ATTR_RESERVED_BUFFER_SIZE.
        """

        traffic = Process(target=self.sendTraffic)

        traffic.start()
        interval_bp_counter = {}
        internal_pg_counter = {}

        
        print("checking stat during sending packet")
        while traffic.is_alive():
            stats = query_counter(self, sai_thrift_get_buffer_pool_stats, self.ingr_pool)
            for counter  in sai_get_buffer_pool_stats_counter_ids_dict.values():
                if not counter in interval_bp_counter:
                    interval_bp_counter[counter] = 0                                
                if (stats[counter]> interval_bp_counter[counter]):
                    interval_bp_counter[counter] = stats[counter]
            index = 0
            for ipg in self.ipgs:
                stats = query_counter(self, sai_thrift_get_ingress_priority_group_stats, ipg)
                for counter  in sai_get_ingress_priority_group_stats_counter_ids_dict.values():
                    if not counter in internal_pg_counter:
                        internal_pg_counter[counter] = 0                              
                    if stats[counter] > internal_pg_counter[counter]:
                        internal_pg_counter[counter] = stats[counter]
                        print("pg index: {} key: {} value: {} ".format(index, counter, internal_pg_counter[counter]))
                index = index + 1             

        traffic.join()

        time.sleep(self.sleep_time)
        print("Send packet finished.")
        bp_counter = {}

        print("Ckeck all the buffer_pool_stats")
        stats = query_counter(self, sai_thrift_get_buffer_pool_stats, self.ingr_pool)
        for counter in sai_get_buffer_pool_stats_counter_ids_dict.values():
            if not counter in bp_counter:
                bp_counter[counter] = 0          
            if (stats[counter]> bp_counter[counter]):
                bp_counter[counter] = stats[counter]
                print(counter, bp_counter[counter])                

        if verify_reserved_buffer_size:
            expected_watermark = self.reserved_buf_size
        else:
            expected_watermark = self.pkt_len

        #self.assertGreater(bp_counter["SAI_BUFFER_POOL_STAT_CURR_OCCUPANCY_BYTES"], 0)
        self.assertGreaterEqual(
            bp_counter["SAI_BUFFER_POOL_STAT_WATERMARK_BYTES"], expected_watermark)

        #accross all the pgs
        print("Ckeck all the port_stats")
        index = 0
        port_counter = {}
        port_index = 1
        stats = query_counter(self, sai_thrift_get_port_stats, port_oid=self.dut.port_obj_list[1].oid)
        for counter in sai_get_port_stats_counter_ids_dict.values():
            if not counter in port_counter:
                port_counter[counter] = 0
            if (stats[counter]> port_counter[counter]):
                port_counter[counter] = stats[counter]
                print("port index: {} key: {} value: {} ".format(port_index, counter, port_counter[counter]))

        pg_counter = {}
        
        print("Ckeck all the ingress_priority_group_stats")
        for ipg in self.ipgs:
            stats = query_counter(self, sai_thrift_get_ingress_priority_group_stats, ipg)
            for counter in sai_get_ingress_priority_group_stats_counter_ids_dict.values():
                if not counter in pg_counter:
                    pg_counter[counter] = 0
                if (stats[counter]> pg_counter[counter]):
                    pg_counter[counter] = stats[counter]
                    print("pg index: {} key: {} value: {} ".format(index, counter, pg_counter[counter]))
            index = index + 1

        index = 0
        # for q in self.qs:
        #     stats = sai_thrift_get_queue_stats(self.client, q, counter_ids=counter_ids)
        #     for key in stats:
        #         print("Queue index: {} key:{} value:{} ".format(index, key, stats[key]))
        #     index = index + 1

        # pdb.set_trace()

        #self.assertGreater(internal_pg_counter["SAI_INGRESS_PRIORITY_GROUP_STAT_CURR_OCCUPANCY_BYTES"], 0)
        #self.assertGreater(internal_pg_counter["SAI_INGRESS_PRIORITY_GROUP_STAT_SHARED_CURR_OCCUPANCY_BYTES"], 0)
        # self.assertGreaterEqual(
        #     pg_counter["SAI_INGRESS_PRIORITY_GROUP_STAT_WATERMARK_BYTES"],
        #     expected_watermark)
        self.assertEqual(
            pg_counter["SAI_INGRESS_PRIORITY_GROUP_STAT_PACKETS"], self.tx_cnt)
        self.assertEqual(
            pg_counter["SAI_INGRESS_PRIORITY_GROUP_STAT_BYTES"],
            self.tx_cnt * self.pkt_len)
        self.assertEqual(
            pg_counter["SAI_INGRESS_PRIORITY_GROUP_STAT_DROPPED_PACKETS"],
            expected_drops)

    def clearVerify(self):
        """
        Clear bufer pool and ingress priority group stats.
        Verify they are cleared.
        """
        print()
        print("Clear bufer pool and ingress priority group stats")
        stats = clear_counter(self, sai_thrift_clear_buffer_pool_stats, self.ingr_pool)
        
        for ipg in self.ipgs:
            stats = clear_counter(self, sai_thrift_clear_ingress_priority_group_stats, ipg)

        print("Get stats and verify they are cleared")
        print("Get buffer_pool_stats after cleared")
        bp_counter = {}
        stats = query_counter(self, sai_thrift_get_buffer_pool_stats, self.ingr_pool)
        for counter in sai_get_buffer_pool_stats_counter_ids_dict.values():
            if not counter in bp_counter:
                bp_counter[counter] = 0
            if stats[counter] > bp_counter[counter]:
                bp_counter[counter] = stats[counter]
                print(counter, bp_counter[counter])

        print("Get ingress_priority_group_stats after cleared")
        pg_counter = {}
        index = 0
        for ipg in self.ipgs:
            stats = query_counter(self, sai_thrift_get_ingress_priority_group_stats, ipg)
            for counter in sai_get_ingress_priority_group_stats_counter_ids_dict.values():
                if not counter in pg_counter:
                    pg_counter[counter] = 0
                if stats[counter] > pg_counter[counter]:
                    pg_counter[counter] = stats[counter]
                    print("pg index: {} key: {} value: {} ".format(index, counter, pg_counter[counter]))
            index = index + 1

        print("Clear Port Counter")
        port_counter_ids = [SAI_PORT_STAT_IN_DROPPED_PKTS,
                            SAI_PORT_STAT_OUT_DROPPED_PKTS]
        port_counter = {}
        port_index = 1
        stats = clear_counter(self, sai_thrift_clear_port_stats, port_oid=self.dut.port_obj_list[port_index].oid)

        print("Check Port counter cleared.")
        
        stats = query_counter(self, sai_thrift_get_port_stats, port_oid=self.dut.port_obj_list[1].oid)
        for counter in sai_get_port_stats_counter_ids_dict.values():
            if not counter in port_counter:
                port_counter[counter] = 0
            if stats[counter]> port_counter[counter]:
                port_counter[counter] = stats[counter]
                print("port index: {} key: {} value: {} ".format(port_index, counter, port_counter[counter]))

    def runTest(self):
        print()

        # Make sure test starts with cleared counters.
        self.clearVerify()

        print("Buffer pool size:", self.buf_size)
        print("Buffer profile reserved_buffer_size:", self.reserved_buf_size)
        print("Buffer profile shared_static_th:", self.reserved_buf_size)

        self.sendVerify(expected_drops=0, verify_reserved_buffer_size=False)
        self.clearVerify()

        self.pkt = simple_udp_packet(
            pktlen=self.pkt_len - 4)  # account for 4B FCS

        print()
        print("Send pkts ({} B) larger than reserved buffer ({} B)".format(
            self.pkt_len, self.reserved_buf_size))
        self.sendVerify(
            expected_drops=0, verify_reserved_buffer_size=True)
        self.clearVerify()

    def tearDown(self):
        pass
        # sai_thrift_set_port_attribute(
        #     self.client, self.port0, qos_pfc_priority_to_priority_group_map=0)
        # sai_thrift_remove_qos_map(self.client, self.qos_map)
        # sai_thrift_remove_ingress_priority_group(self.client, self.ipg)
        # sai_thrift_remove_buffer_profile(self.client, self.buffer_profile)
        # sai_thrift_remove_buffer_pool(self.client, self.ingr_pool)

        # super(BufferStatistics, self).tearDown()

