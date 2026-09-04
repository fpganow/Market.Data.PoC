/*
 * FifoReader.cpp
 *
 *  Created on: Jul 18, 2025
 *      Author: johns
 */

#include "FifoReader.h"

#include <iostream>
#include <sleep.h>
#include <string>
#include <stdexcept>

#include <xllfifo.h>

FifoReader::FifoReader(int fifo_device_id)
{
	XLlFifo_Config *config;
	int status;

	config = XLlFfio_LookupConfig(fifo_device_id);
	if (!config) {
		std::cerr << "Configuration for FIFO failed " << fifo_device_id;
		throw std::runtime_error("Configuration for FIFO failed");
	}

	status = XLlFifo_CfgInitialize(&_fifo, config, config->BaseAddress);
	if (status != XST_SUCCESS) {
		std::cout << "Initialization failed for FIFO " << fifo_device_id << "\n";
		throw std::runtime_error("Initialization failed for FIFO");

	}

	status = XLlFifo_Status(&_fifo);
	XLlFifo_IntClear(&_fifo, 0xffffffff);
	status = XLlFifo_Status(&_fifo);
	if (status != 0x0) {
		std::cerr << "Reset value of ISR0: 0x"
				<< std::hex << XLlFifo_Status(&_fifo)
				<< "\n";
		throw std::runtime_error("Reset value of ISR0");
	}
}

FifoReader::~FifoReader()
{
}

FifoPacketNode*
FifoReader::read_packets()
{
	int status = 0;
	const int BUFFER_SIZE = 1024;
	const int WORD_SIZE = 8;

	FifoPacketNode* head = nullptr;

	u64 data_to_recv[BUFFER_SIZE];
	u64 rx_word;

	int recv_len = 0;
//	* XLlFifo_iRxOccupancy returns the number of 32-bit words available (occupancy)
//	* to be read from the receive channel of the FIFO, specified by
//	* <i>InstancePtr</i>.
	while(XLlFifo_iRxOccupancy(&_fifo))
	{
		recv_len = (XLlFifo_iRxGetLen(&_fifo)) / WORD_SIZE;
     	xil_printf("RECV_LEN: %d\n", recv_len);
		for (int j=0; j<recv_len; j++)
		{
			//rx_word = XLlFifo_RxGetWord(&fifo);
			rx_word = Xil_In64(_fifo.Axi4BaseAddress + XLLF_AXI4_RDFD_OFFSET);
			data_to_recv[j] = rx_word;
     		printf("RECV: 0x%llx\n", rx_word);
		}
	}

	status = XLlFifo_IsRxDone(&_fifo);
	if (status != 1) {
		std::cerr << "Receive failed " << status << "\n";
	}
	return head;
}
