PS5_PAYLOAD_SDK ?= /opt/ps5-payload-sdk
CC := $(PS5_PAYLOAD_SDK)/bin/prospero-clang
CFLAGS := -O2 -Wall -Wextra

all: arabi_scanner_poc.elf arabi_afr_poc.elf

arabi_scanner_poc.elf: arabi_scanner_poc.c
	$(CC) $(CFLAGS) $< -o $@

arabi_afr_poc.elf: arabi_afr_poc.c
	$(CC) $(CFLAGS) $< -o $@

clean:
	rm -f arabi_scanner_poc.elf arabi_afr_poc.elf
