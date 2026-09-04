/*
 * DmaReader.cpp
 *
 *  Created on: Jul 18, 2025
 *      Author: johns
 */

#include "DmaReader.h"

#include <iostream>
#include <sleep.h>
#include <string>
#include <stdexcept>

u64 buffer[2048];
u32 buffer_len = 2048;


DmaReader::DmaReader(int dma_device_id, u32 ddr_mem_base)
{
	_dma_device_id = dma_device_id;
	_ddr_mem_base = ddr_mem_base;

	// Set Max packet length
	_max_pkt_len = 0x20;

	_axi_dma_mem.tx_bd_space_base	= ddr_mem_base;
	_axi_dma_mem.tx_bd_space_high = (ddr_mem_base + 0x00000FFF);
	_axi_dma_mem.rx_bd_space_base = (ddr_mem_base + 0x00001000);
	_axi_dma_mem.rx_bd_space_high = (ddr_mem_base + 0x00001FFF);
	_axi_dma_mem.tx_buffer_base = (ddr_mem_base + 0x00100000);
	_axi_dma_mem.rx_buffer_base = (ddr_mem_base + 0x00300000);
	_axi_dma_mem.rx_buffer_high = (ddr_mem_base + 0x004FFFFF);

	int status;
	XAxiDma_Config *config;
#define MARK_UNCACHEABLE        0x701
#ifdef __aarch64__
	Xil_SetTlbAttributes(_axi_dma_mem.tx_bd_space_base, MARK_UNCACHEABLE);
	Xil_SetTlbAttributes(_axi_dma_mem.rx_bd_space_base, MARK_UNCACHEABLE);
#endif

	config = XAxiDma_LookupConfig(_dma_device_id);
	if (!config) {
		std::cerr << "Config not found for device " << _dma_device_id << "\n";
		throw std::runtime_error("Config not found");
	}

	/* Initialize DMA engine */
	status = XAxiDma_CfgInitialize(&_axi_dma, config);
	if (status != XST_SUCCESS) {
		std::cerr << "Initialization failed " << status << "\n";
		throw std::runtime_error("Initialization failed");
	}

	if(!XAxiDma_HasSg(&_axi_dma)) {
		std::cerr << "Device configured as Simple mode" << "\n";
		throw std::runtime_error("Device configured as Simple mode");
	}

	dma_tx_setup();

	dma_rx_setup();
}

DmaReader::~DmaReader()
{

}

void
DmaReader::dma_tx_setup()
{
	XAxiDma_BdRing *TxRingPtr;
	XAxiDma_Bd BdTemplate;
	int Delay = 0;
	int Coalesce = 1;
	int Status;
	u32 BdCount;

	TxRingPtr = XAxiDma_GetTxRing(&_axi_dma);
//	printf("[dma_tx_setup] TxRingPtr=%0llx\n", TxRingPtr);

	/* Disable all TX interrupts before TxBD space setup */
	XAxiDma_BdRingIntDisable(TxRingPtr, XAXIDMA_IRQ_ALL_MASK);

	/* Set TX delay and coalesce */
	XAxiDma_BdRingSetCoalesce(TxRingPtr, Coalesce, Delay);

	/* Setup TxBD space  */
//	printf("[dma_tx_setup] axi_dma_mem->tx_bd_space_high=%0llx\n", axi_dma_mem->tx_bd_space_high);
//	printf("[dma_tx_setup] axi_dma_mem->tx_bd_space_base=%0llx\n", axi_dma_mem->tx_bd_space_base);
	BdCount = XAxiDma_BdRingCntCalc(XAXIDMA_BD_MINIMUM_ALIGNMENT,
			_axi_dma_mem.tx_bd_space_high - _axi_dma_mem.tx_bd_space_base + 1);

	size_t size_of_bd = sizeof(XAxiDma_Bd);
	Status = XAxiDma_BdRingCreate(TxRingPtr,
			_axi_dma_mem.tx_bd_space_base,
			_axi_dma_mem.tx_bd_space_base,
			XAXIDMA_BD_MINIMUM_ALIGNMENT, BdCount);
	if (Status != XST_SUCCESS) {
		std::cerr << "failed create BD ring in txsetu\n";
		throw std::runtime_error("failed create BD ring in txsetup");
	}
//	printf("[dma_tx_setup] BdCount=%d\n", BdCount);

	/*
	 * We create an all-zero BD as the template.
	 */
	XAxiDma_BdClear(&BdTemplate);

	Status = XAxiDma_BdRingClone(TxRingPtr, &BdTemplate);
	if (Status != XST_SUCCESS) {
		std::cerr << "failed bdring clone in txsetup " << Status << "n";
		throw std::runtime_error("failed bdring clone in txsetup");
	}

	/* Start the TX channel */
	Status = XAxiDma_BdRingStart(TxRingPtr);
	if (Status != XST_SUCCESS) {
		std::cerr << "failed start bdring txsetup " << Status << "\n";
		throw std::runtime_error("failed start bdring txsetup");
	}
}

void
DmaReader::dma_rx_setup()
{
	XAxiDma_BdRing *RxRingPtr;
	int Delay = 0;
	int Coalesce = 1;
	int Status;
	XAxiDma_Bd BdTemplate;
	XAxiDma_Bd *BdPtr;
	XAxiDma_Bd *BdCurPtr;
	u32 BdCount;
	u32 FreeBdCount;
	UINTPTR RxBufferPtr;
	u32 Index;

	RxRingPtr = XAxiDma_GetRxRing(&_axi_dma);

	/* Disable all RX interrupts before RxBD space setup */
	XAxiDma_BdRingIntDisable(RxRingPtr, XAXIDMA_IRQ_ALL_MASK);

	/* Set delay and coalescing */
	XAxiDma_BdRingSetCoalesce(RxRingPtr, Coalesce, Delay);

	/* Setup Rx BD space */
	BdCount = XAxiDma_BdRingCntCalc(XAXIDMA_BD_MINIMUM_ALIGNMENT,
			_axi_dma_mem.rx_bd_space_high
			- _axi_dma_mem.rx_bd_space_base + 1);
	Status = XAxiDma_BdRingCreate(RxRingPtr,
			_axi_dma_mem.rx_bd_space_base,
			_axi_dma_mem.rx_bd_space_base,
			XAXIDMA_BD_MINIMUM_ALIGNMENT, BdCount);
	if (Status != XST_SUCCESS) {
		std::cerr << "RX create BD ring failed " << Status << "\n";
		throw std::runtime_error("RX create BD ring failed");
	}

	/*
	 * Setup an all-zero BD as the template for the Rx channel.
	 */
	XAxiDma_BdClear(&BdTemplate);

	Status = XAxiDma_BdRingClone(RxRingPtr, &BdTemplate);
	if (Status != XST_SUCCESS) {
		std::cerr << "RX clone BD failed " << Status << "\n";
		throw std::runtime_error("RX clone BD failed ");
	}

	/* Attach buffers to RxBD ring so we are ready to receive packets */
	FreeBdCount = XAxiDma_BdRingGetFreeCnt(RxRingPtr);

	Status = XAxiDma_BdRingAlloc(RxRingPtr, FreeBdCount, &BdPtr);
	if (Status != XST_SUCCESS) {
		std::cerr << "RX alloc BD failed " << Status << "\n";
		throw std::runtime_error("RX alloc BD failed");
	}

	BdCurPtr = BdPtr;
	RxBufferPtr = _axi_dma_mem.rx_buffer_base;
	for (Index = 0; Index < FreeBdCount; Index++) {
		Status = XAxiDma_BdSetBufAddr(BdCurPtr, RxBufferPtr);

		if (Status != XST_SUCCESS) {
			std::cerr << "Set buffer addr " << (unsigned int)RxBufferPtr
					<< " on BD " << (UINTPTR)BdCurPtr
					<< " failed " << Status
					<< "\n";
			throw std::runtime_error("Set buffer address on BD failed.");
		}
//		 * @param	BdPtr is the BD to operate on.
//		 * @param	LenBytes is the requested transfer length
//		 * @param	LengthMask is the maximum transfer length
		Status = XAxiDma_BdSetLength(BdCurPtr, _max_pkt_len,
				RxRingPtr->MaxTransferLen);
		if (Status != XST_SUCCESS) {
			std::cerr << "Rx set length " << _max_pkt_len
					<< " on BD " << (UINTPTR)BdCurPtr
					<< "failed " << Status
					<< "\n";
			throw std::runtime_error("Set buffer length on BD failed.");
		}

		/* Receive BDs do not need to set anything for the control
		 * The hardware will set the SOF/EOF bits per stream status
		 */
		XAxiDma_BdSetCtrl(BdCurPtr, 0);
		XAxiDma_BdSetId(BdCurPtr, RxBufferPtr);

		RxBufferPtr += _max_pkt_len;
		BdCurPtr = (XAxiDma_Bd *)XAxiDma_BdRingNext(RxRingPtr, BdCurPtr);
	}

	/* Clear the receive buffer, so we can verify data
	 */
//	memset((void *)RX_BUFFER_BASE_0, 0, MAX_PKT_LEN);
	memset((void *)_axi_dma_mem.rx_buffer_base, 0, _max_pkt_len);

	Status = XAxiDma_BdRingToHw(RxRingPtr, FreeBdCount,
						BdPtr);
	if (Status != XST_SUCCESS) {
		std ::cerr << "RX submit hw failed " << Status << "\n";
		throw std::runtime_error("RX submit hw failed");
	}

	/* Start RX DMA channel */
	Status = XAxiDma_BdRingStart(RxRingPtr);
	if (Status != XST_SUCCESS) {
		std::cerr << "RX start hw failed "
				<< Status << "\n";
		throw std::runtime_error("RX start hw failed");
	}
}

//struct EthFrame*
EthernetFrame*
DmaReader::read_packets()
{
//	int bytes_read = 0;

	XAxiDma_BdRing *RxRingPtr;
	XAxiDma_Bd *BdPtr;
	XAxiDma_Bd *CurBdPtr;
	int ProcessedBdCount;
	int FreeBdCount;
	int Status;
	int TimeOut = 1000000U;

	// Get BD RX Ring Pointer
	RxRingPtr = XAxiDma_GetRxRing(&_axi_dma);

	/*
	 * Wait until the data has been received by the Rx channel or
	 * 1usec * 10^6 iterations of timeout occurs.
	 */
	while (TimeOut) {
		if ((ProcessedBdCount = XAxiDma_BdRingFromHw(RxRingPtr,
					XAXIDMA_ALL_BDS,
					&BdPtr)) != 0) {
			break;
		}
		TimeOut--;
		usleep(1U);
	}

	// If no data read, return 0
	if (ProcessedBdCount == 0) {
		return nullptr;
	} else {
		std::cout << "ProcessedBdCount=" << ProcessedBdCount << "\n";
	}

	u32 buffer_i = 0;

	EthernetFrame* e_head = nullptr;
	EthernetFrame* e_current = nullptr;
	struct EthFrame* head = nullptr;
	struct EthFrame* current = nullptr;

	// Iterate over read BDs
	CurBdPtr = BdPtr;
	for(int i=0; i<ProcessedBdCount; i++) {
		int bd_length = XAxiDma_BdGetLength(CurBdPtr, 0xffff);
		// bd_act_length = length in bytes of all data
		int bd_act_length = XAxiDma_BdGetActualLength(CurBdPtr, 0xffff);
		u32 status = XAxiDma_BdGetSts(CurBdPtr);
		int is_sof = (status & XAXIDMA_BD_STS_RXSOF_MASK) == XAXIDMA_BD_STS_RXSOF_MASK;
		int is_eof = (status & XAXIDMA_BD_STS_RXEOF_MASK) == XAXIDMA_BD_STS_RXEOF_MASK;

		u32 buf_addr = XAxiDma_BdGetBufAddr(CurBdPtr);
		u64 *p_buf_64 = (u64 *)((u64)buf_addr);
//		printf(" bd_num=%d,bd_length=%d,bd_act_length=%d,is_sof=%d,is_eof=%d 0x%x\n",
//				i,
//				bd_length,
//				bd_act_length,
//				is_sof,
//				is_eof,
//				buf_addr);
//		printf("&buffer=0x%x\n", &buffer);

		if (is_sof == 1)
		{
			buffer_i = 0;
		}
		u64 d_word;
		for (int j=0; j< (bd_act_length / 8); j++) {
			d_word = *(p_buf_64+j);
//			d_word = reverse_bytes_manual(d_word);
			printf("  - READ: 0x%016lx\n", d_word);
//			*(buf_to_recv + j) = d_word;
//			bytes_read += 8;

//			printf("buffer_i=%d\n", buffer_i);
			buffer[buffer_i] = d_word;
			buffer_i++;
		}
		if (is_eof == 1)
		{
//			//buffer[0:buffer_i - 1] has a full packet
			if (e_head == nullptr) {
				e_current = e_head = new EthernetFrame(buffer, buffer_i*8);
			} else {
				e_current->next = new EthernetFrame(buffer, buffer_i*8);
				e_current = e_current->next;
			}
			e_current->next = nullptr;
			if (head == nullptr) {
				current = head = new struct EthFrame();
			} else {
				current->next = new struct EthFrame();
				current = current->next;
			}
			current->next = nullptr;
			current->packet_length = buffer_i;
			current->packet_data = new u64[buffer_i];
			memcpy(current->packet_data, buffer, buffer_i*8);
//			std::cout << "[2]buffer_i = " << buffer_i << "\n";
		}
		CurBdPtr = (XAxiDma_Bd *)XAxiDma_BdRingNext(RxRingPtr, CurBdPtr);
	}

	// Free all processed RX BDs
	Status = XAxiDma_BdRingFree(RxRingPtr, ProcessedBdCount, BdPtr);
	if (Status != XST_SUCCESS) {
		std::cerr << "Failed to free " << ProcessedBdCount
				<< " rx BDs " << Status
				<< "n";
		return nullptr;
	}

	// Return processed BX to RX Channel
	/* Return processed BDs to RX channel so we are ready to receive new
	 * packets:
	 *    - Allocate all free RX BDs
	 *    - Pass the BDs to RX channel
	 */
	FreeBdCount = XAxiDma_BdRingGetFreeCnt(RxRingPtr);
	Status = XAxiDma_BdRingAlloc(RxRingPtr, FreeBdCount, &BdPtr);
	if (Status != XST_SUCCESS) {
		std::cerr << "bd alloc failed " << Status << "\n";
		return nullptr;
	}

	Status = XAxiDma_BdRingToHw(RxRingPtr, FreeBdCount, BdPtr);
	if (Status != XST_SUCCESS) {
		std::cerr << "Submit " << FreeBdCount
				<< "  rx BDs failed " << Status << "\n";
		return nullptr;
	}

	return e_head;
}
