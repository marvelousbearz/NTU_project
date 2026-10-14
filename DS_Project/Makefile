CXX ?= c++
CXXFLAGS ?= -std=c++17 -O2 -Wall -Wextra -Wpedantic
JAVAC ?= javac
JAVACFLAGS ?= --release 11

SERVER_TARGET := flight_server
SERVER_SOURCE := src/server.cpp
CLIENT_TARGET := flight_client
CLIENT_SOURCE := src/client.cpp
JAVA_CLIENT_CLASS := build/java/FlightClient.class
JAVA_CLIENT_SOURCE := src/java/FlightClient.java

.PHONY: all clients java-client test clean

all: $(SERVER_TARGET) clients

clients: $(CLIENT_TARGET) $(JAVA_CLIENT_CLASS)

$(SERVER_TARGET): $(SERVER_SOURCE)
	$(CXX) $(CXXFLAGS) $(SERVER_SOURCE) -o $(SERVER_TARGET)

$(CLIENT_TARGET): $(CLIENT_SOURCE)
	$(CXX) $(CXXFLAGS) $(CLIENT_SOURCE) -o $(CLIENT_TARGET)

$(JAVA_CLIENT_CLASS): $(JAVA_CLIENT_SOURCE)
	mkdir -p build/java
	$(JAVAC) $(JAVACFLAGS) -d build/java $(JAVA_CLIENT_SOURCE)

java-client: $(JAVA_CLIENT_CLASS)

test: $(SERVER_TARGET)
	python3 -m unittest discover -s tests -v

clean:
	$(RM) $(SERVER_TARGET) $(CLIENT_TARGET)
	$(RM) -r build/java
