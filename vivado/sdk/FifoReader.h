/*
 * FifoReader.h
 *
 *  Created on: Jul 18, 2025
 *      Author: johns
 */

#ifndef SRC_FIFOREADER_H_
#define SRC_FIFOREADER_H_

#include <xllfifo.h>

typedef struct FifoPacket {
	u32 packet_length;
	u64 *packet_data;
	FifoPacket *next;
} FifoPacketNode;

class FifoReader {
public:
	FifoReader(int fifo_device_id);
	virtual ~FifoReader();

	FifoPacketNode* read_packets();

private:
	XLlFifo _fifo;
};

#endif /* SRC_FIFOREADER_H_ */
