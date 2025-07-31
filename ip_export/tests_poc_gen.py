from hamcrest import (
    assert_that,
    contains_string,
    equal_to,
    has_length,
    starts_with
)
from unittest import TestCase

from poc_gen import EthernetFrame, Pcap

from pathlib import Path
from scapy.all import raw, rdpcap, IP, UDP

class TestPcapFile(TestCase):
    def setUp(self):
        self._mac = "00:0a:35:18:3c:1f"
        self._ip = "10.0.1.14"
        self._dport = 8000

    """
    Open a pcap file and write all bytes one at a time to the FPGA
    As of now, any MAC and any IP address are read, only data on port
    8000 is filtered in.
    """
    def test_smoke(self):
        # GIVEN
        pcap_file = "../tests/data/generated_2025_05_02.pcap"

        # WHEN
        pcap = Pcap(pcap_file=pcap_file,
                    mac=self._mac,
                    ip=self._ip,
                    dport=self._dport)

        # THEN
        assert_that(pcap.get_frame_count(), equal_to(1))

    def test_packet_data(self):
        # GIVEN
        pcap_file = "../tests/data/generated_2025_05_02.pcap"

        # WHEN
        pcap = Pcap(pcap_file=pcap_file,
                    mac=self._mac,
                    ip=self._ip,
                    dport=self._dport)
        eth_frame = EthernetFrame()
        pcap.get_frame(eth_frame, 0)

        # THEN
        assert_that(pcap.get_frame_count(), equal_to(1))
        assert_that(eth_frame.get_length_bytes(), equal_to(307))
        assert_that(eth_frame.get_short(), equal_to(
            "DST: MAC=00:0a:35:18:3c:1f, IP=10.0.1.14, DPort=8000"))
        assert_that(eth_frame.get_number_of_words(), equal_to(39))
        assert_that(eth_frame.get_word(0), equal_to(0x000a35183c1f0015))
        assert_that(eth_frame.get_word(37), equal_to(0x0000c84d08000000))
        assert_that(eth_frame.get_word(38), equal_to(0x0000010000000000))
        assert_that(eth_frame.get_tkeep(38), equal_to(0b1110_0000))
