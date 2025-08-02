/*
 * DmaReader.h
 *
 *  Created on: Jul 18, 2025
 *      Author: johns
 */

#ifndef SRC_DMAREADER_H_
#define SRC_DMAREADER_H_

#include <xaxidma.h>
#include <xaxidma_bd.h>

#include <xil_types.h>
#include <xil_mmu.h>

typedef struct EthFrame {
	u32 packet_length;
	u64 *packet_data;
	EthFrame *next;
} EthFrameNode;

typedef struct {
	u32 tx_bd_space_base;
	u32 tx_bd_space_high;
	u32 rx_bd_space_base;
	u32 rx_bd_space_high;
	u32 tx_buffer_base;
	u32 rx_buffer_base;
	u32 rx_buffer_high;
} AxiDma_Mem;

class DmaReader {
public:
	DmaReader(int dma_device_id, u32 ddr_mem_base);
	virtual ~DmaReader();

	// Returns number of bytes read
	EthFrameNode* read_packets();

private:
	int _dma_device_id;
	u32 _ddr_mem_base;
	u32 _max_pkt_len;

	AxiDma_Mem _axi_dma_mem;
	XAxiDma _axi_dma;

	void dma_tx_setup();
	void dma_rx_setup();
};

#endif /* SRC_DMAREADER_H_ */
