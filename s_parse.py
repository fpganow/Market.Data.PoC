#!/usr/bin/env python3.11

# scapy

from pathlib import Path
import random
import re
from scapy.all import *

file_path = 'tests/data/raw_run_25_02_03.txt'
dst_ip = "10.0.1.14"


pcap_file = file_path.split('.')[0] + '.pcap'

print(f'Opening: {file_path}')
print(f'Opening: {pcap_file}')

pcap_out = PcapWriter(pcap_file, append=True)

prev_frame_num = None
frames = []
frame_data = []
for line in Path(file_path).read_text().splitlines():
    if 'PAYLOAD_DATA' in line:
        # Parse line header
        pattern = r"\[([^\]]*)\]"
        matches = re.findall(pattern, line)
        bd_set_num = int(matches[1])
        bd_num = int(matches[2])
        frame_num = int(matches[3].split('=')[1])

        # Parse line bytes
        pattern = f"\[.*\](.*)$"
        matches = re.findall(pattern, line)
        bytes_ = [int(x.strip(), 16) for x in matches[0].strip().split()]

        if prev_frame_num is None:
            frame_data.extend(bytes_)
            prev_frame_num = frame_num
        elif prev_frame_num != frame_num:
            #if random.randint(0, 10) == 5:
            #    breakpoint()
            try:
                # Create a packet from the byte array
                packet = Ether(bytearray(frame_data))
                if ARP in packet:
                    arp = packet[ARP]
                    print(f'ARP: PSRC={arp.psrc}, PDST={arp.pdst}')
                elif UDP in packet:
                    udp = packet[UDP]
                    if packet[IP].dst == dst_ip:
                        print(f'UDP: SRC={packet[IP].src}, DST={packet[IP].dst}')
                        print(f'     SPORT={udp.sport}, DPORT={udp.dport}')
                        print(f'     PAYLOAD={udp}')
                        pcap_out.write(packet)
                elif TCP in packet:
                    tcp = packet[TCP]
                    breakpoint()
            except Exception as ex:
                print(f'Error parsing frame #: {frame_num}')
            prev_frame_num = frame_num
            frames.extend(frame_data)
            frame_data = bytes_
        else:
            frame_data.extend(bytes_)
pcap_out.close()
