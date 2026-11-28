PS5_PAYLOAD_SDK ?= /tmp/ps5sdk
include $(PS5_PAYLOAD_SDK)/toolchain/prospero.mk

TARGET := arabi_hub.elf
SRCS   := arabi_hub.c

all: dashboard_html.h $(TARGET)

dashboard_html.h: loader.html
	python3 -c 'data=open("loader.html","rb").read(); open("dashboard_html.h","w").write("static const unsigned char DASHBOARD_HTML[] = {" + ",".join(str(b) for b in data) + "};\nstatic const size_t DASHBOARD_HTML_LEN = " + str(len(data)) + ";\n")'

$(TARGET): $(SRCS) dashboard_html.h
	$(CC) $(CFLAGS) -O2 -Wall -o $@ $(SRCS) $(LDFLAGS)

clean:
	rm -f $(TARGET) dashboard_html.h
