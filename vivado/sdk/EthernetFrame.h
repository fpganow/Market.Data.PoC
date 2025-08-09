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
	EthernetFrame(u64* packet_data, u32 packet_length);
	~EthernetFrame();

	EthernetFrame* next;
};

#endif /* SRC_ETHERNETFRAME_H_ */
