from hamcrest import (
    assert_that,
    contains_string,
    equal_to,
    has_length,
    starts_with
)
from unittest import TestCase

from poc_gen import Pcap

from pathlib import Path
from scapy.all import raw, rdpcap, IP, UDP

class EthernetFrame(object):
    """
    """
#    @sv()
    def __init__(self):
        """
        """
        pass

#    @sv(return_type=DataType.Bit)
    def hasMoreFrames(self):
        """
        """
        return True

                #raw_bytes = raw(packet)
class TestPcapFile(TestCase):
    """
    Open a pcap file and write all bytes one at a time to the FPGA
    As of now, any MAC and any IP address are read, only data on port
    8000 is filtered in.
    """
    def test_smoke(self):
        # GIVEN
        mac = "00:0a:35:18:3c:1f"
        ip = "10.0.1.14"
        dport = 8000
        pcap_file = "../tests/data/generated_2025_05_02.pcap"

        # WHEN
        pcap = Pcap(pcap_file=pcap_file,
                    mac=mac,
                    ip=ip,
                    dport=dport)

        # THEN
        assert_that(pcap.get_packet_count(), equal_to(1))


#        if Path(pcap_file).exists() is False:
#            print('ERROR')
#            error_msg = f"File {pcap_file} does not exist"
#            print(f'Pcap.__init__() -> {error_msg}\n')
#           raise Exception(error_msg)

        #self._pcap_file = pcap_file
        #self._mac = mac
        #self._ip = ip
        #self._dport = dport

#        self._packets = []
#        packets = rdpcap(pcap_file)
#        for packet in packets:
#            if packet[UDP].dport == dport:
#                self._packets.append(packet)

#class TestWatchList(TestCase):
#    def test_get_single_watchlist(self):
#        # GIVEN
#        config_toml = 'sim/bench_1.cfg'
#
#        # Construct/set up FilterBench
#        filter_bench = FilterBench(path_or_str=config_toml)
#        watchlist_words = []
#
#        # WHEN
#        watchlist_size = filter_bench.watchlist_get_size()
#        for i in range(watchlist_size):
#            watchlist_words.append(filter_bench.watchlist_get_item(i))
#
#        # THEN
#        assert_that(watchlist_size, equal_to(2))
#        assert_that(watchlist_words, has_length(2))
#        assert_that(watchlist_words[0], equal_to(0x4d53465420202020))
#        assert_that(watchlist_words[1], equal_to(0x4141504c20202020))
#
#        # Type
#        #  Time
#        #  AddOrder
#        #  OrderExecuted
#        #  OrderExecutedAtPriceSize
#        #  ReduceSize
#        #  ModifyOrder
#        #  DeleteOrder
#        #  Get.Everything
#        #  Get.All.Orders
#        #  Get.Top
#
#        # SerializeCommand
#        # [0] type
#        # side
#        # orderid
#        # quantity
#        # symbol
#        # price
#        # exe.qty
#        # can.qty
#        # rem.qty
#        # seconds
#        # nanoseconds
#        # [11] add
#        # [12] edit
#        # [13] remove

            #import scapy
            #import scapy.utils
            #print(f'scapy.utils.__file__: {scapy.utils.__file__}')
            #from scapy.compat import raw
            #from scapy.all import raw, rdpcap, IP, UDP
            #packets = scapy.utils.rdpcap(pcap_file)
            #for packet in packets:
                #print('Dumping packet')
                #breakpoint()
                #print(f'Dest MAC: {dir(packet)}')
                #print(f'raw(packet): {scapy.all.raw(packet)}')
             #packets = scapy.utils.rdpcap2()
