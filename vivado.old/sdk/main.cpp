/*
 * main.cpp
 *
 *  Created on: Jul 18, 2025
 *      Author: johns
 */

#include <iostream>
#include <sleep.h>
#include "platform.h"

#include "xparameters.h"
#include "xgpio.h"

#include "DmaReader.h"
#include "FifoReader.h"


int main()
{
//	int status = 0;
	int counter = 0;

	init_platform();

	// Step 1 - Set up DMA #0
	printf("Configuring DMA #0\n");
	DmaReader dmaReader(XPAR_AXI_DMA_0_DEVICE_ID, 0x2000000);
	// Read 1 packet to make sure everything is okay
	int keepLooping = 1;
	while (keepLooping)
	{
//		struct EthFrame* packet = dmaReader.read_packets();
		EthernetFrame* packet = dmaReader.read_packets();
		if (packet == nullptr)
		{
			printf("No new data\n");
		}
		else
		{
			printf("New data\n");
			keepLooping = 0;
			printf("Exiting Loop\n");
		}
		sleep(2);
	}

	// Then continuously poll the FIFO
    // Set up FIFO #1
    printf("Configuring FIFO #1\n");
	FifoReader fifoReader(XPAR_AXI_FIFO_MM_S_0_DEVICE_ID);

	// Reset LabVIEW IP
	printf("Resetting LabVIEW IP\n");
    XGpio gpio_1;
    XGpio_Initialize(&gpio_1, XPAR_AXI_GPIO_1_DEVICE_ID);
    XGpio_SetDataDirection(&gpio_1, 1, 0);

    XGpio_DiscreteWrite(&gpio_1, 1, 0);
    XGpio_DiscreteWrite(&gpio_1, 1, 1);
    XGpio_DiscreteWrite(&gpio_1, 1, 0);

//	while (1) {
//		FifoPacketNode* packets = fifoReader.read_packets();
//
//		printf(".\n");
//		sleep(2);
//	}

    while (1) {
    	counter++;

//    	u64 buf_to_recv[1024];
//    	u32 buf_to_recv_len = 1024;
    	EthernetFrame* frames = dmaReader.read_packets();
    	if (frames == nullptr)
    	{
    		std::cout << "No Frames read, sleeping..." << "\n";
    		sleep(2);
    	}
    	else
    	{
    		EthernetFrame* current = frames;
    		EthernetFrame* prev;
    		while (current != nullptr) {
    			std::cout << "Frame Length: " << current->d_packetLengthBytes << "\n";
    			for (u32 i=0; i < current->d_packetLengthBytes; i++) {
    				printf("  0x%016lx\n", current->d_packetData[i]);
    			}
    			prev = current;
    			current = current->next;
//    			delete prev->packet_data;
    			delete prev;
    		}
    		//std::cout << "Read " << bytes_read << " bytes\n";
    		sleep(1);
    	}
    }

	cleanup_platform();

	return 0;
}
