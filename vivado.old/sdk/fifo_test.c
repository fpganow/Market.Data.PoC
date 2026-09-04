
#include "fifo_test.h"

#include "sleep.h"
#include <stdio.h>
#include <xstatus.h>

#include "xllfifo.h"


int start_fifo(XLlFifo *fifo, u32 device_id)
{
	XLlFifo_Config *config;
	int status;

	config = XLlFfio_LookupConfig(device_id);
	if (!config) {
		printf("Configuration for FIFO at %0x not found\n", device_id);
		return XST_FAILURE;
	}

	status = XLlFifo_CfgInitialize(fifo, config, config->BaseAddress);
	if (status != XST_SUCCESS) {
		printf("Initialization failed for FIFO %d\n", device_id);
		return XST_FAILURE;
	}

	status = XLlFifo_Status(fifo);
	printf("status=%0lx\n", status);
	XLlFifo_IntClear(fifo, 0xffffffff);
	status = XLlFifo_Status(fifo);
	printf("status=%0lx\n", status);
	if (status != 0x0) {
		printf("ERROR: Reset value of ISR0: 0x%x\n", XLlFifo_Status(fifo));
		return XST_FAILURE;
	}

	return XST_SUCCESS;
}

void test_single_fifo_loopback(int device_id)
{
	printf("Testing Single FIFO Loop-back\n");

#define BUFFER_SIZE 16
#define WORD_SIZE 8 // Word size 8 for 64-bit data transfers

	int res = 0;
	int status = 0;

    // Initialize FIFOs
	XLlFifo fifo;
    res = start_fifo(&fifo, device_id);
    if (res != XST_SUCCESS) {
    	printf("Failed to start FIFO\n");
    	return;
    }

    // Prepare data to send and clear buffer for memory to receive
    u64 data_to_send[BUFFER_SIZE];
    u64 data_to_recv[BUFFER_SIZE];
    int i;
    for (i=0; i<BUFFER_SIZE; i++) {
    	data_to_send[i] = 0xDEADBEEFAABBAA00 + i;
    	data_to_recv[i] = 0;
    }

    // Put data in FIFO
    int vacancy;
    for (i=0; i < BUFFER_SIZE; i++) {
    	if (XLlFifo_iTxVacancy(&fifo)) {
    		vacancy = XLlFifo_iTxVacancy(&fifo);
    		// Note that XLlFifo_TxPutWord does not support 64-bit
    		// XLlFifo_TxPutWord(&fifo, data_to_send[i]);
    		Xil_Out64(fifo.Axi4BaseAddress +
    							XLLF_AXI4_TDFD_OFFSET, data_to_send[i]);
    	} else {
    		printf("No vacancy\n");
    	}
    }
    // Transmit and wait for verification
    u32 set_length = (BUFFER_SIZE*WORD_SIZE);
    printf("set_length=%d\n", set_length);
    XLlFifo_iTxSetLen(&fifo, set_length);
    while ( XLlFifo_IsTxDone(&fifo) == FALSE ) {
    	u32 status = XLlFifo_Status(&fifo);
//    	printf("Status=%0llx\n", status);
    }

    // Receive data from other FIFO
     int recv_len;
     u64 rx_word;
     printf("Receiving Response now\n");
     while(XLlFifo_iRxOccupancy(&fifo)) {
     	recv_len = (XLlFifo_iRxGetLen(&fifo)) / WORD_SIZE;
//     	xil_printf("RECV_LEN: %d\n", recv_len);
     	for (int j=0; j<recv_len; j++) {
     		//rx_word = XLlFifo_RxGetWord(&fifo);
     		rx_word = Xil_In64(fifo.Axi4BaseAddress + XLLF_AXI4_RDFD_OFFSET);
     		data_to_recv[j] = rx_word;
     		printf("RECV: 0x%llx\n", rx_word);
     	}
     }

     status = XLlFifo_IsRxDone(&fifo);
     if (status != 1) {
    	 printf("Receive failed %d\n", status);
     }

     int failure_count = 0;
	 for (int k=0; k<BUFFER_SIZE; k++) {
		 if (data_to_send[k] != data_to_recv[k]) {
//			 printf("SENT 0x%llx != RECV 0x%llx\n", data_to_send[k], data_to_recv[k]);
			 failure_count++;
		 }
	 }
	 printf("SENT[0] 0x%llx,  RECV[0] 0x%llx\n", data_to_send[0], data_to_recv[0]);
}


void fifo_busy_wait(int interval_s)
{
    // Loop infinitely, sleeping interval_s seconds
    int counter = 0;
    while (1) {
    	xil_printf("Counter: %d\n", counter++);
    	sleep(interval_s);
    }
}
