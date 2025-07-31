#!/usr/bin/python3.11

import socket
import time

UDP_IP = "10.0.1.14"
UDP_PORT = 8000
#MESSAGE = b"Hello, World, More Words, More  More More"
MESSAGE = bytes.fromhex("DEADBEEFBEEFDEAD")
MESSAGE == bytes(" My Message is The Quick Brown Fox: ", encoding='utf-8')
print(f'Opening UDP Socket to {UDP_IP}:{UDP_PORT}')
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

i = 1
keepLooping = True
while keepLooping is True:
    counter = f"_{i}"
    message = MESSAGE + bytearray(counter, encoding='utf-8')
    i += 1
    sock.sendto(message, (UDP_IP, UDP_PORT))
    raw_data_str = "-".join([hex(x)[2:] for x in message])
    print(f"Sent: {message}: {raw_data_str}")
    for j in range(len(message) // 8):
        row_data_str = "-".join([hex(x)[2:] for x in message[j*8: (j*8)+8]])
        print(f' [{j:>2}]: {row_data_str}')
    remainder = len(message) % 8
    rem_row = len(message) // 8
    if remainder != 0:
        rem_data_str = "-".join([hex(x)[2:] for x in message[-remainder:]])
        print(f' [{rem_row:>2}]: {remainder} {rem_data_str}')
    time.sleep(1)

sock.close
