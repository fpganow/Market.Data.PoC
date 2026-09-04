/*
 * EthernetFrame.cpp
 *
 *  Created on: Aug 7, 2025
 *      Author: johns
 */

#include "EthernetFrame.h"

#include <cstring>

EthernetFrame::EthernetFrame(u64* packetData,
							 u32 packetLengthBytes)
{
	// TODO: Copy incoming data
	d_packetData = new u64[packetLengthBytes];
	memcpy(d_packetData, packetData, packetLengthBytes);
	d_packetLengthBytes = packetLengthBytes;
	// TODO: REVERSE BYTE ORDER HERE
	// TODO: Identify if IPv4
	// TODO: Identify if UDP
	// TODO: Identify port

}

EthernetFrame::~EthernetFrame()
{

}

