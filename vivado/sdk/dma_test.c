
#include <stdio.h>
#include <xstatus.h>
#include <xaxidma_bd.h>
#include "dma_test.h"

#include "sleep.h"
#include "xparameters.h"




//#define MEM_BASE_ADDR_0		XPAR_PS7_DDR_0_S_AXI_BASEADDR
//#define MEM_BASE_ADDR_0		0x01000000

//#define TX_BD_SPACE_BASE_0	(MEM_BASE_ADDR_0)
//#define TX_BD_SPACE_HIGH_0	(MEM_BASE_ADDR_0 + 0x00000FFF)
//#define RX_BD_SPACE_BASE_0	(MEM_BASE_ADDR_0 + 0x00001000)
//#define RX_BD_SPACE_HIGH_0	(MEM_BASE_ADDR_0 + 0x00001FFF)
//#define TX_BUFFER_BASE_0		(MEM_BASE_ADDR_0 + 0x00100000)
//#define RX_BUFFER_BASE_0		(MEM_BASE_ADDR_0 + 0x00300000)
//#define RX_BUFFER_HIGH_0		(MEM_BASE_ADDR_0 + 0x004FFFFF)

//#define MEM_BASE_ADDR_1		0x02000000

//#define TX_BD_SPACE_BASE_1	(MEM_BASE_ADDR_1)
//#define TX_BD_SPACE_HIGH_1	(MEM_BASE_ADDR_1 + 0x00000FFF)
//#define RX_BD_SPACE_BASE_1	(MEM_BASE_ADDR_1 + 0x00001000)
//#define RX_BD_SPACE_HIGH_1	(MEM_BASE_ADDR_1 + 0x00001FFF)
//#define TX_BUFFER_BASE_1		(MEM_BASE_ADDR_1 + 0x00100000)
//#define RX_BUFFER_BASE_1		(MEM_BASE_ADDR_1 + 0x00300000)
//#define RX_BUFFER_HIGH_1		(MEM_BASE_ADDR_1 + 0x004FFFFF)

#define MAX_PKT_LEN		0x20
#define MARK_UNCACHEABLE        0x701

#define TEST_START_VALUE	0xC

//u32 *Packet = (u32 *) TX_BUFFER_BASE_0;

int dma_tx_setup(XAxiDma * AxiDmaInstPtr, AxiDma_Mem * axi_dma_mem)
{
	XAxiDma_BdRing *TxRingPtr;
	XAxiDma_Bd BdTemplate;
	int Delay = 0;
	int Coalesce = 1;
	int Status;
	u32 BdCount;

	TxRingPtr = XAxiDma_GetTxRing(AxiDmaInstPtr);
//	printf("[dma_tx_setup] TxRingPtr=%0llx\n", TxRingPtr);

	/* Disable all TX interrupts before TxBD space setup */
	XAxiDma_BdRingIntDisable(TxRingPtr, XAXIDMA_IRQ_ALL_MASK);

	/* Set TX delay and coalesce */
	XAxiDma_BdRingSetCoalesce(TxRingPtr, Coalesce, Delay);

	/* Setup TxBD space  */
//	printf("[dma_tx_setup] axi_dma_mem->tx_bd_space_high=%0llx\n", axi_dma_mem->tx_bd_space_high);
//	printf("[dma_tx_setup] axi_dma_mem->tx_bd_space_base=%0llx\n", axi_dma_mem->tx_bd_space_base);
	BdCount = XAxiDma_BdRingCntCalc(XAXIDMA_BD_MINIMUM_ALIGNMENT,
			axi_dma_mem->tx_bd_space_high - axi_dma_mem->tx_bd_space_base + 1);

	size_t size_of_bd = sizeof(XAxiDma_Bd);
	Status = XAxiDma_BdRingCreate(TxRingPtr,
			axi_dma_mem->tx_bd_space_base,
			axi_dma_mem->tx_bd_space_base,
			XAXIDMA_BD_MINIMUM_ALIGNMENT, BdCount);
	if (Status != XST_SUCCESS) {
		printf("failed create BD ring in txsetup\n");
		return XST_FAILURE;
	}
//	printf("[dma_tx_setup] BdCount=%d\n", BdCount);

	/*
	 * We create an all-zero BD as the template.
	 */
	XAxiDma_BdClear(&BdTemplate);

	Status = XAxiDma_BdRingClone(TxRingPtr, &BdTemplate);
	if (Status != XST_SUCCESS) {
		printf("failed bdring clone in txsetup %d\n", Status);
		return XST_FAILURE;
	}

	/* Start the TX channel */
	Status = XAxiDma_BdRingStart(TxRingPtr);
	if (Status != XST_SUCCESS) {
		printf("failed start bdring txsetup %d\n", Status);
		return XST_FAILURE;
	}

	return XST_SUCCESS;
}

int dma_rx_setup(XAxiDma * AxiDmaInstPtr, AxiDma_Mem * axi_dma_mem)
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
	int Index;

	RxRingPtr = XAxiDma_GetRxRing(AxiDmaInstPtr);

	/* Disable all RX interrupts before RxBD space setup */

	XAxiDma_BdRingIntDisable(RxRingPtr, XAXIDMA_IRQ_ALL_MASK);

	/* Set delay and coalescing */
	XAxiDma_BdRingSetCoalesce(RxRingPtr, Coalesce, Delay);

	/* Setup Rx BD space */
	BdCount = XAxiDma_BdRingCntCalc(XAXIDMA_BD_MINIMUM_ALIGNMENT,
			axi_dma_mem->rx_bd_space_high
			- axi_dma_mem->rx_bd_space_base + 1);
	Status = XAxiDma_BdRingCreate(RxRingPtr,
			axi_dma_mem->rx_bd_space_base,
			axi_dma_mem->rx_bd_space_base,
			XAXIDMA_BD_MINIMUM_ALIGNMENT, BdCount);

	if (Status != XST_SUCCESS) {
		printf("RX create BD ring failed %d\n", Status);
		return XST_FAILURE;
	}

	/*
	 * Setup an all-zero BD as the template for the Rx channel.
	 */
	XAxiDma_BdClear(&BdTemplate);

	Status = XAxiDma_BdRingClone(RxRingPtr, &BdTemplate);
	if (Status != XST_SUCCESS) {
		printf("RX clone BD failed %d\n", Status);
		return XST_FAILURE;
	}

	/* Attach buffers to RxBD ring so we are ready to receive packets */
	FreeBdCount = XAxiDma_BdRingGetFreeCnt(RxRingPtr);

	Status = XAxiDma_BdRingAlloc(RxRingPtr, FreeBdCount, &BdPtr);
	if (Status != XST_SUCCESS) {
		printf("RX alloc BD failed %d\n", Status);
		return XST_FAILURE;
	}

	BdCurPtr = BdPtr;
	RxBufferPtr = axi_dma_mem->rx_buffer_base;
	for (Index = 0; Index < FreeBdCount; Index++) {
		Status = XAxiDma_BdSetBufAddr(BdCurPtr, RxBufferPtr);

		if (Status != XST_SUCCESS) {
			printf("Set buffer addr %x on BD %x failed %d\n",
			    (unsigned int)RxBufferPtr,
			    (UINTPTR)BdCurPtr, Status);

			return XST_FAILURE;
		}
//		 * @param	BdPtr is the BD to operate on.
//		 * @param	LenBytes is the requested transfer length
//		 * @param	LengthMask is the maximum transfer length
		Status = XAxiDma_BdSetLength(BdCurPtr, MAX_PKT_LEN,
				RxRingPtr->MaxTransferLen);
		if (Status != XST_SUCCESS) {
			printf("Rx set length %d on BD %x failed %d\n",
			    MAX_PKT_LEN, (UINTPTR)BdCurPtr, Status);
			return XST_FAILURE;
		}

		/* Receive BDs do not need to set anything for the control
		 * The hardware will set the SOF/EOF bits per stream status
		 */
		XAxiDma_BdSetCtrl(BdCurPtr, 0);
		XAxiDma_BdSetId(BdCurPtr, RxBufferPtr);

		RxBufferPtr += MAX_PKT_LEN;
		BdCurPtr = (XAxiDma_Bd *)XAxiDma_BdRingNext(RxRingPtr, BdCurPtr);
	}

	/* Clear the receive buffer, so we can verify data
	 */
//	memset((void *)RX_BUFFER_BASE_0, 0, MAX_PKT_LEN);
	memset((void *)axi_dma_mem->rx_buffer_base, 0, MAX_PKT_LEN);

	Status = XAxiDma_BdRingToHw(RxRingPtr, FreeBdCount,
						BdPtr);
	if (Status != XST_SUCCESS) {
		printf("RX submit hw failed %d\n", Status);
		return XST_FAILURE;
	}

	/* Start RX DMA channel */
	Status = XAxiDma_BdRingStart(RxRingPtr);
	if (Status != XST_SUCCESS) {
		printf("RX start hw failed %d\n", Status);
		return XST_FAILURE;
	}

	return XST_SUCCESS;
}
//
//static int CheckData(AxiDma_Mem * axi_dma_mem)
//{
//	u64 *rx_packet_64;
//	u32 index = 0;
//
//	rx_packet_64 = (u64 *) axi_dma_mem->rx_buffer_base;
//
//	/* Invalidate the DestBuffer before receiving the data, in case the
//	 * Data Cache is enabled
//	 */
//	Xil_DCacheInvalidateRange((UINTPTR)rx_packet_64, 8*4);
//
//	for(index = 0; index < 8; index++) {
//		printf("Received %d: %llx\n",
//					index, rx_packet_64[index]);
//	}
//
//	return XST_SUCCESS;
//}

/*****************************************************************************/
/**
*
* This function waits until the DMA transaction is finished, checks data,
* and cleans up.
*
* @param	None
*
* @return	- XST_SUCCESS if DMA transfer is successful and data is correct,
*		- XST_FAILURE if fails.
*
* @note		None.
*
******************************************************************************/
// TODO:
// param: buffer
// buffer_len
// return num of bytes read
int receive_dma_packet(XAxiDma * AxiDmaInstPtr,
					   AxiDma_Mem * axi_dma_mem,
					   u32 *o_bytes_read,
					   u64 *buf_to_recv,
					   u32 buf_to_recv_len)
{
	XAxiDma_BdRing *RxRingPtr;
	XAxiDma_Bd *BdPtr;
	XAxiDma_Bd *CurBdPtr;
	int ProcessedBdCount;
	int FreeBdCount;
	int Status;
	int TimeOut = 1000000U;

	RxRingPtr = XAxiDma_GetRxRing(AxiDmaInstPtr);

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

	if (ProcessedBdCount == 0) {
		*o_bytes_read = 0;
		return XST_SUCCESS;
	}

//	u32 *o_bytes_read,
//	u64 *buf_to_recv,
//	u32 buf_to_recv_len)
	*(o_bytes_read) = 0;
//	memset(buf_to_recv, 0, buf_to_recv_len * 8);

	CurBdPtr = BdPtr;
	for(int i=0; i<ProcessedBdCount; i++) {
		int bd_length = XAxiDma_BdGetLength(CurBdPtr, 0xffff);
		// bd_act_length = length in bytes of all data
		int bd_act_length = XAxiDma_BdGetActualLength(CurBdPtr, 0xffff);
		u32 buf_addr = XAxiDma_BdGetBufAddr(CurBdPtr);
		u64 *p_buf_64 = (u64 *)buf_addr;
		u32 *p_buf_32 = (u32 *)buf_addr;

		for (int j=0; j< (bd_act_length / 8); j++) {
			printf("READ: %llx\n", *(p_buf_64 + *o_bytes_read));
			*(buf_to_recv + *o_bytes_read) = *(p_buf_64+j);
			*(o_bytes_read) += 8;
		}
		CurBdPtr = XAxiDma_BdRingNext(RxRingPtr, CurBdPtr);
	}

	// Read actual data
//	u64 *rx_packet_64;
//	u32 index = 0;
//
//	rx_packet_64 = (u64 *) axi_dma_mem->rx_buffer_base;
//
//	/* Invalidate the DestBuffer before receiving the data, in case the
//	 * Data Cache is enabled
//	 */
//	Xil_DCacheInvalidateRange((UINTPTR)rx_packet_64, 8*4);
//
//	for(index = 0; index < 8; index++) {
//		printf("Received %d: %llx\n",
//					index, rx_packet_64[index]);
//	}

	/* Free all processed RX BDs for future transmission */
	Status = XAxiDma_BdRingFree(RxRingPtr, ProcessedBdCount, BdPtr);
	if (Status != XST_SUCCESS) {
		xil_printf("Failed to free %d rx BDs %d\r\n",
		    ProcessedBdCount, Status);
		return XST_FAILURE;
	}

	/* Return processed BDs to RX channel so we are ready to receive new
	 * packets:
	 *    - Allocate all free RX BDs
	 *    - Pass the BDs to RX channel
	 */
	FreeBdCount = XAxiDma_BdRingGetFreeCnt(RxRingPtr);
	Status = XAxiDma_BdRingAlloc(RxRingPtr, FreeBdCount, &BdPtr);
	if (Status != XST_SUCCESS) {
		xil_printf("bd alloc failed %d\r\n", Status);
		return XST_FAILURE;
	}

	Status = XAxiDma_BdRingToHw(RxRingPtr, FreeBdCount, BdPtr);
	if (Status != XST_SUCCESS) {
		xil_printf("Submit %d rx BDs failed %d\r\n", FreeBdCount, Status);
		return XST_FAILURE;
	}

	return XST_SUCCESS;
}

int send_dma_packet(XAxiDma *axi_dma,
					AxiDma_Mem *axi_dma_mem,
					u64 *buffer, u32 buffer_len)
{
	XAxiDma_BdRing *TxRingPtr;
//	u8 *TxPacket;
	u64 *tx_packet_64;
//	u8 Value;
	XAxiDma_Bd *BdPtr;
	int ProcessedBdCount;
	int Status;
	int Index;
//	printf("SendPacket [send_dma_packet]\n");

	TxRingPtr = XAxiDma_GetTxRing(axi_dma);
//	printf("TxRingPtr=%0llx\n", TxRingPtr);

	tx_packet_64 = (u64 *) axi_dma_mem->tx_buffer_base;
//	printf("TxPacket=%0llx\n", tx_packet_64);

	for(Index = 0; Index < buffer_len; Index ++) {
//		TxPacket[Index] = Value;
//		xil_printf("Sending %d: 0x%x\r\n", Index, (unsigned int)Value);
//		Value = (Value + 1) & 0xFF;
		*(tx_packet_64+Index) = *(buffer+Index);
//		printf("Sending [%d]: 0x%llx\n", Index, *(tx_packet_64+Index));
	}

	/* Flush the buffers before the DMA transfer, in case the Data Cache
	 * is enabled
	 */
//	Xil_DCacheFlushRange((UINTPTR)TxPacket, MAX_PKT_LEN);
//	Xil_DCacheFlushRange((UINTPTR)RX_BUFFER_BASE_0, MAX_PKT_LEN);
	Xil_DCacheFlushRange((UINTPTR)tx_packet_64, buffer_len*8);
	Xil_DCacheFlushRange((UINTPTR)axi_dma_mem->rx_buffer_base, buffer_len*8);
//	printf("Flushing tx_packet_64=%0llx, len=%d\n", tx_packet_64, buffer_len*8);
//	printf("Flushing axi_dma_mem->rx_buffer_base=%0llx, len=%d\n", (UINTPTR)axi_dma_mem->rx_buffer_base, buffer_len*8);

	/* Allocate a BD */
	Status = XAxiDma_BdRingAlloc(TxRingPtr, 1, &BdPtr);
	if (Status != XST_SUCCESS) {
		return XST_FAILURE;
	}

	/* Set up the BD using the information of the packet to transmit */
//	printf("Set Buf Addr axi_dma_mem->tx_buffer_base=%0llx, len=%d\n", (UINTPTR)axi_dma_mem->tx_buffer_base, buffer_len*8);
	Status = XAxiDma_BdSetBufAddr(BdPtr, (UINTPTR) axi_dma_mem->tx_buffer_base);
	if (Status != XST_SUCCESS) {
//		xil_printf("Tx set buffer addr %x on BD %x failed %d\r\n",
//			    (UINTPTR)axi_dma_mem->tx_buffer_base, (UINTPTR)BdPtr, Status);
		return XST_FAILURE;
	}

//	printf("Set Length = %d\n", buffer_len*8);
	Status = XAxiDma_BdSetLength(BdPtr, buffer_len*8, // Length in bytes
					TxRingPtr->MaxTransferLen);
	if (Status != XST_SUCCESS) {
		xil_printf("Tx set length %d on BD %x failed %d\r\n",
				buffer_len*8, (UINTPTR)BdPtr, Status);

		return XST_FAILURE;
	}

	/* For single packet, both SOF and EOF are to be set
	 */
	XAxiDma_BdSetCtrl(BdPtr, XAXIDMA_BD_CTRL_TXEOF_MASK |
							XAXIDMA_BD_CTRL_TXSOF_MASK);

//	printf("Set Id %0llx\n",(UINTPTR)axi_dma_mem->tx_buffer_base);
	XAxiDma_BdSetId(BdPtr, (UINTPTR)axi_dma_mem->tx_buffer_base);

	/* Give the BD to DMA to kick off the transmission. */
//	printf("BdRingToHw %0llx\n",(UINTPTR)BdPtr);
	Status = XAxiDma_BdRingToHw(TxRingPtr, 1, BdPtr);
	if (Status != XST_SUCCESS) {
		printf("to hw failed %d\n", Status);
		return XST_FAILURE;
	}

	XAxiDma_BdRing *RxRingPtr;
	RxRingPtr = XAxiDma_GetRxRing(axi_dma);
	int TimeOut = 1000000U;
	/*
	 * Wait until the one BD TX transaction is done or
	 * 1usec * 10^6 iterations of timeout occurs.
	 */
	while (TimeOut) {
		if ((ProcessedBdCount = XAxiDma_BdRingFromHw(TxRingPtr,
					XAXIDMA_ALL_BDS,
					&BdPtr)) != 0) {
				break;
		}
		TimeOut--;
		usleep(1U);
	}

//	printf("Timing out\n");

	/* Free all processed TX BDs for future transmission */
	Status = XAxiDma_BdRingFree(TxRingPtr, ProcessedBdCount, BdPtr);
	if (Status != XST_SUCCESS) {
		printf("Failed to free %d tx BDs %d\n",
		    ProcessedBdCount, Status);
		return XST_FAILURE;
	}

	return XST_SUCCESS;
}

int start_dma(XAxiDma *axi_dma, int device_id, AxiDma_Mem * axi_dma_mem)
{
	int status;
	XAxiDma_Config *config;

#define MARK_UNCACHEABLE        0x701
#ifdef __aarch64__
//	xil_printf("__aarch64__ is true\n\r");
	Xil_SetTlbAttributes(axi_dma_mem->tx_bd_space_base, MARK_UNCACHEABLE);
	Xil_SetTlbAttributes(axi_dma_mem->rx_bd_space_base, MARK_UNCACHEABLE);
#endif

	config = XAxiDma_LookupConfig(device_id);
	if (!config) {
		printf("Config not found for %d\n", device_id);
		return XST_FAILURE;
	}

	/* Initialize DMA engine */
	status = XAxiDma_CfgInitialize(axi_dma, config);
	if (status != XST_SUCCESS) {
		printf("Initialization failed %d\n", status);
		return XST_FAILURE;
	}

	if(!XAxiDma_HasSg(axi_dma)) {
		printf("Device configured as Simple mode\n");
		return XST_FAILURE;
	}

	status = dma_tx_setup(axi_dma, axi_dma_mem);
	if (status != XST_SUCCESS) {
		printf("Failed to set up DMA TX\n");
		return XST_FAILURE;
	} else {
		printf("  - Successfully set up DMA TX\n");
	}

	status = dma_rx_setup(axi_dma, axi_dma_mem);
	if (status != XST_SUCCESS) {
		printf("Failed to set up DMA RX\n");
		return XST_FAILURE;
	} else {
		printf("  - Successfully set up DMA RX\n");
	}

	return XST_SUCCESS;
}

int receive_dma_packet2(XAxiDma * AxiDmaInstPtr, AxiDma_Mem * axi_dma_mem)
{
//	XAxiDma_BdRing *TxRingPtr;
	XAxiDma_BdRing *RxRingPtr;
	XAxiDma_Bd *BdPtr;
	int ProcessedBdCount;
	int FreeBdCount;
	int Status;
	int TimeOut = 1000000U;

	RxRingPtr = XAxiDma_GetRxRing(AxiDmaInstPtr);

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

	/* Check received data */
	u64 *rx_packet_64;
	u32 index = 0;

	rx_packet_64 = (u64 *) axi_dma_mem->rx_buffer_base;

	printf("# of received BDs: %d\n", ProcessedBdCount);
	/* Invalidate the DestBuffer before receiving the data, in case the
	 * Data Cache is enabled
	 */
	Xil_DCacheInvalidateRange((UINTPTR)rx_packet_64, 8*4);

	for(index = 0; index < 8; index++) {
		printf("Received %d: %llx\n",
					index, rx_packet_64[index]);
	}

	/* Free all processed RX BDs for future transmission */
	Status = XAxiDma_BdRingFree(RxRingPtr, ProcessedBdCount, BdPtr);
	if (Status != XST_SUCCESS) {
		xil_printf("Failed to free %d rx BDs %d\r\n",
		    ProcessedBdCount, Status);
		return XST_FAILURE;
	}

	/* Return processed BDs to RX channel so we are ready to receive new
	 * packets:
	 *    - Allocate all free RX BDs
	 *    - Pass the BDs to RX channel
	 */
	FreeBdCount = XAxiDma_BdRingGetFreeCnt(RxRingPtr);
	Status = XAxiDma_BdRingAlloc(RxRingPtr, FreeBdCount, &BdPtr);
	if (Status != XST_SUCCESS) {
		xil_printf("bd alloc failed %d\r\n", Status);
		return XST_FAILURE;
	}

	Status = XAxiDma_BdRingToHw(RxRingPtr, FreeBdCount, BdPtr);
	if (Status != XST_SUCCESS) {
		xil_printf("Submit %d rx BDs failed %d\r\n", FreeBdCount, Status);
		return XST_FAILURE;
	}

	return XST_SUCCESS;
}

int listen_to_dma(int dma_device_id)
{
	int status;
	XAxiDma axi_dma;

	u32 ddr_mem_base =  0x1000000;
	if (ddr_mem_base == 0x01000000) {
		printf("\n--- BASE 0x01000000 == 0x%x\n", ddr_mem_base);
	} else {
		printf("\n--- BASE 0x01000000 != 0x%x\n", ddr_mem_base);
	}
	printf("DMA Loopback Single Started\n");

	// Start DMA
	AxiDma_Mem axi_dma_mem;
	axi_dma_mem.tx_bd_space_base	= ddr_mem_base;
	axi_dma_mem.tx_bd_space_high = (ddr_mem_base + 0x00000FFF);
	axi_dma_mem.rx_bd_space_base = (ddr_mem_base + 0x00001000);
	axi_dma_mem.rx_bd_space_high = (ddr_mem_base + 0x00001FFF);
	axi_dma_mem.tx_buffer_base = (ddr_mem_base + 0x00100000);
	axi_dma_mem.rx_buffer_base = (ddr_mem_base + 0x00300000);
	axi_dma_mem.rx_buffer_high = (ddr_mem_base + 0x004FFFFF);
	status = start_dma(&axi_dma, dma_device_id, &axi_dma_mem);
	if (status != XST_SUCCESS) {
		printf("Failed to start DMA Controller #%d\n", dma_device_id);
		return XST_FAILURE;
	}

	// Poll / Read
	u64 buf_to_recv[4];

	/* Check DMA transfer result */
	status = receive_dma_packet2(&axi_dma, &axi_dma_mem);
	if (status != XST_SUCCESS) {
		printf("AXI DMA SG Polling Example Failed\n");
		return XST_FAILURE;
	}

	return 0;
}


int dma_loopback_single(int dma_device_id)
{
	int status;
	XAxiDma axi_dma;

	u32 ddr_mem_base =  0x1000000;
	printf("  - DMA Loopback Single Test Started\n");

	// Start DMA
	AxiDma_Mem axi_dma_mem;
	axi_dma_mem.tx_bd_space_base	= ddr_mem_base;
	axi_dma_mem.tx_bd_space_high = (ddr_mem_base + 0x00000FFF);
	axi_dma_mem.rx_bd_space_base = (ddr_mem_base + 0x00001000);
	axi_dma_mem.rx_bd_space_high = (ddr_mem_base + 0x00001FFF);
	axi_dma_mem.tx_buffer_base = (ddr_mem_base + 0x00100000);
	axi_dma_mem.rx_buffer_base = (ddr_mem_base + 0x00300000);
	axi_dma_mem.rx_buffer_high = (ddr_mem_base + 0x004FFFFF);
	status = start_dma(&axi_dma, dma_device_id, &axi_dma_mem);
	if (status != XST_SUCCESS) {
		printf("Failed to start DMA Controller #%d\n", dma_device_id);
		return XST_FAILURE;
	}
	printf("  - start_dma() success\n");

	// Prepare to send data
	u64 buf_to_send[16];
	u32 buf_to_send_len = 2;
	for (int i=0; i < buf_to_send_len; i++) {
		buf_to_send[i] = 0xDEADBEEFCCBB0000 + i + 1;
	}
	printf("  - Sending %d bytes of data\n", buf_to_send_len);
	status = send_dma_packet(&axi_dma, &axi_dma_mem, buf_to_send, buf_to_send_len);
	if (status != XST_SUCCESS) {
		return XST_FAILURE;
	}
	printf("  - send_dma_packet() success\n");

	// Read Data from DMA
	u64* buf_to_recv = NULL;
	u32 buf_to_recv_len = 1000;
	u32 o_bytes_read;
	buf_to_recv = (u64 *)malloc(sizeof(u64) * buf_to_recv_len);

	status = receive_dma_packet(&axi_dma, &axi_dma_mem, &o_bytes_read, buf_to_recv, buf_to_recv_len);
	if (status != XST_SUCCESS) {
		printf("AXI DMA SG Polling Example Failed\n");
		free(buf_to_recv);
		return XST_FAILURE;
	}
	free(buf_to_recv);
	printf("  - receive_dma_packet() success\n");

	return XST_SUCCESS;
}

void dma_busy_wait(int interval_s)
{
    // Loop infinitely, sleeping interval_s seconds
    int counter = 0;
    while (1) {
    	xil_printf("Counter: %d\n", counter++);
    	sleep(interval_s);
    }
}
