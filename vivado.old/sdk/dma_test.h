
#include "xaxidma.h"
#include "xaxidma_bd.h"

typedef struct {
	u32 tx_bd_space_base;
	u32 tx_bd_space_high;
	u32 rx_bd_space_base;
	u32 rx_bd_space_high;
	u32 tx_buffer_base;
	u32 rx_buffer_base;
	u32 rx_buffer_high;
} AxiDma_Mem;


int dma_loopback_single(int dma_device_id);
void dma_busy_wait(int interval_s);

int start_dma(XAxiDma *axi_dma, int device_id, AxiDma_Mem * axi_dma_mem);
int send_dma_packet(XAxiDma *axi_dma, AxiDma_Mem * axi_dma_mem, u64 *buffer, u32 buffer_len);

int CheckDmaResult(XAxiDma * AxiDmaInstPtr, AxiDma_Mem * axi_dma_mem);

int listen_to_dma(int dma_device_id);

int receive_dma_packet(XAxiDma * AxiDmaInstPtr,
					   AxiDma_Mem * axi_dma_mem,
					   u32 *o_bytes_read,
					   u64 *buf_to_recv,
					   u32 buf_to_recv_len);
