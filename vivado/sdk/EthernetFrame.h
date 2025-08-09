/*
 * EthernetFrame.h
 *
 *  Created on: Aug 7, 2025
 *      Author: johns
 */

#ifndef SRC_ETHERNETFRAME_H_
#define SRC_ETHERNETFRAME_H_

#include <xil_types.h>

class EthernetFrame {
public:
	EthernetFrame(u64* packetData, u32 packetLengthBytes);
	~EthernetFrame();

	u64* d_packetData;
	u32 d_packetLengthBytes;

	EthernetFrame* next;
};

#endif /* SRC_ETHERNETFRAME_H_ */
